"""Recheck saved model candidates after a verifier change without retranslating them."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from vlt.translation.ollama_backend import OllamaTranslationBackend


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=0,
                        help="Recheck only the first N rows, including pending rows")
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.input.read_text("utf-8").splitlines() if line.strip()]
    output = args.input.with_name(args.input.stem + "-postcheck.jsonl")
    prior = {json.loads(line)["id"] for line in output.read_text("utf-8").splitlines()
             if line.strip()} if output.exists() else set()
    backend = OllamaTranslationBackend(cpu_threads=4)
    with output.open("a", encoding="utf-8") as target:
        for index, row in enumerate(rows):
            if args.limit and index >= args.limit:
                break
            if row["status"] != "translated" or row["id"] in prior:
                continue
            try:
                backend._verify_facts(row["source"], row["translation"], [])
                review = backend._verify_alignment(row["source"], row["translation"])
                if review.status != "PASS":
                    raise RuntimeError("alignment: " + review.status + " " + ", ".join(review.issues))
                backend._verify_roundtrip(row["source"], row["translation"], row["language"])
                status, error = "pass", ""
            except RuntimeError as exc:
                status, error = "pending", str(exc)
            record = {"id": row["id"], "status": status, "error": error}
            target.write(json.dumps(record, ensure_ascii=False) + "\n")
            target.flush()
            print(row["id"], status, flush=True)


if __name__ == "__main__":
    main()
