"""Freeze the Phase 10B comparison set from existing, local evidence.

The extra live rows are ASR output, not corrected reference translations.  A
blank reference must never be scored as a model error or a model success.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tests/fixtures/translation_bakeoff_650.json"


def build() -> list[dict]:
    fixed = json.loads((ROOT / "tests/fixtures/translation_reliability_400.json").read_text(encoding="utf-8"))
    rows = [dict(item) for item in fixed]
    reviewed = json.loads((ROOT / "data/phase9_review.json").read_text(encoding="utf-8"))
    assert len(rows) == 400 and len(reviewed) == 150
    for index, item in enumerate(reviewed):
        rows.append({
            "id": f"phase9-{index:03d}", "language": item["language"],
            "category": "real_asr_problem", "source": item["original"],
            "reference_zh_tw": "", "semantic_facts": "",
            "provenance": "phase9_real_asr_review",
            "source_quality": "unreviewed_asr",
        })
    connection = sqlite3.connect(ROOT / "data/phase10/live-soak/app.db")
    try:
        payloads = [json.loads(row[0]) for row in connection.execute(
            "SELECT payload_json FROM segments WHERE type='speech' ORDER BY start_ms, segment_id")]
    finally:
        connection.close()
    seen = {(row["language"], row["source"].strip()) for row in rows}
    selected = []
    for item in payloads:
        source = item.get("original", "").strip()
        language = item.get("language")
        if language != "ja" or not source or (language, source) in seen:
            continue
        seen.add((language, source))
        selected.append(item)
        if len(selected) == 100:
            break
    if len(selected) != 100:
        raise RuntimeError(f"Only {len(selected)} unique live Japanese rows; need 100")
    for index, item in enumerate(selected):
        rows.append({
            "id": f"phase10-live-{index:03d}", "language": "ja",
            "category": "real_live_asr", "source": item["original"],
            "reference_zh_tw": "", "semantic_facts": "",
            "provenance": "phase10_30min_chrome_soak",
            "source_quality": "unreviewed_asr",
            "asr_confidence": item.get("asr_confidence"),
            "start_ms": item.get("start_ms"), "end_ms": item.get("end_ms"),
        })
    assert len(rows) == 650
    assert sum(item["language"] == "ja" for item in rows) == 500
    assert sum(item["language"] == "en" for item in rows) == 150
    assert len({item["id"] for item in rows}) == len(rows)
    return rows


if __name__ == "__main__":
    corpus = build()
    OUTPUT.write_text(json.dumps(corpus, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(corpus)} rows to {OUTPUT}")
