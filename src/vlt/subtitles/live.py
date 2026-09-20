"""In-memory partial state and idempotent final transcript persistence."""

from __future__ import annotations

import time

from vlt.asr.base import Recognition
from vlt.sessions.manager import SessionManager


class TranscriptCoordinator:
    def __init__(self, sessions: SessionManager, session_id: str, offset_ms: int = 0):
        self.sessions = sessions
        self.session_id = session_id
        self.offset_ms = max(0, offset_ms)
        self.finals = sessions.list_segments(session_id)
        self._seen = {item["id"] for item in self.finals}
        self.live: dict | None = None
        self.partial_latency_ms: float | None = None
        self.final_latency_ms: float | None = None
        self._partial_measured: set[str] = set()

    def _segment(self, result: Recognition) -> dict:
        start = max(0, self.offset_ms + result.start_ms)
        end = max(start + 1, self.offset_ms + result.end_ms)
        return {
            "id": f"segment_{result.utterance_id}",
            "type": "speech",
            "start_ms": start,
            "end_ms": end,
            "language": result.language,
            "speaker_id": "speaker_001",
            "original": result.text,
            "asr_state": "final" if result.is_final else "partial",
        }

    def apply_partial(self, result: Recognition) -> bool:
        if result.is_final:
            raise ValueError("Expected partial recognition")
        segment = self._segment(result)
        if segment["id"] in self._seen:
            return False
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
