import asyncio
import json
from pathlib import Path

from vlt.asr.base import Recognition
from vlt.asr.faster_whisper_backend import FasterWhisperBackend
from vlt.asr.pipeline import ASRPipeline
from vlt.asr.queue import BoundedAudioQueue
from vlt.audio.base import AudioChunk
from vlt.database.database import Database
from vlt.sessions.manager import SessionManager
from vlt.subtitles.live import TranscriptCoordinator


def fixture_session(tmp_path: Path):
    database = Database(tmp_path / "app.db")
    manager = SessionManager(tmp_path, database)
    session = manager.create(source_language="auto")
    return database, manager, session


def recognition(uid="one", text="昨日は本当に寝れなくて", language="ja", *, final=False,
                start=100, end=1300):
    return Recognition(uid, text, language, start, end, final)


def test_partial_updates_one_live_entry(tmp_path):
    db, manager, session = fixture_session(tmp_path)
    transcript = TranscriptCoordinator(manager, session["session_id"])
    transcript.apply_partial(recognition(text="昨日は"))
    first_id = transcript.live["id"]
    transcript.apply_partial(recognition(text="昨日は本当に"))
    assert transcript.live["id"] == first_id
    assert transcript.live["original"] == "昨日は本当に"
    assert transcript.finals == []
    assert manager.list_segments(session["session_id"]) == []
    db.close()


def test_final_once_with_ordered_session_timestamps_and_immediate_persistence(tmp_path):
    db, manager, session = fixture_session(tmp_path)
    transcript = TranscriptCoordinator(manager, session["session_id"], offset_ms=5000)
    transcript.apply_partial(recognition())
    assert transcript.apply_final(recognition(final=True))
    assert not transcript.apply_final(recognition(final=True))
    assert transcript.live is None
    assert len(transcript.finals) == 1
    segment = transcript.finals[0]
    assert (segment["start_ms"], segment["end_ms"]) == (5100, 6300)
    assert segment["asr_state"] == "final"
    assert segment["language"] == "ja"
    path = Path(session["folder_path"]) / "transcript.json"
    assert json.loads(path.read_text(encoding="utf-8"))["segments"] == [segment]
    assert manager.list_segments(session["session_id"]) == [segment]
    db.close()


def test_resume_reconciles_transcript_without_new_session(tmp_path):
    db, manager, session = fixture_session(tmp_path)
    transcript = TranscriptCoordinator(manager, session["session_id"])
    transcript.apply_final(recognition(final=True))
    path = Path(session["folder_path"]) / "transcript.json"
    path.unlink()  # Simulate a crash after SQLite commit and before JSON render.
    manager.mark_interrupted()
    resumed = manager.resume(session["session_id"])
    assert resumed["folder_path"] == session["folder_path"]
    assert resumed["status"] == "active"
    assert len(TranscriptCoordinator(manager, session["session_id"]).finals) == 1
    assert len(json.loads(path.read_text(encoding="utf-8"))["segments"]) == 1
    assert len(manager.list_sessions()) == 1
    db.close()


def test_japanese_and_english_text_flow(tmp_path):
    db, manager, session = fixture_session(tmp_path)
    transcript = TranscriptCoordinator(manager, session["session_id"])
    transcript.apply_final(recognition("ja-turn", "昨日は本当に寝れなくて", "ja", final=True))
    transcript.apply_final(recognition("en-turn", "I could not sleep yesterday", "en",
                                       final=True, start=1400, end=2600))
    assert [(item["language"], item["original"]) for item in transcript.finals] == [
        ("ja", "昨日は本当に寝れなくて"), ("en", "I could not sleep yesterday")]
    assert transcript.finals[0]["end_ms"] < transcript.finals[1]["start_ms"]
    db.close()


def test_final_segments_persist_before_session_ends(tmp_path):
    db, manager, session = fixture_session(tmp_path)
    transcript = TranscriptCoordinator(manager, session["session_id"])
    transcript.apply_final(recognition("immediate", "今話しています", "ja", final=True))
    assert manager.get(session["session_id"])["status"] == "active"
    assert manager.list_segments(session["session_id"])[0]["original"] == "今話しています"
    path = Path(session["folder_path"]) / "transcript.json"
    assert json.loads(path.read_text(encoding="utf-8"))["segments"][0]["original"] == "今話しています"
    db.close()


def test_timestamp_ordering_after_session_resume(tmp_path):
    db, manager, session = fixture_session(tmp_path)
    first = TranscriptCoordinator(manager, session["session_id"], offset_ms=500)
    first.apply_final(recognition("first", "First", "en", final=True))
    manager.mark_interrupted()
    manager.resume(session["session_id"])
    second = TranscriptCoordinator(manager, session["session_id"], offset_ms=3000)
    second.apply_final(recognition("second", "Second", "en", final=True))
    segments = manager.list_segments(session["session_id"])
    assert segments[0]["end_ms"] < segments[1]["start_ms"]
    db.close()


def test_english_final_text_is_saved_as_original(tmp_path):
    db, manager, session = fixture_session(tmp_path)
    transcript = TranscriptCoordinator(manager, session["session_id"])
    transcript.apply_partial(recognition("english", "I was", "en"))
    transcript.apply_final(recognition("english", "I was watching the stream.", "en", final=True))
    assert transcript.live is None
    assert transcript.finals[0]["original"] == "I was watching the stream."
    assert transcript.finals[0]["language"] == "en"
    db.close()


def test_asr_queue_is_bounded_and_drops_oldest():
    queue = BoundedAudioQueue(max_bytes=64)
    for number in range(1000):
        queue.push(AudioChunk(bytes([number % 256]) * 16, 16000, 1, number))
    assert queue.size_bytes == 64
    assert queue.dropped_bytes == 996 * 16
    assert [asyncio.run(queue.pop()).timestamp_ms for _ in range(4)] == [996, 997, 998, 999]


def test_reconnect_keeps_one_session_and_does_not_replay_final(tmp_path):
    db, manager, session = fixture_session(tmp_path)
    transcript = TranscriptCoordinator(manager, session["session_id"])

    class Audio:
        state = "capturing"
        calls = 0
        async def audio_stream(self):
            self.calls += 1
            for number in range(2):
                yield AudioChunk(b"\0" * 640, 16000, 1, number)
            if self.calls >= 2:
                self.state = "idle"

    class Backend:
        instances = 0
        def __init__(self):
            Backend.instances += 1
            self.number = Backend.instances
            self.status = "idle"
        def set_language(self, language): self.language = language
        def set_callbacks(self, partial, final, status): self.final = final
        def get_status(self): return self.status
        async def start(self): self.status = "live"
        async def stop(self): self.status = "idle"
        async def push_audio(self, chunk):
            self.final(recognition("fixed-id", final=True))
            if self.number == 1:
                self.status = "error"

    audio = Audio()
    pipeline = ASRPipeline(audio, Backend, "auto", lambda _: None,
                           transcript.apply_final, lambda *_: None)
    asyncio.run(pipeline.run())
    assert pipeline.reconnects == 1
    assert len(manager.list_segments(session["session_id"])) == 1
    assert len(manager.list_sessions()) == 1
    db.close()


def test_local_streaming_backend_emits_partial_and_final_with_detected_language():
    class Model:
        def __init__(self, *_args, **_kwargs): pass
        def transcribe(self, _samples, **_kwargs):
            return [type("Segment", (), {"text": "こんにちは"})()], type("Info", (), {"language": "ja"})()

    class Vad:
        calls = 0
        def is_speech(self, _frame, _sample_rate):
            self.calls += 1
            return self.calls <= 75

    async def exercise():
        backend = FasterWhisperBackend(model_factory=Model)
        backend._vad = Vad()
        backend.set_language("auto")
        partials, finals = [], []
        backend.set_callbacks(partials.append, finals.append, lambda *_: None)
        await backend.start()
        await backend.push_audio(AudioChunk(b"\0" * 640 * 65, 16000, 1, 0))
        await asyncio.sleep(0.05)
        await backend.push_audio(AudioChunk(b"\0" * 640 * 40, 16000, 1, 1300))
        await asyncio.sleep(0.1)
        await backend.stop()
        return partials, finals

    partials, finals = asyncio.run(exercise())
    assert partials and len(finals) == 1
    assert partials[0].utterance_id == finals[0].utterance_id
    assert finals[0].language == "ja"
    assert finals[0].text == "こんにちは"
    assert finals[0].start_ms < finals[0].end_ms


def test_silent_process_loopback_gap_finalizes_existing_speech():
    class Model:
        def __init__(self, *_args, **_kwargs): pass
        def transcribe(self, _samples, **_kwargs):
            return [type("Segment", (), {"text": "こんにちは"})()], type("Info", (), {"language": "ja"})()

    class Vad:
        def is_speech(self, *_args): return True

    async def exercise():
        backend = FasterWhisperBackend(model_factory=Model)
        backend._vad = Vad()
        finals = []
        backend.set_callbacks(lambda _result: None, finals.append, lambda *_: None)
        await backend.start()
        await backend.push_audio(AudioChunk(bytes(640 * 45), 16000, 1, 1000))
        await asyncio.sleep(0.05)
        await backend.push_audio(AudioChunk(bytes(640), 16000, 1, 2800))
        await asyncio.sleep(0.1)
        await backend.stop()
        return finals, backend.gap_finalizations

    finals, gaps = asyncio.run(exercise())
    assert gaps == 1
    assert len(finals) >= 1 and finals[0].text == "こんにちは"
