"""Compare bounded preceding-context windows on the same recorded utterances.

This is an offline model experiment. It does not change the production default.
Results stay under ignored data/phase10 and never include audio.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from vlt.translation.base import TranslationRequest
from vlt.translation.ollama_backend import OllamaTranslationBackend


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    transcript = next((root / "data/phase8-final-soak/sessions").rglob("transcript.json"))
    rows = json.loads(transcript.read_text("utf-8"))["segments"]
    # Use recorded timestamps. These four contexts intentionally share exactly
    # the same current source, making leakage and added facts easy to inspect.
    cases = []
    for index, row in enumerate(rows):
        if (row.get("type") != "speech" or row["language"] != "ja"
                or index < 4 or len(row["original"]) < 8):
            continue
        nearby = [previous["original"] for previous in rows[:index]
                  if previous.get("type") == "speech" and previous["language"] == row["language"]
                  and 0 < row["start_ms"] - previous["start_ms"] <= 30000]
        if len(nearby) >= 3:
            cases.append((index, row, nearby))
        if len(cases) == 8:
            break
    output = root / "data/phase10/context-probe.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    done = {(item["index"], item["mode"]) for line in output.read_text("utf-8").splitlines()
            if (item := json.loads(line))} if output.exists() else set()
    modes = (("none", 0), ("previous_1", 1), ("previous_3", 3), ("previous_30s", 5))
    with output.open("a", encoding="utf-8") as target:
        for index, row, nearby in cases:
            for mode, limit in modes:
                if (index, mode) in done:
                    continue
                backend = OllamaTranslationBackend(context_segments=limit)
                started = time.monotonic()
                try:
                    translation = backend.translate_final(TranslationRequest(
                        f"context-{index}", row["original"], row["language"],
                        "zh-TW", "natural", tuple(nearby[-limit:]) if limit else (),
                        final=True))
                    status, error = "translated", ""
                except RuntimeError as exc:
                    translation, status, error = "", "pending", str(exc)
                result = {"index": index, "mode": mode, "source": row["original"],
                          "context": nearby[-limit:] if limit else [],
                          "translation": translation, "status": status, "error": error,
                          "elapsed_ms": round((time.monotonic() - started) * 1000)}
                target.write(json.dumps(result, ensure_ascii=False) + "\n")
                target.flush()
                print(index, mode, status, result["elapsed_ms"], flush=True)


if __name__ == "__main__":
    main()
