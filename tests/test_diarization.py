import json
import asyncio
from pathlib import Path

import numpy as np
import pytest

from vlt.asr.base import Recognition
from vlt.asr.pipeline import ASRPipeline
from vlt.audio.base import AudioChunk
from vlt.database.database import Database
from vlt.diarization.base import SpeakerDecision, SpeakerObservation
from vlt.diarization.sherpa_backend import SherpaOnnxDiarizationBackend
from vlt.sessions.manager import SessionManager
from vlt.subtitles.live import TranscriptCoordinator
from vlt.translation.base import TranslationRequest
from vlt.translation.ollama_backend import OllamaTranslationBackend


def setup(tmp_path):
    db = Database(tmp_path / "app.db")
    manager = SessionManager(tmp_path, db)
    session = manager.create()
    return db, manager, session["session_id"], Path(session["folder_path"])


def segment(sid, speaker="unknown", start=100, end=900):
    return {"id": sid, "type": "speech", "start_ms": start, "end_ms": end,
            "language": "ja", "speaker_id": speaker, "speaker_confidence": 0.0,
            "speaker_assignment": "automatic", "original": "こんにちは",
            "asr_state": "final", "translation_state": "pending"}


def test_single_speaker_stays_stable_with_multiple_embeddings(tmp_path):
    backend = SherpaOnnxDiarizationBackend(tmp_path)
    one = np.eye(4, dtype=np.float32)[0]
    ids = [backend._identify(one, i * 2000, i * 2000 + 1500)[0] for i in range(8)]
    assert ids == [None] + ["speaker_001"] * 7


def test_tentative_candidate_cannot_duplicate_strong_existing_voice(tmp_path):
    backend = SherpaOnnxDiarizationBackend(tmp_path)
    one = np.array([1.0, 0.0], dtype=np.float32)
    noisy = np.array([0.25, 0.9682458], dtype=np.float32)
    returning = np.array([0.7, 0.7141428], dtype=np.float32)
    assert backend._identify(one, 0, 1500)[0] is None
    assert backend._identify(one, 2000, 3500)[0] == "speaker_001"
    assert backend._identify(noisy, 4000, 5500)[0] is None
    assert backend._identify(returning, 6000, 7500)[0] == "speaker_001"
    assert len(backend._profiles) == 1


def test_overlapping_similar_voice_stays_unknown_instead_of_new_id(tmp_path):
    backend = SherpaOnnxDiarizationBackend(tmp_path)
    original = np.array([1.0, 0.0], dtype=np.float32)
    similar = np.array([0.67, 0.74236], dtype=np.float32)
    assert backend._identify(original, 0, 1500)[0] is None
    assert backend._identify(original, 2000, 3500)[0] == "speaker_001"
    speaker, _confidence = backend._identify(similar, 3000, 4500, {"speaker_001"})
    assert speaker is None
    assert len(backend._profiles) == 1
    assert backend._next_number == 2


def test_changed_delivery_near_existing_voice_stays_unknown(tmp_path):
    backend = SherpaOnnxDiarizationBackend(tmp_path)
    one = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    other = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    changed = _normalized_for_test(np.array([0.55, 0.0, 0.835], dtype=np.float32))
    backend._identify(one, 0, 1500)
    assert backend._identify(one, 2000, 3500)[0] == "speaker_001"
    assert backend._identify(np.array([0.0, 0.0, 1.0], dtype=np.float32),
                             4000, 5500)[0] is None
    assert backend._identify(changed, 6000, 7500)[0] is None
    assert backend._identify(changed, 8000, 9500)[0] is None
    assert len(backend._profiles) == 1
    assert backend._identify(other, 10000, 11500)[0] is None
    assert backend._identify(other, 12000, 13500)[0] == "speaker_002"


def test_second_third_fourth_speaker_joins_without_renumbering(tmp_path):
    backend = SherpaOnnxDiarizationBackend(tmp_path)
    vectors = np.eye(5, dtype=np.float32)
    assert backend._identify(vectors[0], 0, 1500)[0] is None
    assert backend._identify(vectors[0], 2000, 3500)[0] == "speaker_001"
    for number in range(1, 4):
        assert backend._identify(vectors[number], number * 4000, number * 4000 + 1500)[0] is None
        second = backend._identify(vectors[number], number * 4000 + 2000,
                                   number * 4000 + 3500)[0]
        if number == 3:
            assert second is None
            assert backend._identify(vectors[number], number * 4000 + 4000,
                                     number * 4000 + 5500)[0] == "speaker_004"
        else:
            assert second == f"speaker_{number+1:03d}"
    assert backend._identify(vectors[0], 17000, 19000)[0] == "speaker_001"
    assert backend._identify(vectors[4], 21000, 22500)[0] is None
    assert backend._identify(vectors[4], 23000, 24500)[0] is None
    assert backend.status == "limited"


def test_fourth_speaker_candidate_rejects_similarity_to_existing_voice(tmp_path):
    backend = SherpaOnnxDiarizationBackend(tmp_path)
    basis = np.eye(5, dtype=np.float32)
    backend._identify(basis[0], 0, 1500)
    backend._identify(basis[0], 2000, 3500)
    for number in range(1, 3):
        backend._identify(basis[number], number * 4000, number * 4000 + 1500)
        backend._identify(basis[number], number * 4000 + 2000,
                          number * 4000 + 3500)
    assert len(backend._profiles) == 3
    assert backend._identify(basis[4], 14000, 15500)[0] is None
    mixed = _normalized_for_test(basis[4] + 0.55 * basis[1])
    assert backend._identify(mixed, 16000, 17500)[0] is None
    assert len(backend._profiles) == 3


def _normalized_for_test(vector):
    return vector / np.linalg.norm(vector)


def test_speaker_id_embedding_and_resume_persist(tmp_path):
    db, manager, sid, folder = setup(tmp_path)
    one = manager.add_speaker(sid, 100, [1.0, 0.0])
    two = manager.add_speaker(sid, 200, [0.0, 1.0])
    manager.add_embedding(sid, two, [0.1, 0.9])
    for _ in range(8):
        manager.add_embedding(sid, two, [0.0, 1.0])
    assert one == "speaker_001" and two == "speaker_002"
    assert len(manager.list_embeddings(sid)[two]) == 3
    manager.mark_interrupted()
    db.close()
    reopened = Database(tmp_path / "app.db")
    resumed = SessionManager(tmp_path, reopened)
    resumed.resume(sid)
    assert resumed.list_speakers(sid)[1]["speaker_id"] == two
    backend = SherpaOnnxDiarizationBackend(tmp_path)
    backend.reset_session(resumed.list_speakers(sid), resumed.list_embeddings(sid))
    assert backend._next_number == 3
    reopened.close()


def test_existing_embedding_dimension_selects_compatible_model(tmp_path):
    backend = SherpaOnnxDiarizationBackend(tmp_path)
    speaker = [{"speaker_id": "speaker_001"}]
    backend.reset_session(speaker, {"speaker_001": [[1.0] * 512]})
    assert backend._legacy_model
    assert len(backend._profiles["speaker_001"][0]) == 512
    backend.reset_session(speaker, {"speaker_001": [[1.0] * 192, [1.0] * 512]})
    assert backend._legacy_model
    assert len(backend._profiles["speaker_001"]) == 1
    backend.reset_session(speaker, {"speaker_001": [[1.0] * 192]})
    assert not backend._legacy_model
    assert len(backend._profiles["speaker_001"][0]) == 192


def test_rename_mapping_and_exports_use_display_name(tmp_path):
    db, manager, sid, folder = setup(tmp_path)
    one = manager.add_speaker(sid, 0)
    two = manager.add_speaker(sid, 0)
    manager.append_final(sid, segment("s1", two))
    manager.update_final_translation(sid, "s1", {"target": "zh-TW", "style": "natural", "text": "你好。"})
    manager.update_speaker(sid, two, display_name="橘ひなの", person_id="person_hinano")
    assert not manager.register_speaker(sid, two, 500, [0.0, 1.0])
    assert manager.list_speakers(sid)[1]["display_name"] == "橘ひなの"
    assert manager.list_speakers(sid)[1]["person_id"] == "person_hinano"
    assert manager.list_segments(sid)[0]["speaker_id"] == two
    for filename in ("transcript.md", "subtitles.srt", "subtitles.vtt"):
        assert "橘ひなの" in (folder / "exports" / filename).read_text(encoding="utf-8")
    assert json.loads((folder / "transcript.json").read_text(encoding="utf-8"))["speakers"][1]["display_name"] == "橘ひなの"
    db.close()


def test_merge_changes_segments_but_preserves_manual_assignment_and_audit(tmp_path):
    db, manager, sid, _ = setup(tmp_path)
    one = manager.add_speaker(sid, 0)
    two = manager.add_speaker(sid, 0)
    manager.append_final(sid, segment("s1", two))
    manager.append_overlap_event(sid, 100, 400, [one, two], "overlapping_speech", 0.7)
    assert manager.merge_speakers(sid, two, one) == 1
    saved = next(item for item in manager.list_segments(sid) if item["id"] == "s1")
    assert saved["speaker_id"] == one and saved["speaker_assignment"] == "manual"
    assert not manager.update_automatic_assignment(sid, "s1", two, 0.99)
    event = next(item for item in manager.list_segments(sid) if item["type"] == "multi_speaker_event")
    assert event["speaker_ids"] == []
    assert event["event_type"] == "unknown_overlap"
    assert "多人" not in event["description"]["zh_tw"]
    assert manager.db.connection.execute("SELECT operation FROM speaker_audit WHERE operation='merge'").fetchone()[0] == "merge"
    assert [s["speaker_id"] for s in manager.list_speakers(sid)] == [one]
    assert manager.next_speaker_number(sid) == 3
    assert manager.add_speaker(sid, 500) == "speaker_003"
    db.close()


def test_manual_assignment_overrides_automatic_and_allows_future_split(tmp_path):
    db, manager, sid, _ = setup(tmp_path)
    one = manager.add_speaker(sid, 0)
    two = manager.add_speaker(sid, 0)
    manager.append_final(sid, segment("s1"))
    manager.append_final(sid, segment("s2", start=1000, end=1800))
    assert manager.assign_segment_speaker(sid, "s1", one)
    assert manager.assign_segment_speaker(sid, "s2", two)
    assert not manager.update_automatic_assignment(sid, "s1", two, 0.98)
    assert [s["speaker_id"] for s in manager.list_segments(sid)] == [one, two]
    db.close()


def test_dominant_interval_and_ambiguous_change(tmp_path):
    backend = SherpaOnnxDiarizationBackend(tmp_path)
    backend._observations.extend([
        SpeakerObservation(0, 700, "speaker_001", 0.9),
        SpeakerObservation(700, 1000, "speaker_002", 0.9),
    ])
    assert backend.get_speaker_for_interval(0, 900).speaker_id == "speaker_001"
    assert backend.get_speaker_for_interval(400, 1000).speaker_id is None


def test_uncertain_overlap_event_never_invents_speaker_or_cause(tmp_path):
    db, manager, sid, folder = setup(tmp_path)
    backend = SherpaOnnxDiarizationBackend(tmp_path)
    backend._observations.append(SpeakerObservation(100, 600, None, 0.4, True))
    decision = backend.get_speaker_for_interval(100, 600)
    assert decision.overlapping and decision.speaker_id is None
    assert manager.append_overlap_event(sid, 100, 600, [], "unknown_overlap", 0.4)
    event = manager.list_segments(sid)[0]
    assert event["speaker_ids"] == [] and event["event_type"] == "unknown_overlap"
    assert "原因" not in event["description"]["zh_tw"]
    assert "多人" not in event["description"]["zh_tw"]
    assert "【重疊】" in (folder / "exports" / "transcript.md").read_text(encoding="utf-8")
    assert not manager.append_overlap_event(sid, 100, 600, [], "unknown_overlap", 0.4)
    db.close()


def test_multi_speaker_events_keep_transcript_order(tmp_path):
    db, manager, sid, folder = setup(tmp_path)
    manager.append_final(sid, segment("late", start=900, end=1400))
    manager.append_overlap_event(sid, 400, 700, [], "unknown_overlap", 0.4)
    manager.append_final(sid, segment("early", start=100, end=500))
    starts = [item["start_ms"] for item in manager.list_segments(sid)]
    assert starts == [100, 400, 900]
    assert [item["start_ms"] for item in json.loads(
        (folder / "transcript.json").read_text(encoding="utf-8"))["segments"]] == starts
    db.close()


@pytest.mark.parametrize("texts,expected", [
    (("[笑い]", "[laughter]"), "laughter"),
    (("えっ！", "wow!"), "collective_reaction"),
    (("こんにちは", "wow!"), "overlapping_speech"),
])
def test_overlap_event_classification_requires_two_explicit_voices(tmp_path, texts, expected):
    db, manager, sid, _ = setup(tmp_path)
    one = manager.add_speaker(sid, 0)
    two = manager.add_speaker(sid, 0)
    manager.append_overlap_event(sid, 200, 500, [one, two], "overlapping_speech", 0.7)
    for index, (speaker, text) in enumerate(zip((one, two), texts), 1):
        item = segment(f"s{index}", speaker, 100, 600)
        item["speaker_confidence"] = 0.9
        item["original"] = text
        manager.append_final(sid, item)
    event = next(item for item in manager.list_segments(sid) if item["type"] == "multi_speaker_event")
    assert event["event_type"] == expected
    if expected == "overlapping_speech":
        assert "大笑" not in event["description"]["zh_tw"]
    db.close()


def test_transcript_uses_diarization_but_unknown_on_failure(tmp_path):
    db, manager, sid, _ = setup(tmp_path)
    manager.register_speaker(sid, "speaker_001", 0)
    requested = []
    def speaker(start, end):
        requested.append((start, end))
        return SpeakerDecision("speaker_001", 0.91)
    coordinator = TranscriptCoordinator(manager, sid, offset_ms=5000, speaker_for_interval=speaker)
    coordinator.apply_final(Recognition("a", "こんにちは", "ja", 100, 800, True))
    assert requested == [(100, 800)]
    assert manager.list_segments(sid)[0]["start_ms"] == 5100
    assert manager.list_segments(sid)[0]["speaker_confidence"] == 0.91
    broken = TranscriptCoordinator(manager, sid, speaker_for_interval=lambda *_: 1 / 0)
    broken.apply_final(Recognition("b", "続けます", "ja", 900, 1500, True))
    assert next(item for item in manager.list_segments(sid) if item["id"] == "segment_b")["speaker_id"] == "unknown"
    db.close()


def test_bounded_pcm_queue_and_observations(tmp_path):
    backend = SherpaOnnxDiarizationBackend(tmp_path)
    chunk = AudioChunk(bytes(640), 16000, 1, 0)
    for _ in range(1000):
        backend.push_audio(chunk)
    assert backend._queue.qsize() <= 256
    assert backend.dropped_chunks > 0
    backend.push_audio(AudioChunk(bytes(10 * 1024 * 1024), 16000, 1, 1001))
    assert max(len(item.pcm) for item in list(backend._queue.queue)) <= backend.MAX_CHUNK_BYTES
    for i in range(1000):
        backend._observations.append(SpeakerObservation(i, i + 1, "speaker_001", 0.8))
    assert len(backend._observations) == 180


def test_speaker_colors_are_deterministic(tmp_path):
    from vlt.settings.manager import SettingsManager
    from vlt.ui.controller import StudioController
    from PySide6.QtCore import QCoreApplication
    QCoreApplication.instance() or QCoreApplication([])
    db, manager, sid, _ = setup(tmp_path)
    class Audio:
        state = "idle"
        peak = 0
        async def list_sources(self): return []
    controller = StudioController(manager, SettingsManager(tmp_path), lambda: None,
                                  audio=Audio(), translation_backend_factory=lambda: None)
    controller._selected_id = sid
    controller._refresh_speakers()
    first = controller._decorate_segment({"speaker_id": "speaker_003"})["speaker_color"]
    assert first == controller._decorate_segment({"speaker_id": "speaker_003"})["speaker_color"]
    controller.shutdown()
    db.close()


def test_live_transcript_view_is_bounded_and_can_load_older_segments(tmp_path):
    from vlt.settings.manager import SettingsManager
    from vlt.ui.controller import StudioController
    from PySide6.QtCore import QCoreApplication
    QCoreApplication.instance() or QCoreApplication([])
    db, manager, sid, _ = setup(tmp_path)
    class Audio:
        state = "idle"
        peak = 0
        async def list_sources(self): return []
    controller = StudioController(manager, SettingsManager(tmp_path), lambda: None,
                                  audio=Audio(), translation_backend_factory=lambda: None)
    controller._selected_id = sid
    controller._transcript = TranscriptCoordinator(manager, sid)
    controller._transcript.finals = [{"id": str(i), "speaker_id": "unknown"} for i in range(250)]
    assert len(controller.transcriptSegments) == 120
    assert controller.transcriptSegments[0]["id"] == "130"
    assert controller.earlierSegmentCount == 130
    controller.loadEarlierSegments()
    assert len(controller.transcriptSegments) == 240
    assert controller.earlierSegmentCount == 10
    controller.shutdown()
    db.close()


def test_updated_embeddings_are_bounded_and_resume_with_session(tmp_path):
    from vlt.settings.manager import SettingsManager
    from vlt.ui.controller import StudioController
    from PySide6.QtCore import QCoreApplication
    QCoreApplication.instance() or QCoreApplication([])
    db, manager, sid, _ = setup(tmp_path)
    speaker = manager.add_speaker(sid, 100, [1.0, 0.0])

    class Audio:
        state = "idle"
        peak = 0
        async def list_sources(self): return []

    class Diarization:
        def get_representations(self, _speaker):
            return [[1.0, 0.0], [0.9, 0.1], [0.8, 0.2]]

    controller = StudioController(manager, SettingsManager(tmp_path), lambda: None,
                                  audio=Audio(), translation_backend_factory=lambda: None)
    controller._selected_id = sid
    controller._transcript = TranscriptCoordinator(manager, sid)
    controller._diarization = Diarization()
    controller._on_diarization_updated()
    controller._on_diarization_updated()
    assert len(manager.list_embeddings(sid)[speaker]) == 3
    manager.mark_interrupted()
    assert len(manager.list_embeddings(sid)[speaker]) == 3
    controller._diarization = None
    controller.shutdown()
    db.close()


def test_new_voice_badge_expires_without_changing_speaker_id(tmp_path):
    import time
    from vlt.settings.manager import SettingsManager
    from vlt.ui.controller import StudioController
    from PySide6.QtCore import QCoreApplication
    QCoreApplication.instance() or QCoreApplication([])
    db, manager, sid, _ = setup(tmp_path)

    class Audio:
        state = "idle"
        peak = 0
        async def list_sources(self): return []

    class Diarization:
        def joined_ms(self, _speaker): return 100
        def get_representation(self, _speaker): return [1.0, 0.0]

    controller = StudioController(manager, SettingsManager(tmp_path), lambda: None,
                                  audio=Audio(), translation_backend_factory=lambda: None)
    controller._selected_id = sid
    controller._transcript = TranscriptCoordinator(manager, sid)
    controller._diarization = Diarization()
    controller._on_diarization_new("speaker_001")
    decorated = controller._decorate_segment({"speaker_id": "speaker_001"})
    assert decorated["speaker_new"]
    assert decorated["speaker_display_name"] == "Speaker 1"
    controller._speaker_new_until["speaker_001"] = time.monotonic() - 1
    controller._poll_audio()
    assert "speaker_001" not in controller._speaker_new_until
    assert not controller._decorate_segment({"speaker_id": "speaker_001"})["speaker_new"]
    assert manager.list_speakers(sid)[0]["speaker_id"] == "speaker_001"
    controller._diarization = None
    controller.shutdown()
    db.close()


def test_partial_translation_never_uses_7b_fallback(monkeypatch):
    backend = OllamaTranslationBackend()
    calls = []
    def generate(_prompt, model):
        calls.append(model)
        return "確定去。"
    monkeypatch.setattr(backend, "_generate", generate)
    request = TranslationRequest("x", "たぶん行く", "ja", "zh-TW", "natural", final=False)
    with pytest.raises(RuntimeError):
        backend.translate_partial(request)
    assert calls == ["qwen2.5:1.5b"]


def test_diarization_observer_failure_does_not_block_asr():
    received = []

    class Audio:
        state = "capturing"
        async def audio_stream(self):
            yield AudioChunk(bytes(640), 16000, 1, 1000)
            self.state = "idle"

    class Backend:
        def set_language(self, language): pass
        def set_callbacks(self, partial, final, status): pass
        def get_status(self): return "live"
        async def start(self): pass
        async def stop(self): pass
        async def push_audio(self, chunk): received.append(chunk)

    def broken_diarization(_chunk):
        raise RuntimeError("speaker model failed")

    pipeline = ASRPipeline(Audio(), Backend, "ja", lambda _r: None, lambda _r: None,
                           lambda *_: None, on_audio_chunk=broken_diarization)
    asyncio.run(pipeline.run())
    assert len(received) == 1
