from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts.phase8_export_probe import fixture
from vlt.database.database import Database
from vlt.sessions.manager import SessionManager


def kill_worker(root, stage):
    marker = root / "ready"
    marker.unlink(missing_ok=True)
    process = subprocess.Popen([sys.executable, "scripts/phase8_export_probe.py", str(root), "--crash-stage", stage],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        deadline = time.monotonic() + 25
        while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.05)
        assert marker.exists(), process.stderr.read().decode() if process.poll() is not None else "worker timed out"
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/PID", str(process.pid)], check=True,
                           stdout=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            process.kill()
        process.wait(timeout=10)
    finally:
        if process.poll() is None:
            process.kill(); process.wait(timeout=10)
        process.stderr.close()


def test_10020_segment_subtitles_indices_timestamps_unicode_and_events(tmp_path):
    db, manager, session = fixture(tmp_path)
    paths = manager.render_exports(session["session_id"], "both")
    srt = Path(paths["srt"]).read_text("utf8")
    vtt = Path(paths["vtt"]).read_text("utf8")
    cues = srt.strip().split("\n\n")
    assert len(cues) == 10020
    for i, cue in enumerate(cues, 1):
        lines = cue.splitlines()
        assert int(lines[0]) == i
        assert re.fullmatch(r"\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}", lines[1])
        assert lines[1].split(" --> ")[0] < lines[1].split(" --> ")[1]
    assert "07:59:" in cues[-1] and "橘ひなの &lt;Hinano&gt;" in srt
    assert "🎮" in srt and "Hello &lt;team&gt;" in srt and "【重疊】" in srt
    assert vtt.startswith("WEBVTT\n\n") and vtt.count(" --> ") == 10020
    assert Path(paths["markdown"]).read_text("utf8").startswith("# " + session["title"])
    db.close()


@pytest.mark.parametrize("stage", [".md", ".srt", ".vtt"])
def test_kill_during_large_export_does_not_complete_session(tmp_path, stage):
    db, manager, session = fixture(tmp_path)
    sid, folder = session["session_id"], session["folder_path"]
    db.close()
    kill_worker(tmp_path, stage)
    db = Database(tmp_path / "app.db")
    manager = SessionManager(tmp_path, db)
    assert manager.get(sid)["status"] == "active"
    assert db.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    manager.mark_interrupted()
    assert json.loads((Path(folder) / "session.json").read_text("utf8"))["status"] == "interrupted"
    manager.resume(sid)
    assert manager.finish(sid)["status"] == "completed"
    assert len(manager.list_segments(sid)) == 10020
    db.close()


def test_five_forced_kills_retain_identity_mapping_and_deduplication(tmp_path):
    db, manager, session = fixture(tmp_path, count=1)
    sid, folder = session["session_id"], session["folder_path"]
    db.close()
    for i in range(5):
        kill_worker(tmp_path, f"run-{i}")
        db = Database(tmp_path / "app.db")
        manager = SessionManager(tmp_path, db)
        assert manager.mark_interrupted() == 1
        resumed = manager.resume(sid)
        assert resumed["session_id"] == sid and resumed["folder_path"] == folder
        assert len(manager.list_sessions()) == 1
        rows = manager.list_segments(sid)
        assert len(rows) == i + 2 and len({r["id"] for r in rows}) == len(rows)
        assert not manager.append_final(sid, next(r for r in rows if r["id"] == f"crash_{i}"))
        assert manager.list_speakers(sid)[0]["display_name"] == "橘ひなの <Hinano>"
        assert db.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        db.close()
