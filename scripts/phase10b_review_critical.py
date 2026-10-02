"""Codex text-only review of the 22 old Critical sources and model outputs.

This review does not compare the ASR source with audio and is not independent
human acceptance.  Suspected ASR errors remain unconfirmed.
"""
from __future__ import annotations

import json
import hashlib
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "data/phase10b"
SUSPECTED_ASR = {"phase9-002", "phase9-020", "phase9-033", "phase9-057",
                 "phase9-064", "phase9-070", "phase9-072", "phase9-095"}

# Labels are conservative text-only judgements relative to the ASR source.
# HALLUCINATED means an unsupported proposition is visibly added.
LABELS = {
    "madlad": [
        "WRONG", "WRONG", "HALLUCINATED", "ACCEPTABLE", "HALLUCINATED",
        "ACCEPTABLE", "HALLUCINATED", "WRONG", "WRONG", "WRONG",
        "HALLUCINATED", "WRONG", "WRONG", "HALLUCINATED", "WRONG",
        "HALLUCINATED", "ACCEPTABLE", "HALLUCINATED", "HALLUCINATED",
        "ACCEPTABLE", "HALLUCINATED", "ACCEPTABLE",
    ],
    "gemma": [
        "HALLUCINATED", "ACCEPTABLE", "HALLUCINATED", "HALLUCINATED",
        "CORRECT", "ACCEPTABLE", "HALLUCINATED", "CORRECT", "ACCEPTABLE",
        "WRONG", "HALLUCINATED", "ACCEPTABLE", "WRONG", "HALLUCINATED",
        "ACCEPTABLE", "WRONG", "WRONG", "HALLUCINATED", "CORRECT",
        "ACCEPTABLE", "ACCEPTABLE", "CORRECT",
    ],
    "qwen": [
        "NO_OUTPUT", "NO_OUTPUT", "NO_OUTPUT", "NO_OUTPUT", "NO_OUTPUT",
        "ACCEPTABLE", "NO_OUTPUT", "NO_OUTPUT", "NO_OUTPUT", "NO_OUTPUT",
        "NO_OUTPUT", "NO_OUTPUT", "NO_OUTPUT", "NO_OUTPUT", "NO_OUTPUT",
        "NO_OUTPUT", "NO_OUTPUT", "NO_OUTPUT", "NO_OUTPUT", "NO_OUTPUT",
        "NO_OUTPUT", "ACCEPTABLE",
    ],
}


def main() -> None:
    sources = json.loads((ROOT / "tests/fixtures/phase9_bad_22.json").read_text("utf-8"))
    assert len(sources) == 22
    canonical = json.dumps(sources, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(canonical).hexdigest() == "8d8a3d46a0ef7dd56f073b55035009048d1414566e068d6e381b5635abe9129d"
    output = []
    for backend, labels in LABELS.items():
        assert len(labels) == len(sources)
        records = {row["id"]: row for row in map(json.loads, (
            EVIDENCE / f"{backend}-critical-zh-TW.jsonl").read_text("utf-8").splitlines())}
        assert len(records) == 22
        for source, label in zip(sources, labels):
            uid = source["sample_id"]
            record = records[uid]
            assert bool(record["translation"]) == (label != "NO_OUTPUT"), uid
            output.append({
                "id": uid, "backend": backend, "source": source["source"],
                "translation": record["translation"], "judgment": label,
                "source_audio_status": ("suspected_asr_error_audio_unavailable" if uid in SUSPECTED_ASR
                                        else "unverified_text_only"),
            })
    result = {
        "reviewer": "Codex text-only; not independent human review",
        "source_audio_available": False,
        "confirmed_asr_source_errors": 0,
        "rows": output,
        "counts": {name: dict(Counter(row["judgment"] for row in output if row["backend"] == name))
                   for name in LABELS},
    }
    (EVIDENCE / "critical-review.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
