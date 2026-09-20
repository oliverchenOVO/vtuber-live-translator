from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
import time
from dataclasses import field


@dataclass(frozen=True)
class TranslationRequest:
    segment_id: str
    original: str
    source_language: str
    target_language: str
    style: str
    context: tuple[str, ...] = ()
    glossary: tuple[dict, ...] = ()
    final: bool = False
    session_id: str = ""
    submitted_at: float = field(default_factory=time.monotonic)


class TranslationBackend(Protocol):
    def translate_partial(self, request: TranslationRequest) -> str: ...
    def translate_final(self, request: TranslationRequest) -> str: ...
    def set_target_language(self, language: str) -> None: ...
    def set_style(self, style: str) -> None: ...
    def update_context(self, context: tuple[str, ...]) -> None: ...
    def update_glossary(self, glossary: tuple[dict, ...]) -> None: ...
