"""Streaming speech recognition contract."""

from dataclasses import dataclass
from typing import AsyncIterator, Protocol

from vlt.audio.base import AudioChunk


@dataclass(frozen=True)
class Recognition:
    text: str
    language: str
    start_ms: int
    end_ms: int
    is_final: bool


class SpeechRecognitionBackend(Protocol):
    async def start(self) -> None: ...
    async def push_audio(self, chunk: AudioChunk) -> None: ...
    def results(self) -> AsyncIterator[Recognition]: ...
    async def stop(self) -> None: ...

