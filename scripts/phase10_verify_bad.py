"""Probe the 22 retained Phase 9 failures against the live local verifier."""
from __future__ import annotations

import json
import time
from pathlib import Path

from vlt.translation.ollama_backend import OllamaTranslationBackend


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    cases = json.loads((root / "tests/fixtures/phase9_bad_22.json").read_text("utf-8"))
    output = root / "data/phase10/bad-review.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    prior = {row["sample_id"]: row for line in output.read_text("utf-8").splitlines()
             if (row := json.loads(line))} if output.exists() else {}
    backend = OllamaTranslationBackend(cpu_threads=4)
    with output.open("a", encoding="utf-8") as target:
        for case in cases:
            if case["sample_id"] in prior:
                continue
            start = time.monotonic()
            try:
                backend._verify_facts(case["source"], case["bad_translation"], [])
                review = backend._verify_alignment(case["source"], case["bad_translation"])
                result = review.status
                issues = review.issues
                if result == "PASS":
                    try:
                        backend._verify_roundtrip(case["source"], case["bad_translation"],
                                                  case["language"])
                    except RuntimeError:
                        result, issues = "PENDING", ("roundtrip_evidence",)
            except RuntimeError as exc:
                result, issues = "RETRY", ("deterministic_guard",)
            row = {"sample_id": case["sample_id"], "result": result,
                   "issues": issues, "elapsed_ms": round((time.monotonic() - start) * 1000)}
            target.write(json.dumps(row, ensure_ascii=False) + "\n")
            target.flush()
            print(row, flush=True)


if __name__ == "__main__":
    main()
