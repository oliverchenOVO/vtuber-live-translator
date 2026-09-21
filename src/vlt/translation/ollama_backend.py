"""Small CPU-only local LLM. No network credentials, audio, or GPU contention."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import replace

from vlt.translation.base import TranslationRequest


class OllamaTranslationBackend:
    def __init__(self, model: str = "qwen2.5:1.5b", endpoint: str = "http://127.0.0.1:11434",
                 fallback_model: str = "qwen2.5:7b"):
        self.model = model
        self.fallback_model = fallback_model
        self.endpoint = endpoint.rstrip("/")
        self.target_language = "zh-TW"
        self.style = "natural"
        self.context: tuple[str, ...] = ()
        self.glossary: tuple[dict, ...] = ()

    def set_target_language(self, language: str) -> None:
        if language not in ("zh-TW", "zh-CN"):
            raise ValueError(language)
        self.target_language = language

    def set_style(self, style: str) -> None:
        if style not in ("natural", "faithful", "minimal"):
            raise ValueError(style)
        self.style = style

    def update_context(self, context: tuple[str, ...]) -> None:
        self.context = context[-5:]

    def update_glossary(self, glossary: tuple[dict, ...]) -> None:
        self.glossary = glossary

    def translate_partial(self, request: TranslationRequest) -> str:
        return self._translate(request, allow_fallback=False)

    def translate_final(self, request: TranslationRequest) -> str:
        if len(request.original) > 130:
            chunks = [part.strip() for part in re.split(r"(?<=[.!?])\s+|(?<=[。！？])", request.original)
                      if part.strip()]
            if len(chunks) > 1:
                return " ".join(self._translate(replace(request, original=part)) for part in chunks)
        return self._translate(request)

    def _translate(self, request: TranslationRequest, *, allow_fallback: bool = True) -> str:
        self.set_target_language(request.target_language)
        self.set_style(request.style)
        self.update_context(request.context)
        self.update_glossary(request.glossary)
        locale = "Traditional Chinese as used in Taiwan" if request.target_language == "zh-TW" else "Simplified Chinese as used in mainland China"
        styles = {
            "natural": "Natural spoken Chinese, with natural word order and punctuation.",
            "faithful": "Stay close to the source wording and sentence structure.",
            "minimal": "Concise subtitle. Remove filler only; retain all factual content.",
        }
        terms = []
        for entry in self.glossary:
            preferred = entry["preferred_zh_tw" if request.target_language == "zh-TW" else "preferred_zh_cn"]
            if preferred and any(term and term.casefold() in request.original.casefold()
                                 for term in (entry["source"], *entry.get("aliases", []))):
                terms.append(f'{entry["source"]} (aliases: {", ".join(entry.get("aliases", []))}) => {preferred}')
        prompt = (
            f"Translate ONLY the CURRENT utterance from {request.source_language} into {locale}. "
            f"{styles[request.style]} Preserve names, numbers, times, negation, uncertainty, causality, and viewpoint. "
            "Context only disambiguates; never add facts from context. Output Chinese translation ONLY, no labels.\n"
            + ("Glossary (mandatory spellings):\n" + "\n".join(terms) + "\n" if terms else "")
            + ("Earlier utterances (context only):\n" + "\n".join(self.context) + "\n" if self.context else "")
            + "CURRENT utterance:\n" + request.original + "\nTranslation:"
        )
        for attempt in range(2 if allow_fallback else 1):
            result = self._generate(prompt, self.model if attempt == 0 else self.fallback_model)
            result = re.sub(r"^(?:Translation|翻譯|译文)\s*[:：]\s*", "", result).strip(' \n"')
            if not result:
                raise RuntimeError("翻譯模型沒有回傳文字。")
            # A final locale normalization is defensive; the model receives the actual locale.
            try:
                from opencc import OpenCC
                result = OpenCC("s2twp" if request.target_language == "zh-TW" else "t2s").convert(result)
            except ImportError:
                pass
            # Exact glossary spellings win over any script conversion.
            for entry in self.glossary:
                preferred = entry["preferred_zh_tw" if request.target_language == "zh-TW" else "preferred_zh_cn"]
                if preferred:
                    for spelling in (entry["preferred_zh_tw"], entry["preferred_zh_cn"], entry["source"], *entry.get("aliases", [])):
                        if spelling:
                            result = re.sub(re.escape(spelling), preferred, result, flags=re.IGNORECASE)
            try:
                self._verify_facts(request.original, result, terms)
                for entry in self.glossary:
                    preferred = entry["preferred_zh_tw" if request.target_language == "zh-TW" else "preferred_zh_cn"]
                    if preferred and any(re.search(re.escape(alias) + r"とゲーム", request.original, re.I)
                                         for alias in (entry["source"], *entry.get("aliases", [])) if alias):
                        if not re.search(r"(?:和|跟|與|同)" + re.escape(preferred) + r".{0,5}(?:玩|打)|" +
                                         re.escape(preferred) + r".{0,5}(?:一起玩|一起打)", result):
                            raise RuntimeError("翻譯未保留共同遊戲的關係，已等待重試。")
                return result
            except RuntimeError as exc:
                if attempt or not allow_fallback:
                    raise
                prompt = prompt.replace("Output Chinese translation ONLY, no labels.",
                                        "Output Chinese translation ONLY, no labels. "
                                        "A minute means approximately one minute (一分鐘), not several minutes. "
                                        "Without taking it out means it stayed in water. "
                                        f"Your answer must correct this detected issue: {exc}")
        raise RuntimeError("翻譯尚未通過事實檢查。")

    def _generate(self, prompt: str, model: str) -> str:
        payload = json.dumps({
            "model": model, "prompt": prompt, "stream": False, "keep_alive": "10m",
            "options": {"num_gpu": 0, "num_thread": 4, "num_predict": 128,
                        "temperature": 0, "repeat_penalty": 1.08},
        }).encode("utf-8")
        req = urllib.request.Request(self.endpoint + "/api/generate", payload,
                                     {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=25) as response:
                return json.load(response)["response"].strip()
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as exc:
            raise RuntimeError("本機 Ollama 翻譯服務暫時不可用，請啟動服務並安裝 qwen2.5:1.5b 與 qwen2.5:7b。") from exc

    @staticmethod
    def _verify_facts(original: str, result: str, terms: list[str]) -> None:
        """Reject obvious factual drift; retain the original as a pending segment."""
        numerals = "零一二三四五六七八九"
        for raw in re.findall(r"\d+", original):
            chinese = "".join(numerals[int(ch)] for ch in raw)
            if raw not in result and chinese not in result and not (raw == "10" and "十" in result):
                raise RuntimeError("翻譯未保留原文數字，已等待重試。")
        if re.search(r"\b(?:a|one) minute\b", original, re.I) and not re.search(r"(?:一|1)分(?:鐘|钟)", result):
            raise RuntimeError("翻譯未保留一分鐘的時間資訊，已等待重試。")
        if re.search(r"\b(?:a|one) hour\b", original, re.I) and not re.search(r"(?:一|1)小時|(?:一|1)小时", result):
            raise RuntimeError("翻譯未保留一小時的時間資訊，已等待重試。")
        if re.search(r"\d+時間しか寝てない", original) and re.search(r"不到|少於|少于", result):
            raise RuntimeError("原文表示只睡了指定時數，並非少於該時數。")
        negative = bool(re.search(r"(?:ない|ません|なかった|ではなく|\bnot\b|\bnever\b|\bno\b|n't\b)", original, re.I))
        if negative and not re.search(r"[不沒无無未別仅僅只]|沒有|不是|不能", result):
            raise RuntimeError("翻譯未保留否定語意，已等待重試。")
        uncertain = bool(re.search(r"(?:たぶん|多分|かもしれ|と思う|おそらく|\bmight\b|\bmaybe\b|\bperhaps\b|\bprobably\b|\bthink\b)", original, re.I))
        if uncertain and not re.search(r"可能|大概|也許|或許|我覺得|應該|估計|恐怕|我想|也许|觉得|应该", result):
            raise RuntimeError("翻譯未保留推測語氣，已等待重試。")
        for term in terms:
            preferred = term.split(" => ")[-1]
            if preferred not in result:
                raise RuntimeError("翻譯未保留指定譯名，已等待重試。")
