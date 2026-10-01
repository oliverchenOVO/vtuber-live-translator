"""Live VAD utterances with replaceable local faster-whisper inference."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# Windows oneMKL's per-thread fast allocator retains buffers across CT2 worker
# lifetimes (~35 MiB for each Start/Stop in the RC probe). Configure it before
# importing the native runtime; inference still uses the same model and settings.
# https://www.intel.com/content/www/us/en/docs/onemkl/developer-guide-windows/2024-2/avoiding-memory-leaks-in-onemkl.html
if sys.platform == "win32":
    os.environ.setdefault("MKL_DISABLE_FAST_MM", "1")

import numpy as np
import webrtcvad
import ctranslate2
from faster_whisper import WhisperModel

from vlt.asr.base import Recognition, RecognitionCallback, StatusCallback
from vlt.asr.queue import BoundedAudioQueue
from vlt.audio.base import AudioChunk


@dataclass(frozen=True)
class _Inference:
    utterance_id: str
    pcm: bytes
    start_ms: int
    end_ms: int
    is_final: bool
    first_audio_at: float
    speech_end_at: float | None


class FasterWhisperBackend:
    SAMPLE_RATE = 16_000
    FRAME_BYTES = 640  # 20 ms, mono signed int16
    MAX_UTTERANCE_BYTES = 15 * SAMPLE_RATE * 2

    def __init__(self, model_name: str = "base", model_dir: Path | None = None,
                 device: str = "auto", cpu_threads: int = 4,
                 model_factory: Callable[..., object] = WhisperModel):
        self.model_name = model_name
        self.model_dir = model_dir
        self.device = device
        self.cpu_threads = max(1, int(cpu_threads))
        self._model_factory = model_factory
        self._model = None
        self._active_device = "cpu"
        self._language = "auto"
        self._status = "idle"
        self._status_message = ""
        self._on_partial: RecognitionCallback = lambda result: None
        self._on_final: RecognitionCallback = lambda result: None
        self._on_status: StatusCallback = lambda state, message: None
        self.queue = BoundedAudioQueue()
        self._requests: asyncio.Queue[_Inference | None] = asyncio.Queue(maxsize=1)
        self._inference_busy = False
        self._consumer: asyncio.Task | None = None
        self._infer_worker: asyncio.Task | None = None
        self._running = False
        self._vad = webrtcvad.Vad(2)
        self._frame_bytes = bytearray()
        self._pre_roll: deque[bytes] = deque(maxlen=10)
        self._voice_votes: deque[bool] = deque(maxlen=5)
        self._utterance = bytearray()
        self._utterance_id = ""
        self._utterance_start_ms = 0
        self._last_voice_ms = 0
        self._silence_frames = 0
        self._last_partial_request_ms = 0
        self._first_audio_at = 0.0
        self._last_voice_at = 0.0
        self._processed_ms = 0
        self._first_chunk_timestamp: int | None = None
        self._last_chunk_timestamp = 0
        self._last_dropped_bytes = 0
        self.gap_finalizations = 0

    def set_callbacks(self, on_partial: RecognitionCallback,
                      on_final: RecognitionCallback, on_status: StatusCallback) -> None:
        self._on_partial = on_partial
        self._on_final = on_final
        self._on_status = on_status

    def set_language(self, language: str) -> None:
        if language not in ("auto", "ja", "en"):
            raise ValueError("Supported languages are auto, ja and en")
        self._language = language

    def get_status(self) -> str:
        return self._status

    def _set_status(self, state: str, message: str) -> None:
        if state != self._status or message != self._status_message:
            self._status = state
            self._status_message = message
            self._on_status(state, message)

    async def start(self) -> None:
        if self._running:
            return
        self._set_status("connecting", "正在啟動本機語音辨識；首次使用可能需要下載資料。")
        try:
            use_cuda = self.device != "cpu" and ctranslate2.get_cuda_device_count() > 0
        except Exception:
            logging.exception("CUDA device inspection failed; using CPU")
            use_cuda = False
        kwargs = {"device": "cuda" if use_cuda else "cpu",
                  "compute_type": "float16" if use_cuda else "int8", "cpu_threads": self.cpu_threads}
        if self.model_dir is not None:
            kwargs["download_root"] = str(self.model_dir)
        try:
            self._model = await asyncio.to_thread(self._model_factory, self.model_name, **kwargs)
            self._active_device = kwargs["device"]
        except Exception:
            if not use_cuda:
                raise
            logging.exception("CUDA ASR unavailable; falling back to CPU")
            kwargs.update(device="cpu", compute_type="int8")
            self._model = await asyncio.to_thread(self._model_factory, self.model_name, **kwargs)
            self._active_device = "cpu"
        self._running = True
        self._consumer = asyncio.create_task(self._consume(), name="asr-vad")
        self._infer_worker = asyncio.create_task(self._infer_loop(), name="asr-inference")
        self._set_status("live", f"本機語音辨識已連接 ({self._active_device.upper()})，正在等待語音…")

    async def stop(self) -> None:
        if not self._running:
            self._set_status("idle", "語音辨識已停止")
            return
        self._running = False
        if self._utterance and self._infer_worker and not self._infer_worker.done():
            await self._finish_utterance()
        if self._consumer:
            self._consumer.cancel()
            try:
                await self._consumer
            except asyncio.CancelledError:
                pass
            except Exception:
                pass  # The consumer already reported a human-readable error.
        if self._infer_worker:
            if not self._infer_worker.done():
                await self._requests.put(None)
            try:
                await self._infer_worker
            except Exception:
                pass  # The inference worker already reported the error.
        self.queue.clear()
        # Completed/cancelled Tasks can retain traceback frames and this backend.
        # Release heavy native weights explicitly after all inference has drained.
        unload = getattr(getattr(self._model, "model", None), "unload_model", None)
        if unload:
            await asyncio.to_thread(unload)
        self._model = None
        self._consumer = None
        self._infer_worker = None
        self._frame_bytes.clear()
        self._reset_utterance()
        self._set_status("idle", "語音辨識已停止")

    async def push_audio(self, chunk: AudioChunk) -> None:
        if chunk.sample_rate != self.SAMPLE_RATE or chunk.channels != 1 or len(chunk.pcm) % 2:
            raise ValueError("ASR requires 16 kHz mono int16 PCM")
        if self._running:
            self.queue.push(chunk)

    async def _consume(self) -> None:
        try:
            while self._running:
                chunk = await self.queue.pop()
                if self.queue.dropped_bytes != self._last_dropped_bytes:
                    self._last_dropped_bytes = self.queue.dropped_bytes
                    self._reset_utterance()
                    self._frame_bytes.clear()
                    self._set_status("live", "辨識暫時落後，已略過較舊音訊。")
                if self._last_chunk_timestamp and chunk.timestamp_ms - self._last_chunk_timestamp > 500:
                    # Process loopback may omit silent packets. Finish a speech turn before
                    # clearing the framing state instead of silently discarding its Final.
                    if self._utterance:
                        await self._finish_utterance()
                        self.gap_finalizations += 1
                    self._frame_bytes.clear()
                if self._first_chunk_timestamp is None:
                    self._first_chunk_timestamp = chunk.timestamp_ms
                self._processed_ms = max(self._processed_ms,
                                         chunk.timestamp_ms - self._first_chunk_timestamp)
                self._last_chunk_timestamp = chunk.timestamp_ms
                self._frame_bytes.extend(chunk.pcm)
                while len(self._frame_bytes) >= self.FRAME_BYTES:
                    frame = bytes(self._frame_bytes[:self.FRAME_BYTES])
                    del self._frame_bytes[:self.FRAME_BYTES]
                    await self._process_frame(frame)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("ASR audio consumer failed")
            self._set_status("error", "語音辨識暫時中斷，正在重新連接。")
            raise

    async def _process_frame(self, frame: bytes) -> None:
        now = time.monotonic()
        frame_start_ms = self._processed_ms
        self._processed_ms += 20
        voiced = self._vad.is_speech(frame, self.SAMPLE_RATE)
        self._pre_roll.append(frame)
        self._voice_votes.append(voiced)
        if not self._utterance:
            if len(self._voice_votes) >= 5 and sum(self._voice_votes) >= 3:
                self._utterance_id = str(uuid.uuid4())
                self._utterance_start_ms = max(0, frame_start_ms - (len(self._pre_roll) - 1) * 20)
                self._utterance = bytearray(b"".join(self._pre_roll))
                self._first_audio_at = now - len(self._pre_roll) * 0.02
                self._last_voice_ms = self._processed_ms
                self._last_voice_at = now
                self._silence_frames = 0
                self._last_partial_request_ms = self._processed_ms
            return
        self._utterance.extend(frame)
        if voiced:
            self._last_voice_ms = self._processed_ms
            self._last_voice_at = now
            self._silence_frames = 0
        else:
            self._silence_frames += 1
        if (len(self._utterance) >= self.SAMPLE_RATE * 2 and
                self._processed_ms - self._last_partial_request_ms >= 1200 and
                self._silence_frames < 30):
            self._last_partial_request_ms = self._processed_ms
            await self._submit_inference(False)
        if self._silence_frames >= 30 or len(self._utterance) >= self.MAX_UTTERANCE_BYTES:
            await self._finish_utterance()

    async def _submit_inference(self, final: bool) -> None:
        request = _Inference(self._utterance_id, bytes(self._utterance),
                             self._utterance_start_ms, self._last_voice_ms,
                             final, self._first_audio_at,
                             self._last_voice_at if final else None)
        if final:
            # A completed turn supersedes any queued snapshot of that same turn.
            if self._requests.full():
                pending = self._requests.get_nowait()
                self._requests.task_done()
                if pending is not None and pending.is_final:
                    await self._requests.put(pending)
            await self._requests.put(request)
        elif not self._requests.full() and not self._inference_busy:
            self._requests.put_nowait(request)

    async def _finish_utterance(self) -> None:
        if self._utterance and len(self._utterance) >= self.SAMPLE_RATE // 2:
            await self._submit_inference(True)
        self._reset_utterance()

    def _reset_utterance(self) -> None:
        self._utterance.clear()
        self._utterance_id = ""
        self._voice_votes.clear()
        self._pre_roll.clear()
        self._silence_frames = 0

    async def _infer_loop(self) -> None:
        while True:
            request = await self._requests.get()
            try:
                if request is None:
                    return
                self._inference_busy = True
                text, language, confidence = await asyncio.to_thread(self._transcribe, request.pcm)
                if not text and not request.is_final:
                    continue
                result = Recognition(request.utterance_id, text, language,
                                     request.start_ms, max(request.start_ms + 1, request.end_ms),
                                     request.is_final, request.first_audio_at, request.speech_end_at,
                                     confidence)
                if request.is_final:
                    self._on_final(result)
                else:
                    self._on_partial(result)
            except Exception:
                logging.exception("ASR inference failed")
                self._set_status("error", "語音辨識暫時中斷，正在重新連接。")
                raise
            finally:
                self._inference_busy = False
                self._requests.task_done()

    def _transcribe(self, pcm: bytes) -> tuple[str, str, float | None]:
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        options = dict(language=None if self._language == "auto" else self._language,
                       task="transcribe", beam_size=1, best_of=1,
                       condition_on_previous_text=False, vad_filter=False,
                       without_timestamps=True)
        try:
            segments, info = self._model.transcribe(samples, **options)
            segments = list(segments)
            text = " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()
        except Exception:
            if self._active_device != "cuda":
                raise
            logging.exception("CUDA ASR inference failed; falling back to CPU")
            kwargs = {"device": "cpu", "compute_type": "int8", "cpu_threads": self.cpu_threads}
            if self.model_dir is not None:
                kwargs["download_root"] = str(self.model_dir)
            self._model = self._model_factory(self.model_name, **kwargs)
            self._active_device = "cpu"
            segments, info = self._model.transcribe(samples, **options)
            segments = list(segments)
            text = " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()
        logprobs = [float(segment.avg_logprob) for segment in segments
                    if getattr(segment, "avg_logprob", None) is not None]
        confidence = float(np.exp(sum(logprobs) / len(logprobs))) if logprobs else None
        return text, info.language or self._language, confidence
