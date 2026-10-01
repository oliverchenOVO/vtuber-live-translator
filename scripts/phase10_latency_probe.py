"""Measure local-model partial latency without persisting unverified partial text."""
from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

from vlt.translation.base import TranslationRequest
from vlt.translation.ollama_backend import OllamaTranslationBackend


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    rows = json.loads((root / "tests/fixtures/translation_reliability_400.json").read_text("utf-8"))
    cases = ([row for row in rows if row["language"] == "ja" and row["id"].endswith("-base")][:10]
             + [row for row in rows if row["language"] == "en" and row["id"].endswith("-base")][:5])
    backend = OllamaTranslationBackend()
    output = root / "data/phase10/partial-latency.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    timings = []
    with output.open("w", encoding="utf-8") as target:
        for row in cases:
            start = time.monotonic()
            try:
                backend.translate_partial(TranslationRequest(
                    row["id"], row["source"], row["language"], "zh-TW", "natural", final=False))
                status = "returned"
            except RuntimeError:
                status = "deferred_or_failed"
            elapsed = round((time.monotonic() - start) * 1000)
            timings.append(elapsed)
            target.write(json.dumps({"id": row["id"], "language": row["language"],
                                     "status": status, "elapsed_ms": elapsed}) + "\n")
            target.flush()
    print("partials", len(timings), "mean_ms", round(statistics.mean(timings)),
          "max_ms", max(timings), flush=True)


if __name__ == "__main__":
    main()
