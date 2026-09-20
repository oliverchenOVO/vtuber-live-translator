from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from vlt.database.database import Database


def _atomic_json(path: Path, data: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


class SessionManager:
    def __init__(self, root: Path, database: Database):
        self.root = root / "sessions"
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = database

    def create(self, title: str = "未命名直播", *, source_language: str = "ja",
               target_language: str = "zh-TW", translation_style: str = "natural") -> dict:
        now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        session_id = str(uuid.uuid4())
        safe_title = re.sub(r"[^\w\u3040-\u30ff\u3400-\u9fff-]+", "_", title).strip("_")[:40] or "Session"
        folder = self.root / f"{stamp}_{safe_title}_{session_id[:8]}"
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "exports").mkdir()
        session = {
            "session_id": session_id, "folder_path": str(folder), "title": title,
            "created_at": now, "updated_at": now, "ended_at": None,
            "status": "active", "source_language": source_language,
            "target_language": target_language, "translation_style": translation_style,
            "audio_source": None, "save_audio": False,
        }
        try:
            with self.db.connection:
                self.db.connection.execute("""INSERT INTO sessions
                    (session_id, folder_path, title, created_at, updated_at, ended_at, status,
                     source_language, target_language, translation_style, audio_source, save_audio)
                    VALUES (:session_id, :folder_path, :title, :created_at, :updated_at, :ended_at,
                            :status, :source_language, :target_language, :translation_style,
                            :audio_source, :save_audio)""", session)
            _atomic_json(folder / "session.json", session)
            _atomic_json(folder / "transcript.json", {"session_id": session_id, "speakers": [], "segments": []})
        except Exception:
            # Keep the folder for diagnosis; the UUID prevents a duplicate on retry.
            raise
        return session

    def list_sessions(self) -> list[dict]:
        rows = self.db.connection.execute("SELECT * FROM sessions ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]

    def get(self, session_id: str) -> dict | None:
        row = self.db.connection.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        return dict(row) if row else None

    def resume(self, session_id: str) -> dict:
        """Resume the same identity and folder after an interrupted run."""
        session = self.get(session_id)
        if session is None:
            raise KeyError(session_id)
        if session["status"] == "completed":
            raise ValueError("已完成的 Session 無法繼續；請建立新 Session。")
        if session["status"] == "interrupted":
            now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
            with self.db.connection:
                self.db.connection.execute(
                    "UPDATE sessions SET status='active', updated_at=? WHERE session_id=?", (now, session_id))
            session.update(status="active", updated_at=now)
            _atomic_json(Path(session["folder_path"]) / "session.json", session)
        self.reconcile_transcript(session_id)
        return session

    def list_segments(self, session_id: str) -> list[dict]:
        rows = self.db.connection.execute(
            "SELECT payload_json FROM segments WHERE session_id=? ORDER BY start_ms, end_ms, segment_id",
            (session_id,),
        ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def reconcile_transcript(self, session_id: str) -> None:
        session = self.get(session_id)
        if session is None:
            raise KeyError(session_id)
        path = Path(session["folder_path"]) / "transcript.json"
        existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        segments = self.list_segments(session_id)
        speakers = [dict(row) for row in self.db.connection.execute(
            "SELECT speaker_id, display_name, joined_at_ms, left_at_ms, person_id "
            "FROM speakers WHERE session_id=? ORDER BY speaker_id", (session_id,)
        ).fetchall()]
        if existing.get("segments") != segments or existing.get("speakers") != speakers:
            _atomic_json(path, {"session_id": session_id,
                                "speakers": speakers, "segments": segments})

    def append_final(self, session_id: str, segment: dict) -> bool:
        """Persist each final to SQLite and atomically render transcript.json."""
        session = self.get(session_id)
        if session is None or session["status"] != "active":
            raise ValueError("必須先建立或恢復進行中的 Session。")
        if segment["type"] != "speech" or segment["asr_state"] != "final":
            raise ValueError("Only final speech segments are persisted")
        if segment["start_ms"] < 0 or segment["end_ms"] <= segment["start_ms"]:
            raise ValueError("Invalid segment timestamps")
        now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        payload = json.dumps(segment, ensure_ascii=False)
        with self.db.connection:
            if segment.get("speaker_id"):
                self.db.connection.execute("""INSERT OR IGNORE INTO speakers
                    (session_id, speaker_id, display_name, joined_at_ms)
                    VALUES (?, ?, ?, ?)""",
                    (session_id, segment["speaker_id"], "Speaker 1", segment["start_ms"]))
            cursor = self.db.connection.execute("""INSERT OR IGNORE INTO segments
                (session_id, segment_id, start_ms, end_ms, type, speaker_id,
                 original, translation, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, segment["id"], segment["start_ms"], segment["end_ms"],
                 "speech", segment.get("speaker_id"), segment["original"], None, payload))
            if cursor.rowcount:
                self.db.connection.execute("UPDATE sessions SET updated_at=? WHERE session_id=?",
                                           (now, session_id))
        self.reconcile_transcript(session_id)
        return bool(cursor.rowcount)

    def set_source_language(self, session_id: str, language: str) -> None:
        if language not in ("auto", "ja", "en"):
            raise ValueError(language)
        session = self.get(session_id)
        if session is None or session["status"] != "active":
            return
        session["source_language"] = language
        with self.db.connection:
            self.db.connection.execute(
                "UPDATE sessions SET source_language=? WHERE session_id=?", (language, session_id))
        _atomic_json(Path(session["folder_path"]) / "session.json", session)

    def finish(self, session_id: str) -> dict:
        session = self.get(session_id)
        if session is None:
            raise KeyError(session_id)
        if session["status"] != "active":
            return session
        now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        session.update(status="completed", updated_at=now, ended_at=now)
        with self.db.connection:
            self.db.connection.execute("UPDATE sessions SET status=?, updated_at=?, ended_at=? WHERE session_id=?",
                                       ("completed", now, now, session_id))
        _atomic_json(Path(session["folder_path"]) / "session.json", session)
        return session

    def mark_interrupted(self) -> int:
        rows = self.db.connection.execute("SELECT session_id, folder_path FROM sessions WHERE status='active'").fetchall()
        with self.db.connection:
            self.db.connection.execute("UPDATE sessions SET status='interrupted' WHERE status='active'")
        for row in rows:
            session = self.get(row["session_id"])
            _atomic_json(Path(row["folder_path"]) / "session.json", session)
        return len(rows)
