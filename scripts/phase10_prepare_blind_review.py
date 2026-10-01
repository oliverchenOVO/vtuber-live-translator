"""Prepare a blinded, randomized 100 JA / 50 EN review sheet from real output."""
from __future__ import annotations

import csv
import json
import random
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1] / "data/phase10"
    records = [json.loads(line) for line in (root / "blind150-retranslated.jsonl").read_text("utf-8").splitlines()]
    if len(records) != 150 or sum(row["language"] == "ja" for row in records) != 100:
        raise ValueError("Blind set must contain exactly 100 Japanese and 50 English rows")
    rng = random.Random(10010)
    rng.shuffle(records)
    with (root / "blind-review.tsv").open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.writer(target, delimiter="\t")
        writer.writerow(("row", "language", "source", "translation", "review_label"))
        for index, record in enumerate(records, 1):
            writer.writerow((index, record["language"], record["source"],
                             record["translation"], ""))
    # Keep the ID mapping out of the reviewer sheet and away from model flags.
    (root / "blind-review-map.json").write_text(
        json.dumps({str(index): row["id"] for index, row in enumerate(records, 1)}, indent=2),
        encoding="utf-8")


if __name__ == "__main__":
    main()
