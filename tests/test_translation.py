import json
import time
from pathlib import Path

import pytest

from vlt.asr.base import Recognition
from vlt.database.database import Database
from vlt.sessions.manager import SessionManager
from vlt.subtitles.live import TranscriptCoordinator
from vlt.translation.base import TranslationRequest
from vlt.translation.glossary import Glossary
from vlt.translation.ollama_backend import OllamaTranslationBackend
from vlt.translation.pipeline import BoundedTranslationQueue, TranslationPipeline


def setup(tmp_path):
    db = Database(tmp_path / "db.sqlite")
    manager = SessionManager(tmp_path, db)
    session = manager.create()
    return db, manager, session, TranscriptCoordinator(manager, session["session_id"])


def recog(text, final=False, uid="one", lang="ja"):
    return Recognition(uid, text, lang, 100, 800, final)


def translation(text, target="zh-TW", style="natural"):
    return {"target": target, "style": style, "text": text}


def request(text="今日は", final=False, uid="one", target="zh-TW"):
    return TranslationRequest(uid, text, "ja", target, "natural", final=final)


def test_partial_translation_replaces_same_live_segment(tmp_path):
    db, _, _, transcript = setup(tmp_path)
    transcript.apply_partial(recog("今日は"))
    segment_id = transcript.live["id"]
    assert transcript.apply_partial_translation(segment_id, "今日は", translation("今天"))
    transcript.apply_partial(recog("今日は"))
    assert transcript.live["translation"]["text"] == "今天"
    transcript.apply_partial(recog("今日はみんなと"))
    assert not transcript.apply_partial_translation(segment_id, "今日は", translation("過時結果"))
    assert transcript.apply_partial_translation(segment_id, "今日はみんなと", translation("今天要和大家"))
    assert transcript.live["id"] == segment_id
    assert transcript.live["translation"]["text"] == "今天要和大家"
    assert transcript.finals == []
    db.close()


def test_final_retranslation_replaces_partial_and_is_immediately_durable(tmp_path):
    db, manager, session, transcript = setup(tmp_path)
    transcript.apply_partial(recog("今日は"))
    transcript.apply_partial_translation(transcript.live["id"], "今日は", translation("今天…"))
    assert transcript.apply_final(recog("今日はみんなとゲームをやっていきます", True))
    assert transcript.live is None
    assert manager.pending_translations(session["session_id"])[0]["translation_state"] == "pending"
    final = translation("今天要和大家一起玩遊戲。")
    assert transcript.apply_final_translation("segment_one", final)
    assert not transcript.apply_final_translation("segment_one", final)
    saved = manager.list_segments(session["session_id"])[0]
    assert saved["translation"] == final
    assert saved["translation_state"] == "final"
    assert json.loads((Path(session["folder_path"]) / "transcript.json").read_text(encoding="utf-8"))["segments"] == [saved]
    assert db.connection.execute("SELECT translation FROM segments").fetchone()[0] == final["text"]
    db.close()


@pytest.mark.parametrize("original,translated,error", [
    ("昨日3時間しか寝てない", "我昨天只睡了三個小時。", False),
    ("昨日3時間しか寝てない", "我昨天睡了四個小時。", True),
    ("I did not sleep", "我沒有睡。", False),
    ("I did not sleep", "我睡了。", True),
    ("たぶん行くと思う", "我覺得大概會去。", False),
    ("たぶん行くと思う", "我一定會去。", True),
    ("I watched for a minute", "我看了好幾分鐘。", True),
    ("I watched for a minute", "我看了大概一分鐘。", False),
    ("昨日3時間しか寝てない", "我昨天只睡了不到三小時。", True),
])
def test_factual_guards(original, translated, error):
    if error:
        with pytest.raises(RuntimeError):
            OllamaTranslationBackend._verify_facts(original, translated, [])
    else:
        OllamaTranslationBackend._verify_facts(original, translated, [])


@pytest.mark.parametrize("target,preferred", [("zh-TW", "佩克拉"), ("zh-CN", "佩克拉")])
def test_locales_and_glossary_override_without_network(monkeypatch, target, preferred):
    from io import BytesIO
    class Response(BytesIO):
        def __enter__(self): return self
        def __exit__(self, *_): self.close()
    calls = []
    def urlopen(req, timeout):
        calls.append(json.loads(req.data))
        return Response(json.dumps({"response": "Pekora來了"}).encode())
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    glossary = ({"source": "ぺこら", "preferred_zh_tw": "佩克拉",
                 "preferred_zh_cn": "佩克拉", "aliases": ["Pekora"]},)
    backend = OllamaTranslationBackend()
    text = backend.translate_final(TranslationRequest("id", "Pekora arrived", "en", target, "natural", glossary=glossary))
    assert preferred in text
    assert ("Traditional Chinese" if target == "zh-TW" else "Simplified Chinese") in calls[0]["prompt"]
    assert calls[0]["options"]["num_gpu"] == 0


def test_styles_change_prompt_not_facts(monkeypatch):
    from io import BytesIO
    prompts = []
    def urlopen(req, timeout):
        prompts.append(json.loads(req.data)["prompt"])
        return BytesIO(b'{"response":"I translated this."}')
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    backend = OllamaTranslationBackend()
    for style in ("natural", "faithful", "minimal"):
        backend.translate_final(TranslationRequest("id", "Hello", "en", "zh-TW", style))
    assert len(set(prompts)) == 3
    assert all("Preserve names, numbers, times, negation, uncertainty" in item for item in prompts)


def test_local_service_disconnect_is_human_readable_and_keeps_pending(monkeypatch):
    import urllib.error
    def disconnected(*_args, **_kwargs):
        raise urllib.error.URLError("connection refused")
    monkeypatch.setattr("urllib.request.urlopen", disconnected)
    with pytest.raises(RuntimeError, match="Ollama"):
        OllamaTranslationBackend().translate_final(request("Hello", True))


def test_glossary_crud_import_export(tmp_path):
    glossary = Glossary(tmp_path / "canonical.json")
    glossary.upsert("ぺこら", "佩克拉", "佩克拉", ["Pekora"])
    glossary.upsert("ぺこら", "佩克拉", "佩克拉", ["ぺこら"])
    assert len(glossary.list()) == 1
    export = tmp_path / "export.json"
    glossary.export_file(export)
    glossary.delete("ぺこら")
    assert glossary.list() == []
    glossary.import_file(export)
    assert glossary.list()[0]["aliases"] == ["ぺこら"]


def test_bounded_queue_prioritizes_final_and_coalesces_partials():
    queue = BoundedTranslationQueue(capacity=3)
    for number in range(1000):
        queue.push(request(str(number)))
    assert len(queue) == 1
    queue.push(request("one", True, "one"))
    queue.push(request("two", True, "two"))
    assert queue.push(request("three", True, "three"))
    assert len(queue) == 3
    assert not queue.push(request("four", True, "four"))
    for number in range(1000):
        assert not queue.push(request(str(number), True, f"backlog-{number}"))
    assert queue.pop().segment_id == "one"
    assert queue.dropped_partials > 0


def test_throttled_latest_partial_is_eventually_sent_without_new_asr_event():
    seen = []
    class Backend:
        def translate_partial(self, req): return req.original
        def translate_final(self, req): return req.original
    pipeline = TranslationPipeline(Backend, lambda req, value, *_: seen.append(value), partial_interval=.1)
    pipeline.start()
    pipeline.submit(request("今日は"))
    pipeline.submit(request("今日はみんなと"))
    deadline = time.monotonic() + 2
    while "今日はみんなと" not in seen and time.monotonic() < deadline:
        time.sleep(.01)
    pipeline.stop()
    assert "今日はみんなと" in seen


def test_translation_failure_never_blocks_asr_and_pending_recovery(tmp_path):
    db, manager, session, transcript = setup(tmp_path)
    events = []
    class Failing:
        def translate_final(self, req): raise RuntimeError("service offline")
        def translate_partial(self, req): raise RuntimeError("service offline")
    pipeline = TranslationPipeline(Failing, lambda *args: events.append(args), partial_interval=0)
    pipeline.start()
    transcript.apply_final(recog("I did not sleep", True, lang="en"))
    pipeline.submit(request("I did not sleep", True))
    deadline = time.monotonic() + 2
    while not events and time.monotonic() < deadline:
        time.sleep(.01)
    pipeline.stop()
    assert events and events[0][1] is None
    assert manager.list_segments(session["session_id"])[0]["original"] == "I did not sleep"
    manager.mark_interrupted()
    assert manager.resume(session["session_id"])["folder_path"] == session["folder_path"]
    assert len(manager.pending_translations(session["session_id"])) == 1
    resumed = TranscriptCoordinator(manager, session["session_id"])
    assert resumed.apply_final_translation("segment_one", translation("我沒有睡。"))
    assert manager.pending_translations(session["session_id"]) == []
    db.close()


def test_context_limits_to_recent_final_segments(tmp_path):
    db, manager, session, transcript = setup(tmp_path)
    transcript.apply_final(recog("昨日は", True, uid="a"))
    second = Recognition("b", "今日は", "ja", 1000, 2000, True)
    transcript.apply_final(second)
    assert [item["id"] for item in manager.list_segments(session["session_id"])] == ["segment_a", "segment_b"]
    db.close()


def test_controller_overlay_receives_translated_segment_and_session_persists(tmp_path):
    import asyncio
    from PySide6.QtCore import QCoreApplication
    from vlt.settings.manager import SettingsManager
    from vlt.ui.controller import StudioController

    app = QCoreApplication.instance() or QCoreApplication([])
    db = Database(tmp_path / "overlay.db")
    manager = SessionManager(tmp_path, db)
    class Audio:
        state = "idle"
        peak = 0
        async def list_sources(self): return []
    class Backend:
        def translate_partial(self, req): return "今天…"
        def translate_final(self, req): return "今天要和大家玩遊戲。"
    controller = StudioController(manager, SettingsManager(tmp_path), lambda: None,
                                  audio=Audio(), translation_backend_factory=Backend)
    controller.createSession()
    controller._on_asr_recognition(recog("今日は"))
    deadline = time.monotonic() + 2
    while not controller.overlaySegment.get("translation") and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert controller.overlaySegment["translation"]["text"] == "今天…"
    controller._on_asr_recognition(recog("今日はみんなとゲームをやっていきます", True))
    while manager.pending_translations(controller.selectedSession["session_id"]) and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert controller.overlaySegment["translation"]["text"] == "今天要和大家玩遊戲。"
    assert controller.transcriptSegments[0]["translation_state"] == "final"
    assert len(manager.list_sessions()) == 1
    controller.shutdown()
    db.close()


def test_reopen_database_retains_completed_translation(tmp_path):
    db, manager, session, transcript = setup(tmp_path)
    transcript.apply_final(recog("I think it will rain", True, lang="en"))
    transcript.apply_final_translation("segment_one", translation("我覺得可能會下雨。"))
    db.close()
    reopened = Database(tmp_path / "db.sqlite")
    resumed = SessionManager(tmp_path, reopened)
    segments = resumed.list_segments(session["session_id"])
    assert segments[0]["translation"]["text"] == "我覺得可能會下雨。"
    assert resumed.pending_translations(session["session_id"]) == []
    reopened.close()
