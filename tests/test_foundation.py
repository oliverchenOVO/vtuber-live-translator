import json
from pathlib import Path

from vlt.database.database import Database
from vlt.sessions.manager import SessionManager
from vlt.settings.manager import SettingsManager


def test_sessions_have_unique_folders_and_json(tmp_path: Path):
    db = Database(tmp_path / "app.db")
    manager = SessionManager(tmp_path, db)
    first = manager.create("同名直播")
    second = manager.create("同名直播")
    assert first["session_id"] != second["session_id"]
    assert first["folder_path"] != second["folder_path"]
    assert len(manager.list_sessions()) == 2
    for session in (first, second):
        folder = Path(session["folder_path"])
        assert json.loads((folder / "session.json").read_text(encoding="utf-8"))["session_id"] == session["session_id"]
        assert json.loads((folder / "transcript.json").read_text(encoding="utf-8"))["segments"] == []
        assert (folder / "exports").is_dir()
        assert not (folder / "audio").exists()
    db.close()


def test_interrupted_session_keeps_identity_and_folder(tmp_path: Path):
    db = Database(tmp_path / "app.db")
    manager = SessionManager(tmp_path, db)
    session = manager.create()
    assert manager.mark_interrupted() == 1
    assert manager.mark_interrupted() == 0
    recovered = manager.get(session["session_id"])
    assert recovered["status"] == "interrupted"
    assert recovered["folder_path"] == session["folder_path"]
    assert json.loads((Path(session["folder_path"]) / "session.json").read_text(encoding="utf-8"))["status"] == "interrupted"
    db.close()


def test_finish_updates_database_and_json(tmp_path: Path):
    db = Database(tmp_path / "app.db")
    manager = SessionManager(tmp_path, db)
    session = manager.create()
    finished = manager.finish(session["session_id"])
    assert finished["status"] == "completed"
    assert finished["ended_at"]
    assert manager.get(session["session_id"])["status"] == "completed"
    assert json.loads((Path(session["folder_path"]) / "session.json").read_text(encoding="utf-8"))["status"] == "completed"
    db.close()


def test_settings_persist_without_audio_recording(tmp_path: Path):
    settings = SettingsManager(tmp_path)
    assert settings.values["save_audio"] is False
    settings.set("target_language", "zh-CN")
    assert SettingsManager(tmp_path).values["target_language"] == "zh-CN"
    assert SettingsManager(tmp_path).values["save_audio"] is False
