"""Read-only long-run resource sampler; no audio or transcript text is stored."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil


def gpu_memory_mb() -> int | None:
    try:
        output = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            text=True, timeout=4).strip().splitlines()[0]
        return int(output)
    except Exception:
        return None


def main() -> None:
    root = Path(__file__).resolve().parents[1] / "data"
    output = Path(os.environ.get("VLT_PHASE5_MONITOR_DIR", str(root / "phase5-live"))) / "resources.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    processes = [process for process in psutil.process_iter(["pid", "cmdline"])
                 if "--phase5-live-test" in (process.info.get("cmdline") or [])]
    if not processes:
        raise RuntimeError("Phase 5 live app is not running")
    process = max(processes, key=lambda candidate: candidate.memory_info().rss)
    process.cpu_percent(None)
    started = time.monotonic()
    while process.is_running() and time.monotonic() - started < 3600:
        time.sleep(30)
        if not process.is_running():
            break
        with sqlite3.connect(root / "app.db") as db:
            session = db.execute("SELECT session_id FROM sessions ORDER BY created_at DESC LIMIT 1").fetchone()
            sid = session[0] if session else ""
            counts = db.execute("SELECT speaker_id,COUNT(*) FROM segments WHERE session_id=? "
                                "AND type='speech' GROUP BY speaker_id", (sid,)).fetchall()
            event_count = db.execute("SELECT COUNT(*) FROM segments WHERE session_id=? "
                                     "AND type='multi_speaker_event'", (sid,)).fetchone()[0]
        sample = {"at": datetime.now(timezone.utc).isoformat(),
                  "elapsed_s": round(time.monotonic() - started, 1),
                  "pid": process.pid,
                  "cpu_percent_one_core": process.cpu_percent(None),
                  "rss_mb": round(process.memory_info().rss / 1024 / 1024, 1),
                  "gpu_memory_total_mb": gpu_memory_mb(),
                  "speaker_segment_counts": dict(counts),
                  "overlap_events": event_count}
        with output.open("a", encoding="utf-8") as target:
            target.write(json.dumps(sample) + "\n")
        print(json.dumps(sample), flush=True)


if __name__ == "__main__":
    main()
