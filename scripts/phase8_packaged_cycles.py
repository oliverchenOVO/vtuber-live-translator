"""Observe 20 packaged Start/Stop cycles and cleanup of an app-owned runtime."""
import argparse
import json
import os
import sqlite3
import subprocess
import time
import urllib.request
from pathlib import Path

import psutil


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("exe", type=Path)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    assert root.is_relative_to(Path("data").resolve())
    assert not (root / "app.db").exists(), "Prepare a fresh root with models and settings"
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1):
            raise AssertionError("An existing Ollama service would invalidate the ownership test")
    except OSError:
        pass
    process = subprocess.Popen([str(args.exe.resolve()), "--phase8-cycle-test"],
                               env={**os.environ, "VLT_DATA_DIR": str(root)})
    app = psutil.Process(process.pid)
    children = {}
    started = time.monotonic()
    try:
        while process.poll() is None:
            assert time.monotonic() - started < 600, "Packaged cycles timed out"
            try:
                for child in app.children(recursive=True):
                    children[(child.pid, child.create_time())] = child
            except psutil.NoSuchProcess:
                pass
            time.sleep(.5)
        assert process.returncode == 0
        _, alive = psutil.wait_procs(list(children.values()), timeout=5)
        events = [json.loads(line) for line in (root / "acceptance.jsonl").read_text("utf8").splitlines()]
        stopped = [row for row in events if row["event"] == "stopped"]
        ready = [row for row in events if row["event"] == "ready"]
        passed = events[-1]["event"] == "passed" and len(stopped) == len(ready) == 20
        assert passed and len({row["session_id"] for row in ready}) == 1
        assert all(not row["live"] and row["diarization_released"] for row in stopped)
        with sqlite3.connect(root / "app.db") as db:
            assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
            translated = db.execute("SELECT COUNT(*) FROM segments WHERE translation IS NOT NULL").fetchone()[0]
        result = {"cycles": 20, "exit_code": process.returncode,
                  "elapsed_s": time.monotonic() - started,
                  "same_session": True, "no_live_after_stop": True,
                  "translated_segments": translated,
                  "diarization_released_every_stop": True,
                  "first_stop_private_mb": stopped[0]["private_mb"],
                  "last_stop_private_mb": stopped[-1]["private_mb"],
                  "max_stop_private_mb": max(row["private_mb"] for row in stopped),
                  "first_stop_handles": stopped[0]["handles"],
                  "last_stop_handles": stopped[-1]["handles"],
                  "start_min_s": min(row["start_seconds"] for row in ready),
                  "start_max_s": max(row["start_seconds"] for row in ready),
                  "owned_descendant_pids": [pid for pid, _ in children],
                  "surviving_descendant_pids": [child.pid for child in alive]}
        (root / "result.json").write_text(json.dumps(result, indent=2), encoding="utf8")
        print(json.dumps(result), flush=True)
        assert len(children) >= 2 and translated > 0, "No working owned translation runner was observed"
        assert not alive, "App-owned runtime survived normal shutdown"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        # Clean only descendants observed under this exact test app process.
        for child in children.values():
            try:
                if child.is_running():
                    child.kill()
            except psutil.Error:
                pass


if __name__ == "__main__":
    main()
