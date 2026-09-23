"""Sample an explicitly selected packaged process; never save speech or audio."""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--minutes", type=int, default=180)
    args = parser.parse_args()
    process = psutil.Process(int((args.root / "app.pid").read_text().strip()))
    started = time.monotonic()
    process.cpu_percent()
    ollama = {}
    output = args.root / "resources.jsonl"
    while process.is_running() and time.monotonic() - started <= args.minutes * 60:
        try:
            mem = process.memory_info()
            sample = {"at": datetime.now(timezone.utc).isoformat(),
                      "elapsed_s": round(time.monotonic() - started, 1), "pid": process.pid,
                      "rss_mb": mem.rss / 1024**2, "private_mb": mem.private / 1024**2,
                      "cpu_one_core_percent": process.cpu_percent(), "threads": process.num_threads(),
                      "handles": process.num_handles()}
            alive = {p.pid: p for p in psutil.process_iter(["name"])
                     if "ollama" in (p.info["name"] or "").lower()}
            ollama = {pid: ollama.get(pid, p) for pid, p in alive.items()}
            sample["ollama_rss_mb"] = sum(p.memory_info().rss for p in ollama.values()) / 1024**2
            sample["ollama_cpu_one_core_percent"] = sum(p.cpu_percent() for p in ollama.values())
            sample["cache_mb"] = sum(p.stat().st_size for p in (args.root / "cache").rglob("*") if p.is_file()) / 1024**2
            try:
                raw = subprocess.check_output(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                              text=True, timeout=4, creationflags=subprocess.CREATE_NO_WINDOW)
                sample["gpu_total_mb"] = sum(int(x) for x in raw.splitlines())
            except Exception:
                sample["gpu_total_mb"] = None
            try:
                with sqlite3.connect(f"file:{(args.root / 'app.db').as_posix()}?mode=ro", uri=True) as db:
                    sample["segments"] = db.execute("SELECT COUNT(*) FROM segments").fetchone()[0]
                    sample["speakers"] = db.execute("SELECT COUNT(*) FROM speakers").fetchone()[0]
                    sample["translated"] = db.execute("SELECT COUNT(*) FROM segments WHERE translation IS NOT NULL").fetchone()[0]
            except sqlite3.OperationalError:
                sample["database_starting"] = True
            log_path = args.root / "logs" / "app.log"
            if log_path.exists():
                with log_path.open("rb") as log:
                    log.seek(max(0, log.seek(0, 2) - 32768))
                    matches = re.findall(r"Pipeline metrics: (.+)", log.read().decode("utf8", errors="ignore"))
                    if matches:
                        sample["pipeline"] = dict(re.findall(r"(\w+)=([^ ]+)", matches[-1]))
            with output.open("a", encoding="utf8") as target:
                target.write(json.dumps(sample) + "\n")
            print(json.dumps(sample), flush=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            break
        time.sleep(60)


if __name__ == "__main__":
    main()
