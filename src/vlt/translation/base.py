"""Translation contract; context must never add facts absent from the utterance."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TranslationRequest:
    original: str
    source_language: str
    target_language: str
    style: str
    recent_dialogue: tuple[str, ...] = ()


class TranslationBackend(Protocol):
    async def translate(self, request: TranslationRequest) -> str: ...

