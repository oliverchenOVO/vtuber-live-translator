"""Small CPU-only local LLM. No network credentials, audio, or GPU contention."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
import unicodedata
from dataclasses import replace

from vlt.translation.base import TranslationRequest


class OllamaTranslationBackend:
    def __init__(self, model: str = "qwen2.5:1.5b", endpoint: str = "http://127.0.0.1:11434",
                 fallback_model: str = "qwen2.5:7b", allow_fallback: bool = False,
                 cpu_threads: int = 4):
        self.model = model
        self.fallback_model = fallback_model
        self.endpoint = endpoint.rstrip("/")
        self.allow_fallback = allow_fallback
        self.cpu_threads = max(1, int(cpu_threads))
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
                return " ".join(self._translate(replace(request, original=part),
                                                allow_fallback=self.allow_fallback) for part in chunks)
        return self._translate(request, allow_fallback=self.allow_fallback)

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
            "Keep Arabic numerals exactly as written. "
            "Preserve measurement units. Translate ordinary words fully. "
            "Do not complete unfinished speech or guess omitted actions. "
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
            "options": {"num_gpu": 0, "num_thread": self.cpu_threads, "num_predict": 128,
                        "temperature": 0, "repeat_penalty": 1.08},
        }).encode("utf-8")
        req = urllib.request.Request(self.endpoint + "/api/generate", payload,
                                     {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=25) as response:
                return json.load(response)["response"].strip()
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as exc:
            raise RuntimeError("本機翻譯服務（Ollama runtime）暫時不可用，請在 Settings 修復 Translation 元件。") from exc

    @staticmethod
    def _verify_facts(original: str, result: str, terms: list[str]) -> None:
        """Reject obvious factual drift; retain the original as a pending segment."""
        if re.search(r"\b(?:current utterance|earlier utterances|context only|translation into|output chinese translation)\b|^\s*translation\s*[:：]", result,
                     re.IGNORECASE | re.MULTILINE):
            raise RuntimeError("翻譯包含模型指令或標籤，已等待重試。")
        if re.search(r"[\u3040-\u30ff]", original) and result.strip() == original.strip():
            raise RuntimeError("翻譯仍是原文，已等待重試。")
        if len(original.strip()) <= 80 and len(result.strip()) > max(60, 3 * len(original.strip())):
            raise RuntimeError("翻譯比原文長太多，可能加入額外內容，已等待重試。")
        source = unicodedata.normalize("NFKC", original)
        target = unicodedata.normalize("NFKC", result)
        from decimal import Decimal
        numeric = r"\d+(?:\.\d+)?"
        values = {Decimal(raw) for raw in re.findall(numeric, target)}
        digits = dict(zip("零〇一二兩两三四五六七八九", [0, 0, 1, 2, 2, 2, 3, 4, 5, 6, 7, 8, 9]))
        units = {"十": 10, "百": 100, "千": 1000, "萬": 10000, "万": 10000, "億": 100000000, "亿": 100000000}
        def chinese_number(text: str) -> Decimal:
            integer, *fraction = re.split("[點点]", text)
            if not any(char in units for char in integer):
                number = int("".join(str(digits[c]) for c in integer))
            else:
                number = section = current = 0
                for char in integer:
                    if char in digits:
                        current = digits[char]
                    elif units[char] < 10000:
                        section += (current or 1) * units[char]
                        current = 0
                    else:
                        number += (section + current) * units[char]
                        section = current = 0
                number += section + current
            return Decimal(str(number) + ("." + "".join(str(digits[c]) for c in fraction[0]) if fraction else ""))
        for token in re.findall(r"[零〇一二兩两三四五六七八九十百千萬万億亿]+(?:[點点][零〇一二三四五六七八九]+)?", target):
            values.add(chinese_number(token))
        for raw in re.findall(numeric, source):
            if Decimal(raw) not in values:
                raise RuntimeError("翻譯未保留原文數字，已等待重試。")
        if re.search(r"\b(?:a|one) minute\b", original, re.I) and not re.search(r"(?:一|1)分(?:鐘|钟)", result):
            raise RuntimeError("翻譯未保留一分鐘的時間資訊，已等待重試。")
        if re.search(r"\b(?:a|one) hour\b", original, re.I) and not re.search(r"(?:一|1)小時|(?:一|1)小时", result):
            raise RuntimeError("翻譯未保留一小時的時間資訊，已等待重試。")
        if re.search(r"\d+時間しか寝てない", original) and re.search(r"不到|少於|少于", result):
            raise RuntimeError("原文表示只睡了指定時數，並非少於該時數。")
        # かもしれない marks uncertainty, not a negated event. A separate ない
        # (行かないかもしれない) remains and must still be preserved.
        negative_source = re.sub(r"かもしれ(?:ない|ません)", "", original)
        negative = bool(re.search(r"(?:ない|ません|なかった|ではなく|\bnot\b|\bnever\b|\bno\b|n't\b)", negative_source, re.I))
        if negative and not re.search(r"[不沒没无無未別别仅僅只]|沒有|不是|不能", result):
            raise RuntimeError("翻譯未保留否定語意，已等待重試。")
        uncertain = bool(re.search(r"(?:たぶん|多分|かもしれ|と思う|おそらく|\bmight\b|\bmaybe\b|\bperhaps\b|\bprobably\b|\bthink\b)", original, re.I))
        if uncertain and not re.search(r"可能|大概|也許|或許|我覺得|應該|估計|恐怕|我想|也许|或许|觉得|应该|估计", result):
            raise RuntimeError("翻譯未保留推測語氣，已等待重試。")
        if re.search(r"\d+\s*(?:ポイント|points?\b)", source, re.I) and re.search(r"\d+\s*分[鐘钟]", target):
            raise RuntimeError("翻譯把分數誤當成時間，已等待重試。")
        for term in terms:
            preferred = term.split(" => ")[-1]
            if preferred not in result:
                raise RuntimeError("翻譯未保留指定譯名，已等待重試。")
