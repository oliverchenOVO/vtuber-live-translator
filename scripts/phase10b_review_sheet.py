"""Join the frozen corpus and local model runs for blinded human spot checks."""
from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/phase10b"


def main() -> None:
    corpus = json.loads((ROOT / "tests/fixtures/translation_bakeoff_650.json").read_text("utf-8"))
    by_backend = {}
    for name in ("madlad", "gemma", "qwen"):
        path = DATA / f"{name}-corpus-zh-TW.jsonl"
        if not path.exists():
            path = ROOT / "evidence/phase10b" / path.name
        by_backend[name] = ({item["id"]: item for item in map(json.loads, path.read_text("utf-8").splitlines())}
                            if path.exists() else {})
    output = DATA / "review_650.tsv"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow(("id", "language", "category", "provenance", "source", "reference_zh_tw",
                         "source_audio_review", "madlad", "madlad_error", "gemma", "gemma_error",
                         "qwen", "qwen_error", "human_safe_translation_review"))
        for row in corpus:
            candidate = [by_backend[name].get(row["id"], {}) for name in ("madlad", "gemma", "qwen")]
            writer.writerow((row["id"], row["language"], row["category"], row["provenance"],
                             row["source"], row.get("reference_zh_tw", ""),
                             "UNREVIEWED", *(value for item in candidate for value in
                                             (item.get("translation", ""), item.get("error", ""))),
                             "UNREVIEWED"))
    # Long form permits an independent reviewer to record each requested
    # semantic category without conflating missing output with safe coverage.
    long_output = DATA / "review_650_long.tsv"
    with long_output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow(("id", "backend", "language", "category", "provenance",
                         "source", "reference_zh_tw", "translation", "error",
                         "eligible_source", "safe_usable", "hallucination",
                         "unsupported_expansion", "omission", "entity_error",
                         "number_error", "negation_error", "modality_error",
                         "untranslated_output", "review_notes"))
        for row in corpus:
            for name in ("madlad", "gemma", "qwen"):
                item = by_backend[name].get(row["id"], {})
                writer.writerow((row["id"], name, row["language"], row["category"],
                                 row["provenance"], row["source"], row.get("reference_zh_tw", ""),
                                 item.get("translation", ""), item.get("error", ""),
                                 *("UNREVIEWED",) * 11))
    print(output)
    print(long_output)


if __name__ == "__main__":
    main()
