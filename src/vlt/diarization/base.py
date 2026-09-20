"""Speaker identity contract; session speaker IDs remain immutable."""

from dataclasses import dataclass
from typing import Protocol

from vlt.audio.base import AudioChunk


@dataclass(frozen=True)
class SpeakerDecision:
    speaker_id: str | None
    confidence: float
    overlapping: bool = False


class DiarizationBackend(Protocol):
    async def identify(self, chunk: AudioChunk) -> SpeakerDecision: ...
    async def reset_session(self) -> None: ...

