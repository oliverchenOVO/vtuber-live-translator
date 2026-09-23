"""In-memory partial state and idempotent final transcript persistence."""

from __future__ import annotations

import time
import logging
from collections.abc import Callable

from vlt.asr.base import Recognition
from vlt.diarization.base import SpeakerDecision
from vlt.sessions.manager import SessionManager


class TranscriptCoordinator:
    def __init__(self, sessions: SessionManager, session_id: str, offset_ms: int = 0,
                 speaker_for_interval: Callable[[int, int], SpeakerDecision] | None = None,
                 initial_limit: int | None = None):
        self.sessions = sessions
        self.session_id = session_id
        self.offset_ms = max(0, offset_ms)
        self.total_final_count = sessions.segment_count(session_id)
        self._live_limit = initial_limit
        self._page_offset = 0
        if initial_limit is None:
            self.finals = sessions.list_segments(session_id)
        else:
            self._page_offset = max(0, self.total_final_count - max(1, initial_limit))
            self.finals = sessions.list_segments_page(
                session_id, self._page_offset, max(1, initial_limit))
        self._seen = {item["id"] for item in self.finals[-512:]}
        self.live: dict | None = None
        self.partial_latency_ms: float | None = None
        self.final_latency_ms: float | None = None
        self._partial_measured: set[str] = set()
        self.speaker_for_interval = speaker_for_interval

    def _segment(self, result: Recognition) -> dict:
        start = max(0, self.offset_ms + result.start_ms)
        end = max(start + 1, self.offset_ms + result.end_ms)
        segment = {
            "id": f"segment_{result.utterance_id}",
            "type": "speech",
            "start_ms": start,
            "end_ms": end,
            "language": result.language,
            "speaker_id": "unknown",
            "original": result.text,
            "asr_state": "final" if result.is_final else "partial",
        }
        if self.speaker_for_interval:
            try:
                decision = self.speaker_for_interval(result.start_ms, result.end_ms)
                segment.update(speaker_id=decision.speaker_id or "unknown",
                               speaker_confidence=round(decision.confidence, 3),
                               speaker_assignment="automatic",
                               speaker_overlap=decision.overlapping)
            except Exception:
                segment.update(speaker_confidence=0.0, speaker_assignment="automatic")
        else:
            segment["speaker_id"] = "speaker_001"
        if result.is_final:
            segment["translation_state"] = "pending"
            segment["translation_status"] = "pending"
        return segment

    @property
    def earlier_count(self) -> int:
        return self._page_offset

    def load_earlier(self, count: int = 120) -> int:
        if self._page_offset <= 0:
            return 0
        offset = max(0, self._page_offset - max(1, count))
        earlier = self.sessions.list_segments_page(
            self.session_id, offset, self._page_offset - offset)
        self.finals = earlier + self.finals
        loaded = self._page_offset - offset
        self._page_offset = offset
        return loaded

    def reload_loaded(self) -> None:
        self.total_final_count = self.sessions.segment_count(self.session_id)
        loaded = max(1, len(self.finals))
        self._page_offset = max(0, self.total_final_count - loaded)
        self.finals = self.sessions.list_segments_page(
            self.session_id, self._page_offset, loaded)
        self._seen = {item["id"] for item in self.finals[-512:]}

    def _already_final(self, segment_id: str) -> bool:
        return segment_id in self._seen or bool(self.sessions.db.connection.execute(
            "SELECT 1 FROM segments WHERE session_id=? AND segment_id=?",
            (self.session_id, segment_id)).fetchone())

    def _remember_final(self, segment_id: str) -> None:
        if len(self._seen) >= 512:
            self._seen.pop()
        self._seen.add(segment_id)

    def apply_partial_translation(self, segment_id: str, original: str, translation: dict) -> bool:
        if not self.live or self.live["id"] != segment_id or self.live["original"] != original:
            return False
        self.live["translation"] = translation
        return True

    def apply_final_translation(self, segment_id: str, translation: dict) -> bool:
        changed = self.sessions.update_final_translation(self.session_id, segment_id, translation)
        if changed:
            for item in self.finals:
                if item["id"] == segment_id:
                    item["translation"] = translation
                    item["translation_state"] = "final"
                    break
        return changed

    def apply_partial(self, result: Recognition) -> bool:
        if result.is_final:
            raise ValueError("Expected partial recognition")
        segment = self._segment(result)
        if self._already_final(segment["id"]):
            return False
        if self.live and self.live["id"] == segment["id"] and self.live["original"] == segment["original"]:
            segment["translation"] = self.live.get("translation")
        self.live = segment  # Replace the same LIVE entry, never append partials.
        if result.first_audio_at is not None and result.utterance_id not in self._partial_measured:
            if len(self._partial_measured) >= 128:
                self._partial_measured.clear()
            self._partial_measured.add(result.utterance_id)
            measured = max(0, (time.monotonic() - result.first_audio_at) * 1000)
            logging.info("ASR latency: kind=first_partial ms=%.1f", measured)
            self.partial_latency_ms = measured if self.partial_latency_ms is None else (0.7 * self.partial_latency_ms + 0.3 * measured)
        return True

    def apply_final(self, result: Recognition) -> bool:
        if not result.is_final:
            raise ValueError("Expected final recognition")
        segment = self._segment(result)
        self._partial_measured.discard(result.utterance_id)
        if self._already_final(segment["id"]):
            return False
        if not result.text.strip():
            self._remember_final(segment["id"])
            if self.live and self.live["id"] == segment["id"]:
                self.live = None
            return False
        inserted = self.sessions.append_final(self.session_id, segment)
        self._remember_final(segment["id"])
        if self.live and self.live["id"] == segment["id"]:
            self.live = None
        if inserted:
            self.finals.append(segment)
            self.total_final_count += 1
            self.finals.sort(key=lambda item: (item["start_ms"], item["end_ms"], item["id"]))
            if self._live_limit and len(self.finals) > self._live_limit:
                removed = len(self.finals) - self._live_limit
                self.finals = self.finals[removed:]
                self._page_offset += removed
            if result.speech_end_at is not None:
                measured = max(0, (time.monotonic() - result.speech_end_at) * 1000)
                logging.info("ASR latency: kind=final ms=%.1f", measured)
                self.final_latency_ms = measured if self.final_latency_ms is None else (0.7 * self.final_latency_ms + 0.3 * measured)
        return inserted

    def finalize_live(self) -> dict | None:
        """Persist a non-empty last partial during an orderly Session finalization."""
        if not self.live or self.live["id"] in self._seen or not self.live.get("original", "").strip():
            self.live = None
            return None
        segment = {key: value for key, value in self.live.items() if key != "translation"}
        segment.update(asr_state="final", translation_state="pending", translation_status="pending")
        if not self.sessions.append_final(self.session_id, segment):
            self.live = None
            return None
        self._remember_final(segment["id"])
        self.finals.append(segment)
        self.total_final_count += 1
        self.finals.sort(key=lambda item: (item["start_ms"], item["end_ms"], item["id"]))
        self.live = None
        return segment
