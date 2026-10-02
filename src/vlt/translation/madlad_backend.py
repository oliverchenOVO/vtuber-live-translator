"""Dedicated local MT candidate.  No Ollama, API key, or UI dependency."""
from __future__ import annotations

import re
from pathlib import Path

from vlt.translation.base import TranslationRequest


class MadladTranslationBackend:
    """CTranslate2 int8 MADLAD-400 with explicit source and locale handling.

    The model is loaded lazily so importing the app never allocates ~3 GiB.
    Glossary placeholders are validated after decoding; a model that drops or
    changes one cannot silently publish an incorrectly named person.
    """

    def __init__(self, model_dir: Path, *, device: str = "cpu", cpu_threads: int = 4):
        self.model_dir = Path(model_dir)
        self.device = device
        self.cpu_threads = cpu_threads
        self.target_language = "zh-TW"
        self.style = "faithful"
        self.context: tuple[str, ...] = ()
        self.glossary: tuple[dict, ...] = ()
        self._translator = None
        self._tokenizer = None

    def set_target_language(self, language: str) -> None:
        if language not in ("zh-TW", "zh-CN"):
            raise ValueError(language)
        self.target_language = language

    def set_style(self, style: str) -> None:
        if style not in ("faithful", "natural", "minimal"):
            raise ValueError(style)
        self.style = style

    def update_context(self, context: tuple[str, ...]) -> None:
        self.context = context[-5:]

    def update_glossary(self, glossary: tuple[dict, ...]) -> None:
        self.glossary = glossary

    def _load(self) -> None:
        if self._translator is not None:
            return
        import ctranslate2
        import sentencepiece
        self._tokenizer = sentencepiece.SentencePieceProcessor(
            model_file=str(self.model_dir / "spiece.model"))
        self._translator = ctranslate2.Translator(
            str(self.model_dir), device=self.device,
            compute_type="int8" if self.device == "cpu" else "auto",
            inter_threads=1, intra_threads=self.cpu_threads)

    @staticmethod
    def _protect(source: str, glossary: tuple[dict, ...], target: str) -> tuple[str, dict[str, str]]:
        spans: list[tuple[int, int, str]] = []
        for entry in glossary:
            preferred = entry.get("preferred_zh_tw" if target == "zh-TW" else "preferred_zh_cn", "")
            if not preferred:
                continue
            for term in (entry.get("source", ""), *entry.get("aliases", [])):
                if term:
                    boundary = (r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])"
                                if term.isascii() else re.escape(term))
                    spans.extend((m.start(), m.end(), preferred)
                                 for m in re.finditer(boundary, source, re.I))
        # Longest aliases take precedence; overlapping shorter matches lose.
        accepted: list[tuple[int, int, str]] = []
        for span in sorted(spans, key=lambda s: (-(s[1] - s[0]), s[0])):
            if not any(span[0] < end and span[1] > start for start, end, _ in accepted):
                accepted.append(span)
        replacements: dict[str, str] = {}
        for index, (start, end, preferred) in enumerate(sorted(accepted, reverse=True), 1):
            marker = f"VLTTERM{index:03d}"
            source = source[:start] + marker + source[end:]
            replacements[marker] = preferred
        return source, replacements

    @staticmethod
    def _finish(text: str, replacements: dict[str, str], target: str) -> str:
        from opencc import OpenCC
        text = OpenCC("s2twp" if target == "zh-TW" else "t2s").convert(text)
        for marker, preferred in replacements.items():
            # The model may insert ASCII spaces around a protected token.
            pattern = r"\s*".join(map(re.escape, marker))
            matches = list(re.finditer(pattern, text, flags=re.I))
            if len(matches) != 1:
                raise RuntimeError("專有名詞標記未完整保留，翻譯未發布。")
            text = re.sub(pattern, lambda _: preferred, text, count=1, flags=re.I)
        if re.search(r"VLT\s*T\s*E\s*R\s*M", text, re.I):
            raise RuntimeError("專有名詞標記外洩，翻譯未發布。")
        return text.strip()

    def _translate(self, request: TranslationRequest) -> str:
        if request.source_language not in ("ja", "en"):
            raise RuntimeError("目前只支援日文或英文原文。")
        self.set_target_language(request.target_language)
        self._load()
        source, replacements = self._protect(request.original, request.glossary, request.target_language)
        tokens = self._tokenizer.encode("<2zh> " + source, out_type=str)
        result = self._translator.translate_batch([tokens], beam_size=2, max_decoding_length=128)[0]
        text = self._tokenizer.decode(result.hypotheses[0])
        if not text:
            raise RuntimeError("翻譯模型沒有回傳文字。")
        return self._finish(text, replacements, request.target_language)

    def translate_partial(self, request: TranslationRequest) -> str:
        return self._translate(request)

    def translate_final(self, request: TranslationRequest) -> str:
        return self._translate(request)
