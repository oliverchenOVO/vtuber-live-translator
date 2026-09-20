"""Connect an existing PCM capture stream to a replaceable ASR backend."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable

from vlt.asr.base import ASRBackend, Recognition, StatusCallback
from vlt.audio.base import AudioCaptureBackend


class ASRPipeline:
    def __init__(self, audio: AudioCaptureBackend, backend_factory: Callable[[], ASRBackend],
                 language: str, on_partial: Callable[[Recognition], None],
                 on_final: Callable[[Recognition], None], on_status: StatusCallback,
                 on_audio_anchor: Callable[[int], None] | None = None):
        self.audio = audio
        self.backend_factory = backend_factory
        self.language = language
        self.on_partial = on_partial
        self.on_final = on_final
        self.on_status = on_status
        self.on_audio_anchor = on_audio_anchor or (lambda _timestamp: None)
        self._stop = threading.Event()
        self._backend: ASRBackend | None = None
        self.reconnects = 0

    def stop(self) -> None:
        self._stop.set()

    def set_language(self, language: str) -> None:
        self.language = language
        if self._backend:
            self._backend.set_language(language)

    async def run(self) -> None:
        delay = 1.0
        while not self._stop.is_set() and getattr(self.audio, "state", "capturing") == "capturing":
            backend = self.backend_factory()
            self._backend = backend
            backend.set_language(self.language)
            backend.set_callbacks(self.on_partial, self.on_final, self.on_status)
            failed = False
            connected_at = 0.0
            try:
                self.on_status("connecting" if not self.reconnects else "reconnecting",
                               "正在連接語音辨識…" if not self.reconnects else "語音辨識中斷，正在重新連接…")
                await asyncio.wait_for(backend.start(), timeout=180)
                connected_at = asyncio.get_running_loop().time()
                anchored = False
                async for chunk in self.audio.audio_stream():
                    if self._stop.is_set() or getattr(self.audio, "state", "capturing") != "capturing":
                        break
                    if backend.get_status() == "error":
                        raise RuntimeError("ASR backend stopped")
                    if not anchored:
                        self.on_audio_anchor(chunk.timestamp_ms)
                        anchored = True
                    await asyncio.wait_for(backend.push_audio(chunk), timeout=5)
                if not self._stop.is_set() and getattr(self.audio, "state", "capturing") == "capturing":
                    raise RuntimeError("Audio stream unexpectedly ended")
                break
            except Exception:
                logging.exception("ASR connection failed")
                if not self._stop.is_set() and getattr(self.audio, "state", "capturing") == "capturing":
                    self.reconnects += 1
                    failed = True
            finally:
                try:
                    await backend.stop()
                except Exception:
                    logging.exception("ASR backend stop failed")
                self._backend = None
            if failed:
                if connected_at and asyncio.get_running_loop().time() - connected_at > 30:
                    delay = 1.0
                self.on_status("reconnecting", f"語音辨識中斷，{delay:g} 秒後重試…")
                await asyncio.to_thread(self._stop.wait, delay)
                delay = min(delay * 2, 30.0)
        self.on_status("idle", "語音辨識已停止")
