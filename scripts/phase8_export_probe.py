"""Deterministic 8-hour fixture, export benchmark and real process-kill recovery probe."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil

from vlt.database.database import Database
from vlt.sessions.manager import SessionManager


def fixture(root: Path, count: int = 10020):
    db = Database(root / "app.db")
    manager = SessionManager(root, db)
    session = manager.create("胡桃のあ 雑談 🎮 : * ? \" < > | " + "長" * 200)
    sid = session["session_id"]
    speaker = manager.add_speaker(sid, 0)
    manager.update_speaker(sid, speaker, display_name="橘ひなの <Hinano>")
    values = []
    for i in range(count):
        start = int(i * 28800000 / count)
        item = {"id": f"fixture_{i:05d}", "type": "speech", "start_ms": start,
                "end_ms": start + 2000, "asr_state": "final", "language": "ja",
                "speaker_id": speaker, "original": f"今日は 🎮 {i}\n\nHello <team>",
                "translation": {"text": f"今天 {i}\n第二行"}, "translation_state": "final"}
        if i % 100 == 99:
            item.update(type="multi_speaker_event", event_type="unknown_overlap",
                        description={"zh_tw": "多人同時說話 🎮"}, speaker_ids=[speaker])
        values.append((sid, item["id"], start, item["end_ms"], item["type"], item["speaker_id"],
                       item["original"], item["translation"]["text"], json.dumps(item, ensure_ascii=False)))
    with db.connection:
        db.connection.executemany("INSERT INTO segments VALUES(?,?,?,?,?,?,?,?,?)", values)
    manager.reconcile_transcript(sid)
    return db, manager, session


def crash_worker(root: Path, stage: str):
    import vlt.sessions.manager as module
    db = Database(root / "app.db")
    manager = SessionManager(root, db)
    sid = manager.list_sessions()[0]["session_id"]
    manager.mark_interrupted()
    manager.resume(sid)
    if stage.startswith("run-"):
        number = int(stage.split("-")[1])
        item = {"id": f"crash_{number}", "type": "speech", "start_ms": number * 1000,
                "end_ms": number * 1000 + 900, "original": "日本語 crash recovery",
                "language": "ja", "speaker_id": "unknown", "asr_state": "final"}
        manager.append_final(sid, item)
        if number >= 1:
            manager.update_final_translation(sid, item["id"], {"target": "zh-TW", "style": "natural", "text": "恢復驗證"})
        if number >= 2:
            manager.assign_segment_speaker(sid, item["id"], manager.list_speakers(sid)[0]["speaker_id"])
        if number >= 3:
            manager.render_exports(sid, "both")
        if number >= 4:
            manager.set_source_language(sid, "auto")
        (root / "ready").write_text(str(os.getpid()))
        while True:
            time.sleep(.1)
    original = module._atomic_text
    def interrupted_write(path, content):
        if path.suffix == stage:
            temporary = path.with_suffix(path.suffix + ".tmp")
            with temporary.open("w", encoding="utf8") as output:
                output.write(content[:len(content) // 2]); output.flush(); os.fsync(output.fileno())
            (root / "ready").write_text(str(os.getpid()))
            while True:
                time.sleep(.1)
        original(path, content)
    module._atomic_text = interrupted_write
    manager.finish(sid, "both")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--crash-stage", default="")
    args = parser.parse_args()
    if args.crash_stage:
        crash_worker(args.root, args.crash_stage)
        return
    process = psutil.Process()
    db, manager, session = fixture(args.root)
    before = process.memory_info()
    started = time.perf_counter()
    paths = manager.render_exports(session["session_id"], "both")
    elapsed = time.perf_counter() - started
    after = process.memory_info()
    result = {"segments": 10020, "duration_hours": 8, "export_seconds": elapsed,
              "rss_before_mb": before.rss / 1024**2, "rss_after_mb": after.rss / 1024**2,
              "peak_rss_mb": after.peak_wset / 1024**2,
              "private_mb": after.private / 1024**2,
              "sizes": {k: Path(v).stat().st_size for k, v in paths.items()}}
    print(json.dumps(result), flush=True)
    (args.root / "benchmark.json").write_text(json.dumps(result, indent=2))
    db.close()


if __name__ == "__main__":
    main()
