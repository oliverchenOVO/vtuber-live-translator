from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from vlt.database.database import Database
from vlt.sessions.manager import SessionManager, _atomic_json
from vlt.product.diagnostics import export_diagnostics
from vlt.product.downloads import download_resumable
from vlt.product.models import ModelManager
from vlt.translation.base import TranslationRequest
from vlt.translation.ollama_backend import OllamaTranslationBackend

CORPUS = json.loads((Path(__file__).parent / "fixtures" / "translation_corpus.json").read_text("utf8"))


def test_owned_runtime_close_releases_child_process(tmp_path):
    import subprocess
    import sys
    import time
    import psutil
    from vlt.product.models import hidden_process_flags
    marker = tmp_path / "child.pid"
    code = """
import pathlib, subprocess, sys, time
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
pathlib.Path(sys.argv[1]).write_text(str(child.pid))
time.sleep(60)
"""
    parent = subprocess.Popen([sys.executable, "-c", code, str(marker)],
                              creationflags=hidden_process_flags())
    manager = ModelManager(tmp_path / "models", tmp_path / "cache", tmp_path / "runtime")
    manager._ollama_process = parent
    child = None
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        assert marker.exists()
        child = psutil.Process(int(marker.read_text()))
        manager.close()
        assert parent.poll() is not None
        assert not child.is_running()
        assert manager._ollama_process is None
        manager.close()  # Idempotent.
    finally:
        manager.close()
        if child and child.is_running():
            child.kill()


def test_runtime_close_does_not_inspect_unowned_service(tmp_path, monkeypatch):
    import vlt.product.models as models
    manager = ModelManager(tmp_path / "models", tmp_path / "cache", tmp_path / "runtime")
    monkeypatch.setattr(models.psutil, "Process", lambda *_: pytest.fail("No owned runtime"))
    manager.close()


def test_uncertain_japanese_is_not_mistaken_for_negative():
    OllamaTranslationBackend._verify_facts("雨かもしれない", "可能會下雨", [])
    OllamaTranslationBackend._verify_facts("雨かもしれません", "或许会下雨", [])
    with pytest.raises(RuntimeError, match="否定"):
        OllamaTranslationBackend._verify_facts("行かないかもしれない", "可能會去", [])
    with pytest.raises(RuntimeError, match="推測"):
        OllamaTranslationBackend._verify_facts("雨かもしれない", "會下雨", [])


@pytest.mark.parametrize("source,output", [
    ("え、やって", "Translation into Traditional Chinese as used in Taiwan: 嘛，幹了"),
    ("おかよな!", "哇！等等！\nTranslation:"),
    ("で、見ました", "で、見ました"),
    ("よいしょー", "今天發生了很多事情。我去買了東西，然後見了朋友。" * 4),
])
def test_obvious_model_leakage_or_runaway_translation_stays_pending(source, output):
    with pytest.raises(RuntimeError):
        OllamaTranslationBackend._verify_facts(source, output, [])


def test_short_valid_translation_is_not_marked_as_runaway():
    OllamaTranslationBackend._verify_facts("よいしょー", "嘿咻！", [])


def test_score_is_not_translated_as_minutes():
    with pytest.raises(RuntimeError, match="分數"):
        OllamaTranslationBackend._verify_facts("100 points remaining", "還剩100分鐘", [])
    OllamaTranslationBackend._verify_facts("残り100ポイント", "還剩100分", [])


def test_final_drops_obsolete_partial_before_model_work():
    from vlt.translation.pipeline import BoundedTranslationQueue
    queue = BoundedTranslationQueue(capacity=2)
    queue.push(TranslationRequest("same", "今日は", "ja", "zh-TW", "natural"))
    queue.push(TranslationRequest("other", "明日", "ja", "zh-TW", "natural"))
    final = TranslationRequest("same", "今日はゲーム", "ja", "zh-TW", "natural", final=True)
    assert queue.push(final)
    assert queue.pop() == final
    assert queue.pop().segment_id == "other"
    assert len(queue) == 0 and queue.dropped_partials == 1


@pytest.mark.parametrize("source,good,bad", [("3 hours", "三小時", "13小時"),
    ("13 hours", "十三小時", "三小時"), ("20 people", "二十個人", "200個人"),
    ("3.5 seconds", "三點五秒", "35秒"), ("2026年", "二〇二六年", "二〇二五年")])
def test_numeric_tokens_do_not_match_substrings(source, good, bad):
    OllamaTranslationBackend._verify_facts(source, good, [])
    with pytest.raises(RuntimeError):
        OllamaTranslationBackend._verify_facts(source, bad, [])


@pytest.mark.parametrize("row", CORPUS, ids=lambda r: r["ja"])
@pytest.mark.parametrize("language", ["ja", "en"])
@pytest.mark.parametrize("locale", ["zh-TW", "zh-CN"])
def test_translation_regression_corpus(row, language, locale, monkeypatch):
    backend = OllamaTranslationBackend(allow_fallback=False)
    expected = row["tw" if locale == "zh-TW" else "cn"]
    monkeypatch.setattr(backend, "_generate", lambda *_: expected)
    from vlt.translation.verification import AlignmentReview
    monkeypatch.setattr(backend, "_verify_alignment", lambda *_: AlignmentReview("PASS"))
    monkeypatch.setattr(backend, "_verify_roundtrip", lambda *_: None)
    glossary = ()
    if "term" in row:
        glossary = ({"source": row["term"], "aliases": [row["alias"]],
                     "preferred_zh_tw": row["preferred"],
                     "preferred_zh_cn": row.get("preferred_cn", row["preferred"])},)
    request = TranslationRequest("case", row[language], language, locale, "natural", glossary=glossary, final=True)
    result = backend.translate_final(request)
    assert result.strip()
    if glossary:
        assert glossary[0]["preferred_zh_tw" if locale == "zh-TW" else "preferred_zh_cn"] in result
    if "bad" in row:
        with pytest.raises(RuntimeError):
            backend._verify_facts(row[language], row["bad"], [])


def manager(root):
    db = Database(root / "app.db")
    sessions = SessionManager(root, db)
    session = sessions.create()
    return db, sessions, session


def segment(i=0):
    return {"id": f"s{i}", "type": "speech", "asr_state": "final", "speaker_id": "unknown",
            "start_ms": i * 1000, "end_ms": i * 1000 + 800, "original": "今日は🎮\nHello <team>",
            "language": "ja", "translation": {"text": "今天遊戲\n第二行"}}


def test_long_final_never_bypasses_disabled_7b(monkeypatch):
    backend = OllamaTranslationBackend(allow_fallback=False)
    calls = []
    monkeypatch.setattr(backend, "_generate", lambda prompt, model: calls.append(model) or "確定會去")
    request = TranslationRequest("long", "たぶん行く。" * 30, "ja", "zh-TW", "natural", final=True)
    with pytest.raises(RuntimeError):
        backend.translate_final(request)
    assert calls == ["qwen2.5:1.5b"]


def test_json_fsync_before_replace(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("vlt.sessions.manager.os.fsync", lambda fd: calls.append(fd))
    _atomic_json(tmp_path / "session.json", {"title": "中文 🎮"})
    assert calls and json.loads((tmp_path / "session.json").read_text("utf8"))["title"] == "中文 🎮"


def test_corrupt_json_recovers_from_sqlite(tmp_path):
    db, sessions, session = manager(tmp_path)
    sessions.append_final(session["session_id"], segment())
    path = Path(session["folder_path"]) / "transcript.json"
    path.write_bytes(b'{"segments":[')
    sessions.mark_interrupted()
    sessions.resume(session["session_id"])
    assert len(json.loads(path.read_text("utf8"))["segments"]) == 1
    db.close()


@pytest.mark.parametrize("title", ["胡桃のあ 雑談", "【APEX】大会！", "中文 測試", "emoji 🎮", ': * ? " < > |', "長" * 1000])
def test_unicode_and_unsafe_titles_preserve_metadata(tmp_path, title):
    db = Database(tmp_path / "app.db")
    sessions = SessionManager(tmp_path, db)
    session = sessions.create(title)
    folder = Path(session["folder_path"])
    assert folder.resolve().is_relative_to(sessions.root.resolve()) and len(folder.name) < 100
    paths = sessions.render_exports(session["session_id"])
    assert Path(paths["markdown"]).read_text("utf8").startswith("# " + title)
    db.close()


def test_batch_unknown_assignment_is_scoped_and_durable(tmp_path):
    db, sessions, session = manager(tmp_path)
    sid = session["session_id"]
    speaker = sessions.add_speaker(sid, 0)
    for i in range(4):
        sessions.append_final(sid, segment(i))
    assert sessions.assign_unknown_range(sid, 1000, 3000, speaker) == 2
    rows = sessions.list_segments(sid)
    assert [r["speaker_id"] for r in rows] == ["unknown", speaker, speaker, "unknown"]
    assert not sessions.update_automatic_assignment(sid, "s1", "unknown", .9)
    db.close()


def test_diagnostics_never_exports_secrets_or_user_content(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "app.log").write_text("SECRET token=abc transcript=private\nPipeline metrics: finals=3 asr_dropped=0 SECRET\n", "utf8")
    result = export_diagnostics(tmp_path / "support.zip", {"api_key": "SECRET", "source_language": "SECRET", "target_language": "zh-TW"},
                                {"cpu": "SECRET", "ram_gb": 32, "logical_cores": 20}, logs)
    with zipfile.ZipFile(result) as archive:
        content = " ".join(archive.read(name).decode() for name in archive.namelist())
    assert "SECRET" not in content and "private" not in content and "abc" not in content
    assert '"finals": 3.0' in content


def test_truncated_download_preserves_resume_file(tmp_path):
    class Response(io.BytesIO):
        status = 200
        headers = {"Content-Length": "10"}
    target = tmp_path / "model.bin"
    with pytest.raises(RuntimeError, match="下載中斷"):
        download_resumable("https://example.invalid/model", target, opener=lambda *a, **k: Response(b"abc"))
    assert not target.exists() and target.with_suffix(".bin.part").read_bytes() == b"abc"


def test_whisper_network_failure_does_not_delete_cache(tmp_path, monkeypatch):
    model = ModelManager(tmp_path / "models", tmp_path / "cache", tmp_path / "runtime")
    pending = model.root / "models--Systran--faster-whisper-base" / "blobs" / "payload.incomplete"
    pending.parent.mkdir(parents=True)
    pending.write_bytes(b"resumable payload")
    def fail(*a, **k):
        raise OSError("network disconnected")
    monkeypatch.setattr("huggingface_hub.snapshot_download", fail)
    with pytest.raises(OSError):
        model.install("asr", lambda *a: None)
    assert pending.read_bytes() == b"resumable payload"


def test_verify_detects_broken_diarization_without_deleting_it(tmp_path):
    model = ModelManager(tmp_path / "models", tmp_path / "cache", tmp_path / "runtime")
    path = model.root / "diarization" / "segmentation.onnx"
    path.parent.mkdir()
    path.write_bytes(b"corrupt model")
    with pytest.raises(RuntimeError, match="驗證失敗"):
        model.verify("diarization")
    assert path.exists()


def test_disk_full_finalization_keeps_database_active(tmp_path, monkeypatch):
    db, sessions, session = manager(tmp_path)
    sessions.append_final(session["session_id"], segment())
    def disk_full(*a, **k):
        raise OSError(28, "No space left")
    monkeypatch.setattr(sessions, "render_exports", disk_full)
    with pytest.raises(OSError):
        sessions.finish(session["session_id"])
    assert sessions.get(session["session_id"])["status"] == "active"
    assert sessions.segment_count(session["session_id"]) == 1
    assert db.connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    db.close()


def test_completed_partial_download_recovers_after_wizard_crash(tmp_path):
    import hashlib
    import urllib.error
    data = b"fully received model"
    path = tmp_path / "model.bin"
    path.with_suffix(".bin.part").write_bytes(data)
    def range_eof(*a, **k):
        raise urllib.error.HTTPError("url", 416, "Range at EOF", {}, None)
    assert download_resumable("https://example.invalid/model", path, hashlib.sha256(data).hexdigest(),
                              opener=range_eof).read_bytes() == data


def test_windows_regular_file_asr_corruption_is_verified(tmp_path):
    model = ModelManager(tmp_path / "models", tmp_path / "cache", tmp_path / "runtime")
    folder = model.asr_snapshot()
    folder.mkdir(parents=True)
    (folder / "model.bin").write_bytes(b"corruption without symlinks")
    assert model._damaged_asr_files() == ["model.bin"]


def test_live_window_and_identity_cache_stay_bounded(tmp_path):
    from vlt.asr.base import Recognition
    from vlt.subtitles.live import TranscriptCoordinator
    db, sessions, session = manager(tmp_path)
    transcript = TranscriptCoordinator(sessions, session["session_id"], initial_limit=12)
    for i in range(40):
        transcript.apply_partial(Recognition(str(i), "日本語", "ja", i * 1000, i * 1000 + 800, False, first_audio_at=0))
        transcript.apply_final(Recognition(str(i), "日本語", "ja", i * 1000, i * 1000 + 800, True))
    assert len(transcript.finals) == 12 and transcript.earlier_count == 28
    assert len(transcript._partial_measured) == 0
    # Forget the in-memory identity; SQLite still prevents an old replay becoming LIVE.
    transcript._seen.clear()
    assert not transcript.apply_partial(Recognition("0", "日本語", "ja", 0, 800, False))
    assert transcript.live is None
    assert sessions.segment_count(session["session_id"]) == 40
    db.close()


def test_audio_completion_does_not_retain_com_operation():
    import weakref
    from vlt.audio.native.process_loopback import ActivationHandler
    class Operation: pass
    operation = Operation()
    reference = weakref.ref(operation)
    handler = ActivationHandler()
    handler.ActivateCompleted(operation)
    del operation
    assert handler.event.is_set() and reference() is None


def test_asr_stop_unloads_native_weights_and_drops_task_references():
    import asyncio
    from vlt.asr.faster_whisper_backend import FasterWhisperBackend
    unloaded = []
    class Native:
        def unload_model(self): unloaded.append(True)
    class Model:
        model = Native()
    async def run():
        backend = FasterWhisperBackend(device="cpu", model_factory=lambda *a, **k: Model())
        await backend.start()
        await backend.stop()
        assert backend._model is None and backend._consumer is None and backend._infer_worker is None
    asyncio.run(run())
    assert unloaded == [True]
