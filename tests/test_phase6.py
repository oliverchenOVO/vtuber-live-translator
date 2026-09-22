import json
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QTimer

from vlt.database.database import Database
from vlt.sessions.manager import APP_VERSION, SessionManager
from vlt.subtitles.live import TranscriptCoordinator
from vlt.settings.manager import SettingsManager
from vlt.ui.controller import StudioController


def setup_session(tmp_path, title="Phase 6 Test"):
    database = Database(tmp_path / "app.db")
    manager = SessionManager(tmp_path, database)
    session = manager.create(title=title)
    return database, manager, session, Path(session["folder_path"])


def speech(segment_id, start=100, end=1000, speaker="speaker_001", text="昨日は3時間しか寝てない"):
    return {"id": segment_id, "type": "speech", "start_ms": start, "end_ms": end,
            "language": "ja", "speaker_id": speaker, "original": text,
            "asr_state": "final", "translation_state": "pending"}


def translated(manager, session_id, segment_id, text="我昨天只睡了三個小時。"):
    assert manager.update_final_translation(
        session_id, segment_id,
        {"target": "zh-TW", "style": "natural", "text": text})


def test_session_json_contains_complete_metadata_and_round_trips(tmp_path):
    db, manager, session, folder = setup_session(tmp_path)
    sid = session["session_id"]
    manager.set_audio_source(sid, "chrome.exe · PID 123")
    manager.append_final(sid, speech("one", end=3700))
    manager.finish(sid, "both")
    metadata = json.loads((folder / "session.json").read_text(encoding="utf-8"))
    assert metadata["session_id"] == sid
    assert metadata["started_at"] and metadata["ended_at"]
    assert metadata["source_process"] == "chrome.exe · PID 123"
    assert metadata["duration_ms"] == 3700
    assert metadata["recording_enabled"] is False
    assert metadata["app_version"] == APP_VERSION
    assert json.loads(json.dumps(metadata, ensure_ascii=False)) == metadata
    db.close()


def test_history_has_title_date_duration_language_speaker_count_and_status(tmp_path):
    db, manager, session, _ = setup_session(tmp_path)
    manager.append_final(session["session_id"], speech("one", end=61000))
    row = manager.list_sessions()[0]
    assert row["title"] == "Phase 6 Test"
    assert row["date"] and row["duration"] == "00:01:01"
    assert row["source_language"] == "ja" and row["speaker_count"] == 1
    assert row["status"] == "active"
    db.close()


def test_interrupted_resume_keeps_same_session_and_folder(tmp_path):
    db, manager, session, folder = setup_session(tmp_path)
    sid = session["session_id"]
    manager.append_final(sid, speech("one"))
    assert manager.mark_interrupted() == 1
    db.close()
    reopened = Database(tmp_path / "app.db")
    resumed = SessionManager(tmp_path, reopened).resume(sid)
    assert resumed["session_id"] == sid and Path(resumed["folder_path"]) == folder
    assert len(SessionManager(tmp_path, reopened).list_segments(sid)) == 1
    reopened.close()


def test_rename_regenerates_markdown_without_renaming_folder(tmp_path):
    db, manager, session, folder = setup_session(tmp_path)
    manager.rename(session["session_id"], "龍的新標題")
    assert Path(manager.get(session["session_id"])["folder_path"]) == folder
    assert "# 龍的新標題" in (folder / "transcript.md").read_text(encoding="utf-8")
    db.close()


def test_speaker_edit_manual_unknown_and_merge_regenerate_outputs(tmp_path):
    db, manager, session, folder = setup_session(tmp_path)
    sid = session["session_id"]
    one = manager.add_speaker(sid, 0)
    two = manager.add_speaker(sid, 100)
    manager.append_final(sid, speech("one", speaker=two))
    translated(manager, sid, "one")
    assert manager.assign_segment_speaker(sid, "one", "unknown")
    assert "未知說話人" in (folder / "transcript.md").read_text(encoding="utf-8")
    assert manager.assign_segment_speaker(sid, "one", two)
    assert manager.merge_speakers(sid, two, one) == 1
    manager.update_speaker(sid, one, display_name="胡桃のあ")
    output = (folder / "transcript.md").read_text(encoding="utf-8")
    assert "胡桃のあ" in output and "manual_assignment" in output and "merge" in output
    db.close()


@pytest.mark.parametrize("mode,expected,absent", [
    ("translation", "我昨天只睡了三個小時。", "昨日は3時間しか寝てない"),
    ("original", "昨日は3時間しか寝てない", "我昨天只睡了三個小時。"),
    ("both", "我昨天只睡了三個小時。", None),
])
def test_srt_vtt_modes_are_timestamped_and_valid(tmp_path, mode, expected, absent):
    db, manager, session, folder = setup_session(tmp_path)
    sid = session["session_id"]
    manager.append_final(sid, speech("one"))
    translated(manager, sid, "one")
    manager.render_exports(sid, mode)
    srt = (folder / "exports" / "transcript.srt").read_text(encoding="utf-8")
    vtt = (folder / "exports" / "transcript.vtt").read_text(encoding="utf-8")
    assert "00:00:00,100 --> 00:00:01,000" in srt and expected in srt
    assert vtt.startswith("WEBVTT\n\n") and "00:00:00.100 --> 00:00:01.000" in vtt
    if absent:
        assert absent not in srt
    if mode == "both":
        assert "昨日は3時間しか寝てない" in srt
    db.close()


def test_markdown_contains_session_speakers_translation_original_and_multi_event(tmp_path):
    db, manager, session, folder = setup_session(tmp_path)
    sid = session["session_id"]
    one = manager.add_speaker(sid, 0)
    manager.append_final(sid, speech("one", speaker=one))
    translated(manager, sid, "one")
    manager.append_overlap_event(sid, 1100, 1500, [], "unknown_overlap", 0.4)
    manager.render_exports(sid, "both")
    output = (folder / "transcript.md").read_text(encoding="utf-8")
    for token in ("## Session", "## Speakers", "## Transcript", "**翻譯**", "**原文**", "【重疊】"):
        assert token in output
    db.close()


def test_pending_translation_survives_crash_and_is_searchable(tmp_path):
    db, manager, session, _ = setup_session(tmp_path)
    sid = session["session_id"]
    manager.append_final(sid, speech("one", text="Pekora arrived"))
    db.close()
    reopened = Database(tmp_path / "app.db")
    restored = SessionManager(tmp_path, reopened)
    assert restored.pending_translations(sid)[0]["id"] == "one"
    assert restored.search(sid, "Pekora")[0]["id"] == "one"
    reopened.close()


def test_search_matches_original_translation_and_speaker_name(tmp_path):
    db, manager, session, _ = setup_session(tmp_path)
    sid = session["session_id"]
    speaker = manager.add_speaker(sid, 0)
    manager.append_final(sid, speech("one", speaker=speaker, text="hello world"))
    translated(manager, sid, "one", "你好世界")
    manager.update_speaker(sid, speaker, display_name="Alice")
    assert {manager.search(sid, query)[0]["id"] for query in ("hello", "你好", "alice")} == {"one"}
    db.close()


def test_finalize_cleans_only_temporary_cache_and_produces_exact_required_files(tmp_path):
    db, manager, session, folder = setup_session(tmp_path)
    sid = session["session_id"]
    manager.append_final(sid, speech("one"))
    (folder / "cache").mkdir()
    (folder / "cache" / "temporary.bin").write_bytes(b"x")
    manager.finish(sid)
    assert not (folder / "cache").exists()
    assert (folder / "session.json").exists() and (folder / "transcript.json").exists()
    assert (folder / "transcript.md").exists()
    assert (folder / "exports" / "transcript.srt").exists()
    assert (folder / "exports" / "transcript.vtt").exists()
    assert manager.get(sid)["status"] == "completed"
    db.close()


def test_export_failure_keeps_session_active_for_retry(tmp_path, monkeypatch):
    db, manager, session, _ = setup_session(tmp_path)
    sid = session["session_id"]
    monkeypatch.setattr(manager, "render_exports", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        manager.finish(sid)
    assert manager.get(sid)["status"] == "active"
    assert manager.get(sid)["ended_at"] is None
    db.close()


def test_auto_close_is_blocked_when_final_export_fails(tmp_path, monkeypatch):
    QCoreApplication.instance() or QCoreApplication([])
    db, manager, session, _ = setup_session(tmp_path)
    class Audio:
        state = "idle"
        peak = 0.0
        error = ""
        async def list_sources(self): return []
        async def stop(self): return None
    settings = SettingsManager(tmp_path)
    settings.set("auto_close_after_finalize", True)
    controller = StudioController(manager, settings, lambda: None, audio=Audio(),
                                  translation_backend_factory=lambda: None)
    controller._selected_id = session["session_id"]
    controller._transcript = TranscriptCoordinator(manager, session["session_id"], initial_limit=120)
    controller._finalizing = True
    controller._translation_pipeline.pending_final_count = lambda: 0
    monkeypatch.setattr(manager, "finish", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")))
    scheduled = []
    monkeypatch.setattr(QTimer, "singleShot", lambda *args: scheduled.append(args))
    controller._finish_after_pending()
    assert not controller.finalizing and manager.get(session["session_id"])["status"] == "active"
    assert scheduled == [] and "失敗" in controller.message
    controller.shutdown()
    db.close()


def test_auto_close_is_scheduled_only_after_successful_finalize(tmp_path, monkeypatch):
    QCoreApplication.instance() or QCoreApplication([])
    db, manager, session, _ = setup_session(tmp_path)
    class Audio:
        state = "idle"
        peak = 0.0
        error = ""
        async def list_sources(self): return []
        async def stop(self): return None
    settings = SettingsManager(tmp_path)
    settings.set("auto_close_after_finalize", True)
    controller = StudioController(manager, settings, lambda: None, audio=Audio(),
                                  translation_backend_factory=lambda: None)
    controller._selected_id = session["session_id"]
    controller._transcript = TranscriptCoordinator(manager, session["session_id"], initial_limit=120)
    controller._finalizing = True
    controller._translation_pipeline.pending_final_count = lambda: 0
    scheduled = []
    monkeypatch.setattr(QTimer, "singleShot", lambda *args: scheduled.append(args))
    controller._finish_after_pending()
    assert manager.get(session["session_id"])["status"] == "completed"
    assert len(scheduled) == 1 and scheduled[0][0] == 50
    controller.shutdown()
    db.close()


def test_source_closed_requests_auto_finalize_without_crash(tmp_path, monkeypatch):
    QCoreApplication.instance() or QCoreApplication([])
    db, manager, session, _ = setup_session(tmp_path)
    class Audio:
        state = "error"
        peak = 0.0
        error = "音訊來源已關閉"
        async def list_sources(self): return []
        async def stop(self): return None
    controller = StudioController(manager, SettingsManager(tmp_path), lambda: None, audio=Audio(),
                                  translation_backend_factory=lambda: None)
    controller._selected_id = session["session_id"]
    controller._transcript = TranscriptCoordinator(manager, session["session_id"], initial_limit=120)
    controller._audio_status = Audio.error
    completed = []
    monkeypatch.setattr(controller, "_complete_session", lambda: completed.append(True))
    controller._poll_audio()
    assert completed == [True] and controller._source_error_handled
    controller.shutdown()
    db.close()


def test_finalize_live_partial_persists_once_with_pending_translation(tmp_path):
    db, manager, session, _ = setup_session(tmp_path)
    from vlt.asr.base import Recognition
    transcript = TranscriptCoordinator(manager, session["session_id"])
    transcript.apply_partial(Recognition("live", "まだ話しています", "ja", 10, 900, False))
    final = transcript.finalize_live()
    assert final and final["asr_state"] == "final"
    assert final["translation_status"] == "pending"
    assert transcript.finalize_live() is None
    assert manager.pending_translations(session["session_id"])[0]["id"] == "segment_live"
    db.close()


def test_delete_removes_database_rows_and_session_folder(tmp_path):
    db, manager, session, folder = setup_session(tmp_path)
    manager.finish(session["session_id"])
    manager.delete(session["session_id"])
    assert manager.get(session["session_id"]) is None and not folder.exists()
    db.close()


def test_large_session_source_remains_complete_while_ui_can_page(tmp_path):
    db, manager, session, folder = setup_session(tmp_path)
    sid = session["session_id"]
    for index in range(260):
        manager.append_final(sid, speech(str(index), index * 1000, index * 1000 + 800,
                                         text=f"line {index}"))
    source = json.loads((folder / "transcript.json").read_text(encoding="utf-8"))
    assert len(source["segments"]) == 260
    paged = TranscriptCoordinator(manager, sid, initial_limit=120)
    assert len(paged.finals) == 120 and paged.earlier_count == 140
    assert paged.load_earlier() == 120 and len(paged.finals) == 240
    assert manager.search(sid, "line", limit=120)[-1]["id"] == "119"
    db.close()
