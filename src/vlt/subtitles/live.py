"""In-memory partial state and idempotent final transcript persistence."""

from __future__ import annotations

import time
from collections.abc import Callable

from vlt.asr.base import Recognition
from vlt.diarization.base import SpeakerDecision
from vlt.sessions.manager import SessionManager


class TranscriptCoordinator:
    def __init__(self, sessions: SessionManager, session_id: str, offset_ms: int = 0,
                 speaker_for_interval: Callable[[int, int], SpeakerDecision] | None = None):
        self.sessions = sessions
        self.session_id = session_id
        self.offset_ms = max(0, offset_ms)
        self.finals = sessions.list_segments(session_id)
        self._seen = {item["id"] for item in self.finals}
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
        return segment

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
        if segment["id"] in self._seen:
            return False
        if self.live and self.live["id"] == segment["id"] and self.live["original"] == segment["original"]:
            segment["translation"] = self.live.get("translation")
        self.live = segment  # Replace the same LIVE entry, never append partials.
        if result.first_audio_at is not None and result.utterance_id not in self._partial_measured:
            self._partial_measured.add(result.utterance_id)
            measured = max(0, (time.monotonic() - result.first_audio_at) * 1000)
            self.partial_latency_ms = measured if self.partial_latency_ms is None else (0.7 * self.partial_latency_ms + 0.3 * measured)
        return True

    def apply_final(self, result: Recognition) -> bool:
        if not result.is_final:
            raise ValueError("Expected final recognition")
        segment = self._segment(result)
        if segment["id"] in self._seen:
            return False
        if not result.text.strip():
            self._seen.add(segment["id"])
            if self.live and self.live["id"] == segment["id"]:
                self.live = None
            return False
        inserted = self.sessions.append_final(self.session_id, segment)
        self._seen.add(segment["id"])
        if self.live and self.live["id"] == segment["id"]:
            self.live = None
        if inserted:
            self.finals.append(segment)
            self.finals.sort(key=lambda item: (item["start_ms"], item["end_ms"], item["id"]))
            if result.speech_end_at is not None:
                measured = max(0, (time.monotonic() - result.speech_end_at) * 1000)
                self.final_latency_ms = measured if self.final_latency_ms is None else (0.7 * self.final_latency_ms + 0.3 * measured)
        return inserted
