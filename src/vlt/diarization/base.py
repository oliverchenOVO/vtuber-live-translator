"""Replaceable live diarization contract. Times are relative to the PCM stream."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from vlt.audio.base import AudioChunk


@dataclass(frozen=True)
class SpeakerDecision:
    speaker_id: str | None
    confidence: float
    overlapping: bool = False
    speaker_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class SpeakerObservation:
    start_ms: int
    end_ms: int
    speaker_id: str | None
    confidence: float
    overlapping: bool = False
    speaker_ids: tuple[str, ...] = ()


class DiarizationBackend(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def push_audio(self, chunk: AudioChunk) -> None: ...
    def reset_session(self, speakers: list[dict], embeddings: dict[str, list[list[float]]]) -> None: ...
    def get_speaker_for_interval(self, start_ms: int, end_ms: int) -> SpeakerDecision: ...
    def on_speaker_detected(self, callback: Callable[[str], None]) -> None: ...
    def on_overlap_detected(self, callback: Callable[[SpeakerObservation], None]) -> None: ...
    def get_representations(self, speaker_id: str) -> list[list[float]]: ...
