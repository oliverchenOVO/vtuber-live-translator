"""Resumable local-model corpus probe; results stay in ignored data/."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from vlt.translation.base import TranslationRequest
from vlt.translation.ollama_backend import OllamaTranslationBackend


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", choices=("bad22", "gold400", "blind150"), required=True)
    parser.add_argument("--limit", type=int, default=0,
                        help="Stop after this many source rows; resume by omitting this option")
    parser.add_argument("--allow-7b-repair", action="store_true",
                        help="Use installed 7B only after a specific 1.5B verification failure")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = {"bad22": root / "tests/fixtures/phase9_bad_22.json",
              "gold400": root / "tests/fixtures/translation_reliability_400.json",
              "blind150": root / "data/phase9_review.json"}[args.set]
    rows = json.loads(source.read_text("utf-8"))
    suffix = "-repair7b" if args.allow_7b_repair else "-retranslated"
    output = root / "data/phase10" / (args.set + suffix + ".jsonl")
    output.parent.mkdir(parents=True, exist_ok=True)
    prior = {row["id"] for line in output.read_text("utf-8").splitlines()
             if (row := json.loads(line))} if output.exists() else set()
    backend = OllamaTranslationBackend(cpu_threads=4, allow_fallback=args.allow_7b_repair)
    with output.open("a", encoding="utf-8") as target:
        for index, row in enumerate(rows):
            if args.limit and index >= args.limit:
                break
            uid = row.get("sample_id") or row.get("id") or f"blind-{index:03}"
            if uid in prior:
                continue
            source_text = row.get("source") or row.get("original")
            start = time.monotonic()
            try:
                translated = backend.translate_final(TranslationRequest(
                    uid, source_text, row["language"], "zh-TW", "natural", final=True))
                status, error = "translated", ""
            except RuntimeError as exc:
                translated, status, error = "", "pending", str(exc)
            record = {"id": uid, "language": row["language"], "source": source_text,
                      "translation": translated, "status": status, "error": error,
                      "elapsed_ms": round((time.monotonic() - start) * 1000),
                      "verification_count": backend.verification_count,
                      "verification_ms": round(backend.verification_ms),
                      "repair_count": backend.repair_count}
            target.write(json.dumps(record, ensure_ascii=False) + "\n")
            target.flush()
            print(uid, status, record["elapsed_ms"], flush=True)


if __name__ == "__main__":
    main()
