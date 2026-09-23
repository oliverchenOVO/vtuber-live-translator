"""Five real taskkill /F runs of the packaged audio/ASR/translation Session."""
import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

from vlt.database.database import Database
from vlt.sessions.manager import SessionManager
from vlt.settings.manager import SettingsManager


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("exe", type=Path)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root, exe = args.root.resolve(), args.exe.resolve()
    assert root.is_relative_to(Path("data").resolve()), "Use a project data subdirectory"
    assert not (root / "app.db").exists(), "Use a fresh test root"
    root.mkdir(parents=True, exist_ok=True)
    source = Path("data/first-run-managed/models")
    for component in ("models--Systran--faster-whisper-base", "diarization"):
        shutil.copytree(source / component, root / "models" / component, dirs_exist_ok=True)
    settings = SettingsManager(root)
    for key, value in {"first_run_complete": True, "performance_preset": "gaming",
                       "source_language": "ja", "show_overlay_on_start": True}.items():
        settings.set(key, value)
    db = Database(root / "app.db")
    manager = SessionManager(root, db)
    session = manager.create("Packaged crash recovery — QA")
    sid, folder = session["session_id"], session["folder_path"]
    speaker = manager.add_speaker(sid, 0)
    manager.update_speaker(sid, speaker, display_name="人工名稱 QA 🎮")
    manager.append_final(sid, {"id": "manual-fixture", "type": "speech", "asr_state": "final",
                              "start_ms": 0, "end_ms": 1000, "language": "ja", "original": "復原驗證固定資料",
                              "speaker_id": speaker, "speaker_assignment": "manual"})
    db.close()
    env = {**os.environ, "VLT_DATA_DIR": str(root)}
    results, prior_ids = [], {"manual-fixture"}
    for index, delay in enumerate((10, 15, 20, 25, 30)):
        marker = root / "acceptance.jsonl"
        offset = marker.stat().st_size if marker.exists() else 0
        process = subprocess.Popen([str(exe), "--phase8-recovery-test"], env=env)
        try:
            deadline = time.monotonic() + 90
            ready = None
            while time.monotonic() < deadline and process.poll() is None:
                if marker.exists():
                    with marker.open("rb") as stream:
                        stream.seek(offset)
                        for line in stream:
                            try:
                                value = json.loads(line)
                            except ValueError:
                                continue
                            if value["event"] == "ready":
                                ready = value
                    if ready:
                        break
                time.sleep(.2)
            assert ready and ready["session_id"] == sid, "Packaged Session failed to resume"
            time.sleep(delay)
            subprocess.run(["taskkill", "/F", "/PID", str(process.pid)], check=True,
                           stdout=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
            process.wait(timeout=10)
        finally:
            if process.poll() is None:
                process.kill(); process.wait(timeout=10)
        with sqlite3.connect(root / "app.db") as connection:
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert connection.execute("SELECT session_id,folder_path FROM sessions").fetchall() == [(sid, folder)]
            ids = {row[0] for row in connection.execute("SELECT segment_id FROM segments")}
            assert prior_ids <= ids
            assert connection.execute("SELECT display_name FROM speakers WHERE speaker_id=?", (speaker,)).fetchone()[0] == "人工名稱 QA 🎮"
        for filename in ("session.json", "transcript.json"):
            json.loads((Path(folder) / filename).read_text("utf8"))
        results.append({"kill": index + 1, "pid": process.pid, "seconds_after_ready": delay,
                        "same_session": True, "same_folder": True, "segments": len(ids),
                        "prior_segments_retained": True, "speaker_name_retained": True, "sqlite_integrity": "ok"})
        prior_ids = ids
        (root / "results.json").write_text(json.dumps(results, indent=2), encoding="utf8")
        print(json.dumps(results[-1]), flush=True)
    # Sixth packaged launch proves the fifth crash also resumes. It completes via
    # the normal controller Finalize path, then exits after the QA deadline.
    final_env = {**env, "VLT_PHASE8_FINISH_AFTER_S": "18"}
    final = subprocess.Popen([str(exe), "--phase8-recovery-test"], env=final_env)
    try:
        assert final.wait(timeout=90) == 0
    finally:
        if final.poll() is None:
            final.kill(); final.wait(timeout=10)
    with sqlite3.connect(root / "app.db") as connection:
        assert connection.execute("SELECT status FROM sessions WHERE session_id=?", (sid,)).fetchone()[0] == "completed"
    print(json.dumps({"sixth_resume_and_finalize": "passed", "session_id": sid}), flush=True)


if __name__ == "__main__":
    main()
