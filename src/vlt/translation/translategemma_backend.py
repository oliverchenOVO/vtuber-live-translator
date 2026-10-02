"""Local TranslateGemma comparison candidate; not the GA default."""
from __future__ import annotations

import json
import urllib.request

from vlt.translation.base import TranslationRequest
from vlt.translation.madlad_backend import MadladTranslationBackend


class TranslateGemmaBackend:
    def __init__(self, endpoint: str = "http://127.0.0.1:11434", *, cpu_threads: int = 4):
        self.endpoint = endpoint.rstrip("/")
        self.cpu_threads = cpu_threads
        self.target_language = "zh-TW"
        self.style = "faithful"
        self.context: tuple[str, ...] = ()
        self.glossary: tuple[dict, ...] = ()

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

    def _translate(self, request: TranslationRequest) -> str:
        if request.source_language not in ("ja", "en"):
            raise RuntimeError("目前只支援日文或英文原文。")
        self.set_target_language(request.target_language)
        source_text, placeholders = MadladTranslationBackend._protect(
            request.original, request.glossary, request.target_language)
        source = "Japanese (ja)" if request.source_language == "ja" else "English (en)"
        target = "Chinese (zh)"
        # Ollama's published TranslateGemma prompt format is used verbatim.
        prompt = (f"You are a professional {source} to {target} translator. Your goal is to accurately "
                  f"convey the meaning and nuances of the original {source} text while adhering to {target} "
                  f"grammar, vocabulary, and cultural sensitivities.\n"
                  f"Produce only the {target} translation, without any additional explanations or commentary. "
                  f"Please translate the following {source} text into {target}:" + "\n\n" + source_text)
        payload = json.dumps({"model": "translategemma:4b", "prompt": prompt,
                              "stream": False, "keep_alive": "10m",
                              "options": {"num_gpu": 0, "num_thread": self.cpu_threads,
                                          "num_predict": 128, "temperature": 0}}).encode()
        with urllib.request.urlopen(urllib.request.Request(
                self.endpoint + "/api/generate", payload,
                {"Content-Type": "application/json"}), timeout=120) as response:
            output = json.load(response)["response"].strip()
        if not output:
            raise RuntimeError("翻譯模型沒有回傳文字。")
        return MadladTranslationBackend._finish(output, placeholders, request.target_language)

    def translate_partial(self, request: TranslationRequest) -> str:
        if len(request.original.strip()) < 4:
            raise RuntimeError("片段太短，等待更多語音。")
        return self._translate(request)

    def translate_final(self, request: TranslationRequest) -> str:
        return self._translate(request)
