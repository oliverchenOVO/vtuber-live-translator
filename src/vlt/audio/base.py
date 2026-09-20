"""Platform independent audio capture contract; implementations arrive in Phase 2."""

from dataclasses import dataclass
from typing import AsyncIterator, Protocol


@dataclass(frozen=True)
class AudioSource:
    id: str
    label: str
    kind: str


@dataclass(frozen=True)
class AudioChunk:
    pcm: bytes
    sample_rate: int
    channels: int
    timestamp_ms: int


class AudioCaptureBackend(Protocol):
    async def list_sources(self) -> list[AudioSource]: ...
    async def select_source(self, source_id: str) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    def audio_stream(self) -> AsyncIterator[AudioChunk]: ...

