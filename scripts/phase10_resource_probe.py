"""Sample only this Phase 10 owned Ollama tree; save resource numbers, no content."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import psutil


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=int, default=120)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    pid = int((root / "data/phase10/ollama.pid").read_text("utf-8").strip())
    server = psutil.Process(pid)
    output = root / "data/phase10/model-resources.jsonl"
    started = time.monotonic()
    with output.open("a", encoding="utf-8") as target:
        while time.monotonic() - started < args.minutes * 60 and server.is_running():
            try:
                processes = [server, *server.children(recursive=True)]
                for process in processes:
                    process.cpu_percent(None)
                time.sleep(10)
                alive = [process for process in processes if process.is_running()]
                row = {"elapsed_s": round(time.monotonic() - started, 1),
                       "rss_mb": round(sum(p.memory_info().rss for p in alive) / 1024**2, 1),
                       "cpu_one_core_percent": round(sum(p.cpu_percent(None) for p in alive), 1),
                       "processes": len(alive)}
                target.write(json.dumps(row) + "\n")
                target.flush()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break


if __name__ == "__main__":
    main()
