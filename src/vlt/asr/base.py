"""Provider independent streaming ASR contract."""

from dataclasses import dataclass
from typing import Callable, Protocol

from vlt.audio.base import AudioChunk


@dataclass(frozen=True)
class Recognition:
    utterance_id: str
    text: str
    language: str
    start_ms: int
    end_ms: int
    is_final: bool
    first_audio_at: float | None = None
    speech_end_at: float | None = None


RecognitionCallback = Callable[[Recognition], None]
StatusCallback = Callable[[str, str], None]


class ASRBackend(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def push_audio(self, chunk: AudioChunk) -> None: ...
    def set_language(self, language: str) -> None: ...
    def set_callbacks(self, on_partial: RecognitionCallback,
                      on_final: RecognitionCallback, on_status: StatusCallback) -> None: ...
    def get_status(self) -> str: ...

