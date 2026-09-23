"""Opt-in real Ollama regression run. No mocks; saves only the authored fixture text."""
import argparse
import json
import time
from pathlib import Path

from vlt.translation.base import TranslationRequest
from vlt.translation.ollama_backend import OllamaTranslationBackend


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    corpus = json.loads(Path("tests/fixtures/translation_corpus.json").read_text("utf8"))
    backend = OllamaTranslationBackend(allow_fallback=False, cpu_threads=2)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf8") as output:
        for locale in ("zh-TW", "zh-CN"):
            for language in ("ja", "en"):
                for index, row in enumerate(corpus):
                    glossary = ()
                    if "term" in row:
                        glossary = ({"source": row["term"], "aliases": [row["alias"]],
                                     "preferred_zh_tw": row["preferred"],
                                     "preferred_zh_cn": row.get("preferred_cn", row["preferred"])},)
                    request = TranslationRequest(str(index), row[language], language, locale, "natural",
                                                 glossary=glossary, final=True)
                    started = time.perf_counter()
                    record = {"case": index, "source": language, "target": locale, "original": row[language]}
                    try:
                        record["text"] = backend.translate_final(request)
                        record["guard_passed"] = True
                    except RuntimeError as exc:
                        record.update(guard_passed=False, error=str(exc))
                    record["seconds"] = time.perf_counter() - started
                    output.write(json.dumps(record, ensure_ascii=False) + "\n"); output.flush()


if __name__ == "__main__":
    main()
