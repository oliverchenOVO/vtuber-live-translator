"""Optional faithful-MT-first policy for a future qualifying backend."""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace

from vlt.translation.base import TranslationBackend, TranslationRequest


def conservative_polish_check(faithful: str, polished: str) -> bool:
    """Cheap guard for Polish; semantic review is still needed before GA use."""
    if not polished.strip() or len(polished) > max(30, len(faithful) * 2):
        return False
    if re.findall(r"\d+(?:[.,]\d+)?", faithful) != re.findall(r"\d+(?:[.,]\d+)?", polished):
        return False
    negative = re.compile(r"不|沒|无|無|未|別|别|不能|不可")
    if bool(negative.search(faithful)) != bool(negative.search(polished)):
        return False
    return True


class FaithfulFirstBackend:
    def __init__(self, faithful: TranslationBackend,
                 polish: Callable[[str, TranslationRequest], str] | None = None):
        self.faithful = faithful
        self.polish = polish
        self.last_state = "faithful_ready"
        self._stage_callback: Callable[[str], None] | None = None

    def set_stage_callback(self, callback: Callable[[str], None]) -> None:
        self._stage_callback = callback

    def _state(self, state: str) -> None:
        self.last_state = state
        if self._stage_callback:
            self._stage_callback(state)

    def set_target_language(self, language: str) -> None:
        self.faithful.set_target_language(language)

    def set_style(self, style: str) -> None:
        self.faithful.set_style(style)

    def update_context(self, context: tuple[str, ...]) -> None:
        self.faithful.update_context(context)

    def update_glossary(self, glossary: tuple[dict, ...]) -> None:
        self.faithful.update_glossary(glossary)

    def translate_partial(self, request: TranslationRequest) -> str:
        return self.faithful.translate_partial(replace(request, style="faithful"))

    def translate_final(self, request: TranslationRequest) -> str:
        faithful = self.faithful.translate_final(replace(request, style="faithful"))
        self._state("faithful_ready")
        if request.style != "natural" or self.polish is None:
            return faithful
        try:
            candidate = self.polish(faithful, request)
            if not conservative_polish_check(faithful, candidate):
                raise ValueError("Polish changed a deterministic fact marker")
        except Exception:
            self._state("natural_failed_using_faithful")
            return faithful
        self._state("natural_ready")
        return candidate
