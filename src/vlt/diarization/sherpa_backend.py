"""Bounded CPU diarization of the existing 16 kHz process-loopback PCM stream."""

from __future__ import annotations

import hashlib
import logging
import queue
import tarfile
import threading
import time
import urllib.request
from collections import deque
from pathlib import Path
from typing import Callable

import numpy as np

from vlt.audio.base import AudioChunk
from vlt.diarization.base import SpeakerDecision, SpeakerObservation
from vlt.product.downloads import download_resumable

SEGMENTATION_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
                    "speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2")
EMBEDDING_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
                 "speaker-recongition-models/3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx")
LEGACY_EMBEDDING_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
                        "speaker-recongition-models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx")
SEGMENTATION_SHA256 = "24615ee884c897d9d2ba09bb4d30da6bb1b15e685065962db5b02e76e4996488"
SEGMENTATION_MODEL_SHA256 = "d582f4b4c6b48205de7e0643c57df0df5615a3c176189be3fc461e9d18827b5d"
EMBEDDING_SHA256 = "aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2"
LEGACY_EMBEDDING_SHA256 = "1a331345f04805badbb495c775a6ddffcdd1a732567d5ec8b3d5749e3c7a5e4b"


def _download_verified(url: str, path: Path, digest: str) -> None:
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == digest:
        return
    download_resumable(url, path, digest)


def ensure_models(root: Path, *, legacy: bool = False) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    seg = root / "segmentation.onnx"
    emb = root / ("embedding.onnx" if legacy else "embedding-campplus.onnx")
    if not seg.exists() or hashlib.sha256(seg.read_bytes()).hexdigest() != SEGMENTATION_MODEL_SHA256:
        archive = root / "segmentation.tar.bz2"
        _download_verified(SEGMENTATION_URL, archive, SEGMENTATION_SHA256)
        temp = seg.with_suffix(".onnx.download")
        with tarfile.open(archive, "r:bz2") as tar:
            member = tar.getmember("sherpa-onnx-pyannote-segmentation-3-0/model.int8.onnx")
            with tar.extractfile(member) as source, temp.open("wb") as target:
                while data := source.read(1024 * 1024):
                    target.write(data)
        if hashlib.sha256(temp.read_bytes()).hexdigest() != SEGMENTATION_MODEL_SHA256:
            temp.unlink(missing_ok=True)
            raise RuntimeError("Diarization model checksum mismatch")
        temp.replace(seg)
    _download_verified(LEGACY_EMBEDDING_URL if legacy else EMBEDDING_URL, emb,
                       LEGACY_EMBEDDING_SHA256 if legacy else EMBEDDING_SHA256)
    return seg, emb


def _normalized(vector: list[float] | np.ndarray) -> np.ndarray:
    value = np.asarray(vector, dtype=np.float32)
    norm = np.linalg.norm(value)
    return value / norm if norm > 0 else value


class SherpaOnnxDiarizationBackend:
    """One worker; 20 s PCM window, 256 queued chunks, 180 observations, 3 embeddings/voice."""

    MAX_CHUNK_BYTES = 16000 * 2  # At most one second per queued item.

    def __init__(self, model_dir: Path, max_speakers: int = 4, process_interval_ms: int = 3000):
        self.model_dir = model_dir
        self.max_speakers = max(1, max_speakers)
        self.process_interval_ms = max(1000, int(process_interval_ms))
        self._queue: queue.Queue[AudioChunk] = queue.Queue(maxsize=256)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._observations: deque[SpeakerObservation] = deque(maxlen=180)
        self._overlap_sent: deque[tuple[int, int]] = deque(maxlen=100)
        self._profiles: dict[str, list[np.ndarray]] = {}
        self._legacy_model = False
        self._joined_ms: dict[str, int] = {}
        self._unprofiled: list[str] = []
        self._next_number = 1
        self._candidates: list[tuple[np.ndarray, int, int]] = []
        self._speaker_callback: Callable[[str], None] = lambda _id: None
        self._overlap_callback: Callable[[SpeakerObservation], None] = lambda _obs: None
        self._update_callback: Callable[[], None] = lambda: None
        self.status = "idle"
        self.latency_ms: float | None = None
        self.dropped_chunks = 0
        self.processed_windows = 0

    def on_speaker_detected(self, callback: Callable[[str], None]) -> None:
        self._speaker_callback = callback

    def on_overlap_detected(self, callback: Callable[[SpeakerObservation], None]) -> None:
        self._overlap_callback = callback

    def on_updated(self, callback: Callable[[], None]) -> None:
        self._update_callback = callback

    def reset_session(self, speakers: list[dict], embeddings: dict[str, list[list[float]]]) -> None:
        with self._lock:
            self._legacy_model = any(len(v) == 512 for vectors in embeddings.values() for v in vectors)
            expected = 512 if self._legacy_model else 192
            self._profiles = {speaker: usable for speaker, vectors in embeddings.items()
                              if (usable := [_normalized(v) for v in vectors[:3] if len(v) == expected])}
            self._unprofiled = [item["speaker_id"] for item in speakers
                                if item["speaker_id"] not in self._profiles]
            self._next_number = max((int(item["speaker_id"].split("_")[-1]) for item in speakers
                                     if item["speaker_id"].startswith("speaker_")), default=0) + 1
            self._observations.clear()
            self._overlap_sent.clear()
            self._candidates.clear()

    def set_next_number(self, number: int) -> None:
        with self._lock:
            self._next_number = max(self._next_number, number)

    def remap_speaker(self, source_id: str, target_id: str) -> None:
        with self._lock:
            source = self._profiles.pop(source_id, [])
            target = self._profiles.setdefault(target_id, [])
            target.extend(source[:max(0, 3 - len(target))])
            self._unprofiled = [s for s in self._unprofiled if s != source_id]
            self._observations = deque(
                [SpeakerObservation(o.start_ms, o.end_ms,
                                    target_id if o.speaker_id == source_id else o.speaker_id,
                                    o.confidence, o.overlapping,
                                    tuple(target_id if s == source_id else s for s in o.speaker_ids))
                 for o in self._observations], maxlen=180)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        if self._stop.is_set():
            raise RuntimeError("Stopped speaker workers cannot be restarted; create a new backend.")
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="diarization-cpu", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        if not self._thread or not self._thread.is_alive():
            self._thread = None
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def push_audio(self, chunk: AudioChunk) -> None:
        if chunk.sample_rate != 16000 or chunk.channels != 1:
            return
        if len(chunk.pcm) > self.MAX_CHUNK_BYTES:
            chunk = AudioChunk(chunk.pcm[-self.MAX_CHUNK_BYTES:], chunk.sample_rate,
                               chunk.channels, chunk.timestamp_ms)
            self.dropped_chunks += 1
        try:
            self._queue.put_nowait(chunk)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            self.dropped_chunks += 1
            try:
                self._queue.put_nowait(chunk)
            except queue.Full:
                self.dropped_chunks += 1

    def get_representation(self, speaker_id: str) -> list[float] | None:
        with self._lock:
            vectors = self._profiles.get(speaker_id)
            return vectors[0].tolist() if vectors else None

    def get_representations(self, speaker_id: str) -> list[list[float]]:
        with self._lock:
            return [vector.tolist() for vector in self._profiles.get(speaker_id, [])[:3]]

    def joined_ms(self, speaker_id: str) -> int:
        with self._lock:
            return self._joined_ms.get(speaker_id, 0)

    def get_speaker_for_interval(self, start_ms: int, end_ms: int) -> SpeakerDecision:
        with self._lock:
            observations = list(self._observations)
        coverage: dict[str, float] = {}
        overlapping = False
        speaker_ids: set[str] = set()
        for obs in observations:
            intersection = max(0, min(end_ms, obs.end_ms) - max(start_ms, obs.start_ms))
            if not intersection:
                continue
            if obs.overlapping:
                overlapping = True
                speaker_ids.update(obs.speaker_ids)
            elif obs.speaker_id:
                coverage[obs.speaker_id] = coverage.get(obs.speaker_id, 0.0) + intersection * obs.confidence
        if overlapping:
            return SpeakerDecision(None, 0.0, True, tuple(sorted(speaker_ids)))
        total = sum(coverage.values())
        if not total:
            return SpeakerDecision(None, 0.0)
        best_id, best = max(coverage.items(), key=lambda pair: pair[1])
        confidence = best / total
        if confidence < 0.72 or best < (end_ms - start_ms) * 0.35:
            return SpeakerDecision(None, confidence)
        return SpeakerDecision(best_id, confidence)

    def _identify(self, embedding: np.ndarray, start_ms: int, end_ms: int,
                  excluded: set[str] | None = None) -> tuple[str | None, float]:
        with self._lock:
            self._candidates = [candidate for candidate in self._candidates
                                if start_ms - candidate[2] <= 15000]
            if not self._profiles and self._unprofiled:
                speaker = self._unprofiled.pop(0)
                self._profiles[speaker] = [embedding]
                self._joined_ms[speaker] = start_ms
                self._speaker_callback(speaker)
                return speaker, 0.8
            all_scores = sorted(((float(max(np.dot(embedding, v) for v in vectors)), speaker)
                                 for speaker, vectors in self._profiles.items() if vectors), reverse=True)
            if all_scores and all_scores[0][0] >= 0.6 and all_scores[0][1] in (excluded or set()):
                # Two overlapping local clusters look like the same voice. Their assignment
                # is uncertain; creating another immutable ID would duplicate that person.
                return None, all_scores[0][0]
            scores = [(score, speaker) for score, speaker in all_scores
                      if speaker not in (excluded or set())]
            # A clean match to an existing profile wins over a tentative candidate.
            # Otherwise a noisy first window can later be promoted to a duplicate ID.
            if scores and scores[0][0] >= 0.6 and (len(scores) == 1 or scores[0][0] - scores[1][0] >= 0.07):
                speaker = scores[0][1]
                if len(self._profiles[speaker]) < 3 and end_ms - start_ms >= 1500:
                    self._profiles[speaker].append(embedding)
                return speaker, min(0.98, scores[0][0])
            if not self._legacy_model and scores and scores[0][0] >= 0.48:
                # CampPlus can score a changed delivery from the same voice around 0.5.
                # Neither create a duplicate ID nor force an uncertain existing identity.
                self._candidates = [candidate for candidate in self._candidates
                                    if float(np.dot(candidate[0], embedding)) < 0.46]
                return None, scores[0][0]
            for index, (candidate, count, last_end) in enumerate(self._candidates):
                candidate_score = float(np.dot(candidate, embedding))
                if (candidate_score >= 0.46 and start_ms >= last_end - 200 and
                        (not scores or candidate_score >= scores[0][0] + 0.10)):
                    if len(self._profiles) >= 3:
                        # At this point a fourth ID is especially costly: similar voices
                        # in a three-person stream can form a noisy temporary cluster.
                        # Require both clear novelty and a third separate observation.
                        if scores and scores[0][0] >= 0.40:
                            self._candidates.pop(index)
                            return None, scores[0][0]
                        if count < 2:
                            self._candidates[index] = (
                                _normalized(candidate + embedding), count + 1, end_ms)
                            return None, 0.0
                    if len(self._profiles) >= self.max_speakers:
                        self.status = "limited"
                        return None, 0.0
                    self._candidates.pop(index)
                    return self._create_speaker(embedding, start_ms), 0.78
            if scores and scores[0][0] >= 0.34 and (len(scores) == 1 or scores[0][0] - scores[1][0] >= 0.07):
                speaker = scores[0][1]
                if len(self._profiles[speaker]) < 3 and end_ms - start_ms >= 1500:
                    self._profiles[speaker].append(embedding)
                return speaker, min(0.98, scores[0][0])
            if scores and scores[0][0] >= 0.27:
                return None, scores[0][0]
            if len(self._profiles) >= self.max_speakers:
                self.status = "limited"
                return None, 0.0
            if len(self._candidates) >= 8:
                self._candidates.pop(0)
            self._candidates.append((embedding, 1, end_ms))
            return None, 0.0

    def _create_speaker(self, embedding: np.ndarray, joined_ms: int) -> str:
        speaker = f"speaker_{self._next_number:03d}"
        self._next_number += 1
        self._profiles[speaker] = [embedding]
        self._joined_ms[speaker] = joined_ms
        self._speaker_callback(speaker)
        return speaker

    def _run(self) -> None:
        try:
            import sherpa_onnx
            segmentation, embedding_model = ensure_models(self.model_dir, legacy=self._legacy_model)
            config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
                segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                    pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                        model=str(segmentation), window_shift_ratio=0.1)),
                embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                    model=str(embedding_model), num_threads=1, provider="cpu"),
                clustering=sherpa_onnx.FastClusteringConfig(
                    num_clusters=-1, threshold=0.5 if self._legacy_model else 0.55),
                min_duration_on=0.3, min_duration_off=0.5)
            diarizer = sherpa_onnx.OfflineSpeakerDiarization(config)
            extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
                sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                    model=str(embedding_model), num_threads=1, provider="cpu"))
            self.status = "live"
            pcm = bytearray()
            window_start = 0
            first_timestamp: int | None = None
            last_chunk_timestamp: int | None = None
            last_process_end = 0
            while not self._stop.is_set():
                try:
                    chunk = self._queue.get(timeout=0.3)
                except queue.Empty:
                    continue
                if first_timestamp is None:
                    first_timestamp = chunk.timestamp_ms
                duration_ms = len(chunk.pcm) // 32
                relative_end = max(0, chunk.timestamp_ms - first_timestamp)
                if not pcm:
                    window_start = max(0, relative_end - duration_ms)
                elif last_chunk_timestamp is not None:
                    gap_ms = chunk.timestamp_ms - last_chunk_timestamp - duration_ms
                    if gap_ms > 2000:
                        pcm.clear()
                        window_start = max(0, relative_end - duration_ms)
                    elif gap_ms > 250:
                        pcm.extend(bytes(gap_ms * 32))
                pcm.extend(chunk.pcm)
                last_chunk_timestamp = chunk.timestamp_ms
                if len(pcm) > 20 * 16000 * 2:
                    cut = len(pcm) - 20 * 16000 * 2
                    cut -= cut % 2
                    del pcm[:cut]
                    window_start += cut // 32
                window_end = window_start + len(pcm) // 32
                if window_end - last_process_end < self.process_interval_ms or len(pcm) < 6 * 16000 * 2:
                    continue
                previous_end = last_process_end
                last_process_end = window_end
                started = time.monotonic()
                audio = np.frombuffer(bytes(pcm), dtype="<i2").astype(np.float32) / 32768.0
                results = diarizer.process(audio).sort_by_start_time()
                if self._stop.is_set():
                    break
                fresh: list[SpeakerObservation] = []
                local_ids: dict[int, str] = {}
                local_intervals: list[tuple[str, int, int]] = []
                with self._lock:
                    previous_observations = list(self._observations)
                for result in results:
                    start = window_start + int(result.start * 1000)
                    end = window_start + int(result.end * 1000)
                    if end <= previous_end - 500 or end - start < 800:
                        continue
                    sample = audio[max(0, int(result.start * 16000)):
                                   min(len(audio), int(result.end * 16000))]
                    if len(sample) < 12800:
                        continue
                    stream = extractor.create_stream()
                    stream.accept_waveform(sample_rate=16000, waveform=sample)
                    stream.input_finished()
                    vector = _normalized(extractor.compute(stream))
                    simultaneous = {known for known, known_start, known_end in local_intervals
                                    if min(end, known_end) - max(start, known_start) >= 300}
                    speaker = local_ids.get(result.speaker)
                    confidence = 0.85 if speaker else 0.0
                    if not speaker:
                        aligned = [(min(end, old.end_ms) - max(start, old.start_ms), old)
                                   for old in previous_observations if old.speaker_id and not old.overlapping]
                        aligned = [(span, old) for span, old in aligned
                                   if span >= min(500, (end - start) * 0.5)]
                        if aligned:
                            best = max(aligned, key=lambda pair: pair[0])[1]
                            if best.speaker_id not in simultaneous:
                                speaker, confidence = best.speaker_id, max(0.7, best.confidence)
                    if not speaker:
                        speaker, confidence = self._identify(vector, start, end, simultaneous)
                    if speaker:
                        local_ids[result.speaker] = speaker
                        local_intervals.append((speaker, start, end))
                    fresh.append(SpeakerObservation(start, end, speaker, confidence))
                with self._lock:
                    self._observations.extend(fresh)
                    self.processed_windows += 1
                    self.latency_ms = (time.monotonic() - started) * 1000
                for a, b in zip(fresh, fresh[1:]):
                    overlap = min(a.end_ms, b.end_ms) - max(a.start_ms, b.start_ms)
                    if overlap >= 300 and a.speaker_id != b.speaker_id:
                        ids = tuple(sorted({s for s in (a.speaker_id, b.speaker_id) if s}))
                        event = SpeakerObservation(max(a.start_ms, b.start_ms),
                                                   min(a.end_ms, b.end_ms), None, 0.7,
                                                   True, ids)
                        with self._lock:
                            duplicate = any(max(0, min(event.end_ms, old_end) -
                                                max(event.start_ms, old_start)) >=
                                            0.8 * min(event.end_ms - event.start_ms,
                                                      old_end - old_start)
                                            for old_start, old_end in self._overlap_sent)
                            if duplicate:
                                continue
                            self._overlap_sent.append((event.start_ms, event.end_ms))
                        with self._lock:
                            self._observations.append(event)
                        self._overlap_callback(event)
                self._update_callback()
        except Exception:
            self.status = "error"
            logging.exception("Diarization stopped; ASR and translation continue")
