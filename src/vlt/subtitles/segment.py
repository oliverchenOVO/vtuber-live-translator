"""Persisted transcript record types."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Segment:
    id: str
    start_ms: int
    end_ms: int
    speaker_id: str | None
    original: str
    translation: str
    style: str

