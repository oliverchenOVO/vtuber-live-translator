"""Real local model comparison, keeping only translated text and latency."""
import json
import sys
import time

from vlt.translation.base import TranslationRequest
from vlt.translation.ollama_backend import OllamaTranslationBackend


sys.stdout.reconfigure(encoding="utf-8")
backend = OllamaTranslationBackend()
glossary = ({"source": "ぺこら", "preferred_zh_tw": "佩克拉", "preferred_zh_cn": "佩克拉",
             "aliases": ["Pekora"]},)
for locale in ("zh-TW", "zh-CN"):
    for style in ("natural", "faithful", "minimal"):
        request = TranslationRequest("style-probe", "昨日3時間しか寝てない。たぶん今日はぺこらとゲームすると思う。",
                                     "ja", locale, style, glossary=glossary, final=True)
        start = time.monotonic()
        try:
            translated = backend.translate_final(request)
            print(json.dumps({"locale": locale, "style": style, "text": translated,
                              "latency_s": round(time.monotonic()-start, 2)}, ensure_ascii=False))
        except RuntimeError as error:
            print(json.dumps({"locale": locale, "style": style, "error": str(error)}, ensure_ascii=False))
