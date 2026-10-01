from __future__ import annotations

import json
import html
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from vlt.database.database import Database
from vlt.version import __version__


def _atomic_json(path: Path, data: object) -> None:
    _atomic_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def _atomic_text(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)


def _subtitle_time(ms: int, separator: str) -> str:
    hours, remainder = divmod(max(0, ms), 3600000)
    minutes, remainder = divmod(remainder, 60000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{millis:03d}"


def _display_duration(ms: int) -> str:
    hours, remainder = divmod(max(0, ms), 3600000)
    minutes, seconds = divmod(remainder // 1000, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _language_name(code: str) -> str:
    return {"ja": "Japanese", "en": "English", "auto": "Auto",
            "zh-TW": "Traditional Chinese", "zh-CN": "Simplified Chinese"}.get(code, code)


APP_VERSION = __version__


class SessionManager:
    def __init__(self, root: Path, database: Database, session_root: Path | None = None):
        self.root = session_root or root / "sessions"
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
            "created_at": now, "started_at": now, "updated_at": now, "ended_at": None,
            "status": "active", "source_language": source_language,
            "target_language": target_language, "translation_style": translation_style,
            "audio_source": None, "source_process": None, "save_audio": False,
            "recording_enabled": False, "app_version": APP_VERSION,
        }
        try:
            with self.db.connection:
                self.db.connection.execute("""INSERT INTO sessions
                    (session_id, folder_path, title, created_at, updated_at, ended_at, status,
                     source_language, target_language, translation_style, audio_source, save_audio)
                    VALUES (:session_id, :folder_path, :title, :created_at, :updated_at, :ended_at,
                            :status, :source_language, :target_language, :translation_style,
                            :audio_source, :save_audio)""", session)
            self._write_session_json(session_id)
            _atomic_json(folder / "transcript.json", {"session_id": session_id, "speakers": [], "segments": []})
        except Exception:
            # Keep the folder for diagnosis; the UUID prevents a duplicate on retry.
            raise
        return session

    def list_sessions(self) -> list[dict]:
        rows = self.db.connection.execute(
            "SELECT s.*, COALESCE(MAX(g.end_ms),0) AS duration_ms, "
            "COUNT(DISTINCT p.speaker_id) AS speaker_count "
            "FROM sessions s LEFT JOIN segments g ON g.session_id=s.session_id "
            "LEFT JOIN speakers p ON p.session_id=s.session_id "
            "GROUP BY s.session_id ORDER BY s.created_at DESC").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["duration"] = _display_duration(item["duration_ms"])
            item["date"] = item["created_at"][:10]
            result.append(item)
        return result

    def get(self, session_id: str) -> dict | None:
        row = self.db.connection.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        return dict(row) if row else None

    def _session_metadata(self, session_id: str) -> dict:
        session = self.get(session_id)
        if session is None:
            raise KeyError(session_id)
        speakers = self.list_speakers(session_id)
        duration = self.db.connection.execute(
            "SELECT COALESCE(MAX(end_ms),0) FROM segments WHERE session_id=?", (session_id,)).fetchone()[0]
        return {**session,
                "started_at": session["created_at"],
                "source_process": session.get("audio_source"),
                "recording_enabled": bool(session.get("save_audio")),
                "audio_recording": "enabled" if session.get("save_audio") else "disabled",
                "speaker_mappings": speakers,
                "next_speaker_index": self.next_speaker_number(session_id),
                "duration_ms": duration,
                "app_version": APP_VERSION}

    def _write_session_json(self, session_id: str) -> None:
        session = self.get(session_id)
        if session is None:
            raise KeyError(session_id)
        _atomic_json(Path(session["folder_path"]) / "session.json", self._session_metadata(session_id))

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
            self._write_session_json(session_id)
        self.reconcile_transcript(session_id)
        return session

    def list_segments(self, session_id: str) -> list[dict]:
        rows = self.db.connection.execute(
            "SELECT payload_json FROM segments WHERE session_id=? ORDER BY start_ms, end_ms, segment_id",
            (session_id,),
        ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def segment_count(self, session_id: str) -> int:
        return int(self.db.connection.execute(
            "SELECT COUNT(*) FROM segments WHERE session_id=?", (session_id,)).fetchone()[0])

    def list_segments_page(self, session_id: str, offset: int, limit: int) -> list[dict]:
        rows = self.db.connection.execute(
            "SELECT payload_json FROM segments WHERE session_id=? "
            "ORDER BY start_ms,end_ms,segment_id LIMIT ? OFFSET ?",
            (session_id, max(1, min(int(limit), 500)), max(0, int(offset))),
        ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def segment_ids(self, session_id: str) -> set[str]:
        return {row["segment_id"] for row in self.db.connection.execute(
            "SELECT segment_id FROM segments WHERE session_id=?", (session_id,))}

    def list_speakers(self, session_id: str) -> list[dict]:
        rows = self.db.connection.execute(
            "SELECT s.speaker_id, s.display_name, s.joined_at_ms, s.left_at_ms, s.person_id, "
            "COUNT(g.segment_id) AS segment_count FROM speakers s LEFT JOIN segments g "
            "ON g.session_id=s.session_id AND g.speaker_id=s.speaker_id "
            "WHERE s.session_id=? GROUP BY s.speaker_id ORDER BY s.speaker_id", (session_id,)).fetchall()
        return [dict(row) for row in rows]

    def list_embeddings(self, session_id: str) -> dict[str, list[list[float]]]:
        result: dict[str, list[list[float]]] = {}
        for row in self.db.connection.execute(
                "SELECT speaker_id,vector_json FROM speaker_embeddings WHERE session_id=? "
                "ORDER BY speaker_id,sample_index", (session_id,)):
            result.setdefault(row["speaker_id"], []).append(json.loads(row["vector_json"]))
        return result

    def next_speaker_number(self, session_id: str) -> int:
        row = self.db.connection.execute("SELECT next_number FROM speaker_sequence WHERE session_id=?",
                                         (session_id,)).fetchone()
        if row:
            return row["next_number"]
        return max((int(s["speaker_id"].split("_")[-1]) for s in self.list_speakers(session_id)
                    if re.fullmatch(r"speaker_\d+", s["speaker_id"])), default=0) + 1

    def add_speaker(self, session_id: str, joined_at_ms: int, embedding: list[float] | None = None) -> str:
        number = self.next_speaker_number(session_id)
        speaker_id = f"speaker_{number:03d}"
        with self.db.connection:
            self.db.connection.execute(
                "INSERT INTO speakers(session_id,speaker_id,display_name,joined_at_ms) VALUES(?,?,?,?)",
                (session_id, speaker_id, f"Speaker {number}", joined_at_ms))
            self.db.connection.execute("INSERT INTO speaker_sequence(session_id,next_number) VALUES(?,?) "
                                       "ON CONFLICT(session_id) DO UPDATE SET next_number=excluded.next_number",
                                       (session_id, number + 1))
            if embedding:
                self.db.connection.execute(
                    "INSERT INTO speaker_embeddings VALUES(?,?,0,?)",
                    (session_id, speaker_id, json.dumps(embedding)))
        self.reconcile_transcript(session_id)
        self._write_session_json(session_id)
        return speaker_id

    def register_speaker(self, session_id: str, speaker_id: str, joined_at_ms: int,
                         embedding: list[float] | None = None) -> bool:
        if not re.fullmatch(r"speaker_\d{3,}", speaker_id):
            raise ValueError(speaker_id)
        number = int(speaker_id.split("_")[-1])
        with self.db.connection:
            cursor = self.db.connection.execute(
                "INSERT OR IGNORE INTO speakers(session_id,speaker_id,display_name,joined_at_ms) "
                "VALUES(?,?,?,?)", (session_id, speaker_id, f"Speaker {number}", joined_at_ms))
            self.db.connection.execute("INSERT INTO speaker_sequence(session_id,next_number) VALUES(?,?) "
                "ON CONFLICT(session_id) DO UPDATE SET next_number=MAX(next_number,excluded.next_number)",
                (session_id, number + 1))
            if embedding and cursor.rowcount:
                self.db.connection.execute("INSERT INTO speaker_embeddings VALUES(?,?,0,?)",
                                           (session_id, speaker_id, json.dumps(embedding)))
        if cursor.rowcount:
            self.reconcile_transcript(session_id)
            self._write_session_json(session_id)
        return bool(cursor.rowcount)

    def add_embedding(self, session_id: str, speaker_id: str, vector: list[float]) -> None:
        """Keep at most three representative vectors per session speaker."""
        with self.db.connection:
            rows = self.db.connection.execute(
                "SELECT sample_index FROM speaker_embeddings WHERE session_id=? AND speaker_id=? "
                "ORDER BY sample_index", (session_id, speaker_id)).fetchall()
            if len(rows) >= 3:
                return
            index = max((row["sample_index"] for row in rows), default=-1) + 1
            self.db.connection.execute("INSERT INTO speaker_embeddings VALUES(?,?,?,?)",
                                       (session_id, speaker_id, index, json.dumps(vector)))

    def update_speaker(self, session_id: str, speaker_id: str, *, display_name: str | None = None,
                       person_id: str | None = None) -> bool:
        fields = {}
        if display_name is not None:
            name = display_name.strip()[:80]
            if not name:
                raise ValueError("人物名稱不能留空。")
            fields["display_name"] = name
        if person_id is not None:
            fields["person_id"] = person_id.strip() or None
        if not fields:
            return False
        with self.db.connection:
            cursor = self.db.connection.execute(
                "UPDATE speakers SET " + ",".join(f"{key}=?" for key in fields) +
                " WHERE session_id=? AND speaker_id=?", (*fields.values(), session_id, speaker_id))
            if cursor.rowcount:
                self._audit(session_id, "update", {"speaker_id": speaker_id, **fields})
        if cursor.rowcount:
            self.reconcile_transcript(session_id)
            self.render_exports(session_id)
            self._write_session_json(session_id)
        return bool(cursor.rowcount)

    def assign_segment_speaker(self, session_id: str, segment_id: str, speaker_id: str) -> bool:
        row = self.db.connection.execute(
            "SELECT payload_json FROM segments WHERE session_id=? AND segment_id=?",
            (session_id, segment_id)).fetchone()
        if not row or (speaker_id != "unknown" and not self.db.connection.execute(
                "SELECT 1 FROM speakers WHERE session_id=? AND speaker_id=?",
                (session_id, speaker_id)).fetchone()):
            return False
        payload = json.loads(row["payload_json"])
        old_id = payload.get("speaker_id")
        payload.update(speaker_id=speaker_id, speaker_confidence=1.0, speaker_assignment="manual")
        with self.db.connection:
            self.db.connection.execute("UPDATE segments SET speaker_id=?,payload_json=? "
                                       "WHERE session_id=? AND segment_id=?",
                                       (speaker_id, json.dumps(payload, ensure_ascii=False), session_id, segment_id))
            self._audit(session_id, "manual_assignment", {"segment_id": segment_id,
                                                          "from": old_id, "to": speaker_id})
        self.reconcile_transcript(session_id)
        self.render_exports(session_id)
        return True

    def assign_unknown_range(self, session_id: str, start_ms: int, end_ms: int, speaker_id: str) -> int:
        if start_ms < 0 or end_ms <= start_ms:
            raise ValueError("結束時間必須晚於開始時間。")
        if not self.db.connection.execute("SELECT 1 FROM speakers WHERE session_id=? AND speaker_id=?",
                                          (session_id, speaker_id)).fetchone():
            raise ValueError("請選擇此 Session 的 Speaker。")
        rows = self.db.connection.execute(
            "SELECT segment_id,payload_json FROM segments WHERE session_id=? AND type='speech' "
            "AND (speaker_id IS NULL OR speaker_id='unknown') AND start_ms>=? AND start_ms<?",
            (session_id, start_ms, end_ms)).fetchall()
        with self.db.connection:
            for row in rows:
                payload = json.loads(row["payload_json"])
                payload.update(speaker_id=speaker_id, speaker_confidence=1.0, speaker_assignment="manual")
                self.db.connection.execute("UPDATE segments SET speaker_id=?,payload_json=? "
                    "WHERE session_id=? AND segment_id=?",
                    (speaker_id, json.dumps(payload, ensure_ascii=False), session_id, row["segment_id"]))
            self._audit(session_id, "assign_unknown_range", {"start_ms": start_ms, "end_ms": end_ms,
                                                           "speaker_id": speaker_id, "count": len(rows)})
        self.reconcile_transcript(session_id)
        self.render_exports(session_id)
        return len(rows)

    def update_automatic_assignment(self, session_id: str, segment_id: str,
                                    speaker_id: str, confidence: float) -> bool:
        row = self.db.connection.execute(
            "SELECT payload_json FROM segments WHERE session_id=? AND segment_id=?",
            (session_id, segment_id)).fetchone()
        if not row:
            return False
        payload = json.loads(row["payload_json"])
        if payload.get("speaker_assignment") == "manual" or payload.get("speaker_id") not in ("unknown", None):
            return False
        payload.update(speaker_id=speaker_id, speaker_confidence=round(confidence, 3),
                       speaker_assignment="automatic")
        with self.db.connection:
            self.db.connection.execute("UPDATE segments SET speaker_id=?,payload_json=? "
                                       "WHERE session_id=? AND segment_id=?",
                                       (speaker_id, json.dumps(payload, ensure_ascii=False), session_id, segment_id))
        self.reconcile_transcript(session_id)
        return True

    def merge_speakers(self, session_id: str, source_id: str, target_id: str) -> int:
        if source_id == target_id:
            return 0
        known = {s["speaker_id"] for s in self.list_speakers(session_id)}
        if source_id not in known or target_id not in known:
            raise ValueError("找不到指定的 Speaker。")
        rows = self.db.connection.execute(
            "SELECT segment_id,payload_json FROM segments WHERE session_id=? AND speaker_id=?",
            (session_id, source_id)).fetchall()
        source_vectors = self.list_embeddings(session_id).get(source_id, [])
        target_count = len(self.list_embeddings(session_id).get(target_id, []))
        event_rows = self.db.connection.execute(
            "SELECT segment_id,payload_json FROM segments WHERE session_id=? AND type='multi_speaker_event'",
            (session_id,)).fetchall()
        with self.db.connection:
            for row in rows:
                payload = json.loads(row["payload_json"])
                payload.update(speaker_id=target_id, speaker_confidence=1.0,
                               speaker_assignment="manual")
                self.db.connection.execute("UPDATE segments SET speaker_id=?,payload_json=? "
                                           "WHERE session_id=? AND segment_id=?",
                                           (target_id, json.dumps(payload, ensure_ascii=False),
                                            session_id, row["segment_id"]))
            for row in event_rows:
                payload = json.loads(row["payload_json"])
                if source_id in payload.get("speaker_ids", []):
                    payload["speaker_ids"] = sorted(set(target_id if name == source_id else name
                                                         for name in payload["speaker_ids"]))
                    if len(payload["speaker_ids"]) < 2:
                        # A merge can remove the evidence for a multi-voice claim.
                        payload["speaker_ids"] = []
                        payload["event_type"] = "unknown_overlap"
                        payload["description"] = {"zh_tw": "偵測到重疊聲音，無法可靠區分。"}
                        payload["confidence"] = 0.0
                    self.db.connection.execute("UPDATE segments SET payload_json=? "
                                               "WHERE session_id=? AND segment_id=?",
                                               (json.dumps(payload, ensure_ascii=False),
                                                session_id, row["segment_id"]))
            for index, vector in enumerate(source_vectors[:max(0, 3 - target_count)], start=target_count):
                self.db.connection.execute("INSERT OR REPLACE INTO speaker_embeddings VALUES(?,?,?,?)",
                                           (session_id, target_id, index, json.dumps(vector)))
            self.db.connection.execute("DELETE FROM speaker_embeddings WHERE session_id=? AND speaker_id=?",
                                       (session_id, source_id))
            self.db.connection.execute("DELETE FROM speakers WHERE session_id=? AND speaker_id=?",
                                       (session_id, source_id))
            self._audit(session_id, "merge", {"type": "speaker_merge",
                                              "source": source_id, "target": target_id,
                                              "segments": len(rows)})
        self.reconcile_transcript(session_id)
        self.render_exports(session_id)
        self._write_session_json(session_id)
        return len(rows)

    def _audit(self, session_id: str, operation: str, details: dict) -> None:
        self.db.connection.execute("INSERT INTO speaker_audit(session_id,operation,details_json,at) "
                                   "VALUES(?,?,?,?)", (session_id, operation,
                                    json.dumps(details, ensure_ascii=False),
                                    datetime.now(timezone.utc).isoformat()))

    def append_overlap_event(self, session_id: str, start_ms: int, end_ms: int,
                             speaker_ids: list[str], event_type: str = "unknown_overlap",
                             confidence: float = 0.0) -> bool:
        if event_type not in ("unknown_overlap", "overlapping_speech", "laughter", "collective_reaction"):
            raise ValueError(event_type)
        if end_ms <= start_ms:
            return False
        event_id = f"event_{start_ms}_{end_ms}"
        description = {"zh_tw": ("偵測到重疊聲音，無法可靠區分。" if event_type == "unknown_overlap"
                                 else "多人同時說話，內容無法可靠區分。")}
        payload = {"id": event_id, "type": "multi_speaker_event", "start_ms": start_ms,
                   "end_ms": end_ms, "speaker_ids": speaker_ids, "event_type": event_type,
                   "description": description, "confidence": confidence}
        with self.db.connection:
            cursor = self.db.connection.execute("INSERT OR IGNORE INTO segments "
                "(session_id,segment_id,start_ms,end_ms,type,speaker_id,original,translation,payload_json) "
                "VALUES(?,?,?,?,?,?,?,?,?)", (session_id, event_id, start_ms, end_ms,
                "multi_speaker_event", None, None, None, json.dumps(payload, ensure_ascii=False)))
        if cursor.rowcount:
            self.reconcile_transcript(session_id)
            self.render_exports(session_id)
        return bool(cursor.rowcount)

    def reconcile_transcript(self, session_id: str) -> None:
        """Atomically refresh the machine-readable source without rendering derived exports."""
        session = self.get(session_id)
        if session is None:
            raise KeyError(session_id)
        path = Path(session["folder_path"]) / "transcript.json"
        try:
            existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            # SQLite is authoritative, including after an interrupted legacy JSON write.
            existing = {}
        segments = self.list_segments(session_id)
        speakers = [dict(row) for row in self.db.connection.execute(
            "SELECT speaker_id, display_name, joined_at_ms, left_at_ms, person_id "
            "FROM speakers WHERE session_id=? ORDER BY speaker_id", (session_id,)
        ).fetchall()]
        if existing.get("segments") != segments or existing.get("speakers") != speakers:
            _atomic_json(path, {"session_id": session_id,
                                "speakers": speakers, "segments": segments})

    def render_exports(self, session_id: str, subtitle_mode: str = "translation") -> dict[str, str]:
        """Render human-readable derivatives from SQLite/JSON without mutating source data."""
        if subtitle_mode not in ("translation", "original", "both"):
            raise ValueError(subtitle_mode)
        session = self._session_metadata(session_id)
        folder = Path(session["folder_path"])
        segments = self.list_segments(session_id)
        speakers = self.list_speakers(session_id)
        names = {row["speaker_id"]: row["display_name"] for row in speakers}
        unknown = "未知說話人"
        markdown = [f"# {session['title']}", "", "## Session", "",
                    f"- Session ID：`{session_id}`",
                    f"- 開始：{session['started_at']}",
                    f"- 結束：{session.get('ended_at') or '進行中'}",
                    f"- Duration：{_display_duration(session['duration_ms'])}",
                    f"- Audio Source：{session.get('audio_source') or 'Unknown'}",
                    f"- Source：{_language_name(session['source_language'])}",
                    f"- Target：{_language_name(session['target_language'])}",
                    f"- Translation Style：{session['translation_style'].title()}",
                    f"- Audio Recording：{'Enabled' if session.get('save_audio') else 'Disabled'}",
                    f"- Status：{session['status']}", "", "## Speakers", ""]
        for row in speakers:
            identity = f" · person_id: {row['person_id']}" if row.get("person_id") else ""
            markdown.append(f"- {row['display_name']} (`{row['speaker_id']}`){identity} · "
                            f"detected {_subtitle_time(row['joined_at_ms'], '.')} · "
                            f"{row['segment_count']} segments")
        if any(item.get("speaker_id") in (None, "unknown") for item in segments
               if item.get("type") == "speech"):
            markdown.append(f"- {unknown}")
        audits = self.db.connection.execute(
            "SELECT operation,details_json,at FROM speaker_audit WHERE session_id=? ORDER BY audit_id",
            (session_id,)).fetchall()
        if audits:
            markdown.extend(["", "## Session Events", ""])
            for event in audits:
                details = json.loads(event["details_json"])
                markdown.append(f"- {event['at']} · {event['operation']} · "
                                f"`{json.dumps(details, ensure_ascii=False)}`")
        markdown.extend(["", "---", "", "## Transcript", ""])
        subtitles: list[tuple[int, int, str]] = []
        for item in segments:
            if item.get("type") == "multi_speaker_event":
                name = "多人"
                label = "【重疊】" if item.get("event_type") == "unknown_overlap" else "【多人】"
                translated = item.get("description", {}).get("zh_tw", "偵測到重疊聲音，無法可靠區分。")
                original = ""
            else:
                name = names.get(item.get("speaker_id"), unknown)
                original = item.get("original", "")
                translated = (item.get("translation") or {}).get("text", "")
                label = ""
            placeholder = ("[原文可能辨識不完整]" if item.get("translation_state") == "uncertain_source"
                           else "[翻譯待補]")
            markdown.extend([f"### {_subtitle_time(item['start_ms'], '.')} — {name}", ""])
            if item.get("type") == "multi_speaker_event":
                markdown.extend([f"{label} {translated}", ""])
            else:
                markdown.extend(["**翻譯**", "", translated or placeholder, "",
                                 "**原文**", "", original or "[無原文]", ""])
            if item.get("type") == "multi_speaker_event":
                body = f"{label} {translated}"
            else:
                chosen = original if subtitle_mode == "original" or not translated else translated
                if subtitle_mode == "both":
                    chosen = "\n".join(part for part in (translated, original) if part)
                chosen = chosen or original
                body = f"{name}: {chosen}"
            # Blank cue lines terminate SRT/VTT cues, and raw angle brackets are
            # interpreted as markup. Preserve visible text without breaking cues.
            body = "\n".join(line for line in body.replace("\r", "").split("\n") if line.strip())
            subtitles.append((item["start_ms"], item["end_ms"], html.escape(body, quote=False)))
            markdown.extend(["---", ""])
        exports = folder / "exports"
        exports.mkdir(exist_ok=True)
        md = "\n".join(markdown).rstrip() + "\n"
        srt = "\n\n".join(f"{index}\n{_subtitle_time(start, ',')} --> {_subtitle_time(end, ',')}\n{text}"
                          for index, (start, end, text) in enumerate(subtitles, 1)) + "\n"
        vtt = "WEBVTT\n\n" + "\n\n".join(
            f"{_subtitle_time(start, '.')} --> {_subtitle_time(end, '.')}\n{text}"
            for start, end, text in subtitles) + "\n"
        paths = {"markdown": folder / "transcript.md",
                 "srt": exports / "transcript.srt", "vtt": exports / "transcript.vtt",
                 "json": folder / "transcript.json"}
        _atomic_text(paths["markdown"], md)
        _atomic_text(paths["srt"], srt)
        _atomic_text(paths["vtt"], vtt)
        # Keep Phase 5 paths compatible while new exports use the requested final names.
        _atomic_text(exports / "transcript.md", md)
        _atomic_text(exports / "subtitles.srt", srt)
        _atomic_text(exports / "subtitles.vtt", vtt)
        return {key: str(value) for key, value in paths.items()}

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
        segment = dict(segment)
        segment.setdefault("translation_status", segment.get("translation_state", "pending"))
        payload = json.dumps(segment, ensure_ascii=False)
        with self.db.connection:
            if segment.get("speaker_id") and segment["speaker_id"] != "unknown":
                number = int(segment["speaker_id"].split("_")[-1])
                self.db.connection.execute("""INSERT OR IGNORE INTO speakers
                    (session_id, speaker_id, display_name, joined_at_ms)
                    VALUES (?, ?, ?, ?)""",
                    (session_id, segment["speaker_id"], f"Speaker {number}", segment["start_ms"]))
            cursor = self.db.connection.execute("""INSERT OR IGNORE INTO segments
                (session_id, segment_id, start_ms, end_ms, type, speaker_id,
                 original, translation, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, segment["id"], segment["start_ms"], segment["end_ms"],
                 "speech", segment.get("speaker_id"), segment["original"], None, payload))
            if cursor.rowcount:
                self.db.connection.execute("UPDATE sessions SET updated_at=? WHERE session_id=?",
                                           (now, session_id))
        self.reconcile_transcript(session_id)
        if cursor.rowcount:
            self.classify_overlap_events(session_id, segment["start_ms"], segment["end_ms"])
        return bool(cursor.rowcount)

    def classify_overlap_events(self, session_id: str, start_ms: int, end_ms: int) -> int:
        """Upgrade only when two *distinct assigned voices* provide explicit text evidence."""
        events = self.db.connection.execute(
            "SELECT segment_id,start_ms,end_ms,payload_json FROM segments WHERE session_id=? "
            "AND type='multi_speaker_event' AND start_ms<? AND end_ms>?",
            (session_id, end_ms, start_ms)).fetchall()
        changed = 0
        laughter = re.compile(r"\s*(?:\[笑い\]|\[笑\]|\[laughter\]|\(laughing\)|笑い声)\s*", re.I)
        reaction = re.compile(r"\s*(?:え[っー!！?？]+|わ[ー!！]+|お[おー!！]+|oh[!！?？]+|wow[!！?？]*)\s*", re.I)
        for event in events:
            related = [json.loads(row["payload_json"]) for row in self.db.connection.execute(
                "SELECT payload_json FROM segments WHERE session_id=? AND type='speech' "
                "AND start_ms<? AND end_ms>?", (session_id, event["end_ms"], event["start_ms"]))]
            selected: dict[str, str] = {}
            for item in related:
                speaker = item.get("speaker_id")
                if speaker and speaker != "unknown" and item.get("speaker_confidence", 0) >= 0.7:
                    selected[speaker] = item.get("original", "")
            if len(selected) < 2:
                continue
            texts = list(selected.values())
            if all(laughter.fullmatch(text) for text in texts):
                kind, description = "laughter", "多人同時大笑。"
            elif all(reaction.fullmatch(text) for text in texts):
                kind, description = "collective_reaction", "多人同時發出驚呼。"
            else:
                continue
            payload = json.loads(event["payload_json"])
            if payload.get("event_type") == kind:
                continue
            payload.update(event_type=kind, description={"zh_tw": description},
                           speaker_ids=sorted(selected))
            with self.db.connection:
                self.db.connection.execute("UPDATE segments SET payload_json=? "
                                           "WHERE session_id=? AND segment_id=?",
                                           (json.dumps(payload, ensure_ascii=False), session_id, event["segment_id"]))
            changed += 1
        if changed:
            self.reconcile_transcript(session_id)
            self.render_exports(session_id)
        return changed

    def update_final_translation(self, session_id: str, segment_id: str, translation: dict) -> bool:
        """Commit translation and JSON payload together; reconcile the readable copy."""
        row = self.db.connection.execute(
            "SELECT payload_json FROM segments WHERE session_id=? AND segment_id=?",
            (session_id, segment_id)).fetchone()
        if row is None:
            return False
        payload = json.loads(row["payload_json"])
        if payload.get("translation_state") == "final":
            return False
        payload["translation"] = translation
        payload["translation_state"] = "final"
        payload["translation_status"] = "final"
        with self.db.connection:
            self.db.connection.execute(
                "UPDATE segments SET translation=?, payload_json=? WHERE session_id=? AND segment_id=?",
                (translation["text"], json.dumps(payload, ensure_ascii=False), session_id, segment_id))
        self.reconcile_transcript(session_id)
        return True

    def set_translation_state(self, session_id: str, segment_id: str, state: str) -> bool:
        """Persist an in-progress or failed state without storing unverified candidate text."""
        if state not in ("verifying", "repair_pending", "pending", "rejected", "uncertain_source"):
            raise ValueError(state)
        row = self.db.connection.execute(
            "SELECT payload_json FROM segments WHERE session_id=? AND segment_id=?",
            (session_id, segment_id)).fetchone()
        if row is None:
            return False
        payload = json.loads(row["payload_json"])
        if payload.get("translation_state") == "final":
            return False
        payload.pop("translation", None)
        payload["translation_state"] = state
        payload["translation_status"] = state
        with self.db.connection:
            self.db.connection.execute(
                "UPDATE segments SET translation=NULL,payload_json=? WHERE session_id=? AND segment_id=?",
                (json.dumps(payload, ensure_ascii=False), session_id, segment_id))
        self.reconcile_transcript(session_id)
        return True

    def pending_translations(self, session_id: str, *, limit: int = 64, offset: int = 0,
                             newest_first: bool = False) -> list[dict]:
        order = "DESC" if newest_first else "ASC"
        rows = self.db.connection.execute(
            "SELECT payload_json FROM segments WHERE session_id=? AND type='speech' AND translation IS NULL "
            "AND COALESCE(json_extract(payload_json, '$.translation_state'),'pending') != 'uncertain_source' "
            f"ORDER BY start_ms {order}, segment_id {order} LIMIT ? OFFSET ?",
            (session_id, max(1, min(64, int(limit))), max(0, int(offset)))).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

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
        self._write_session_json(session_id)

    def set_audio_source(self, session_id: str, source_process: str) -> None:
        source = source_process.strip()[:160] or None
        with self.db.connection:
            self.db.connection.execute("UPDATE sessions SET audio_source=? WHERE session_id=?",
                                       (source, session_id))
        self._write_session_json(session_id)

    def set_translation_preferences(self, session_id: str, key: str, value: str) -> None:
        choices = {"target_language": ("zh-TW", "zh-CN"),
                   "translation_style": ("natural", "faithful", "minimal")}
        if key not in choices or value not in choices[key]:
            raise ValueError((key, value))
        session = self.get(session_id)
        if not session or session["status"] != "active":
            return
        session[key] = value
        with self.db.connection:
            self.db.connection.execute(f"UPDATE sessions SET {key}=? WHERE session_id=?",
                                       (value, session_id))
        self._write_session_json(session_id)

    def rename(self, session_id: str, title: str) -> dict:
        value = title.strip()[:120]
        if not value:
            raise ValueError("Session 名稱不能留空。")
        now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        with self.db.connection:
            self.db.connection.execute("UPDATE sessions SET title=?,updated_at=? WHERE session_id=?",
                                       (value, now, session_id))
        self._write_session_json(session_id)
        self.render_exports(session_id)
        return self.get(session_id) or {}

    def search(self, session_id: str, query: str, limit: int = 100) -> list[dict]:
        needle = query.strip().casefold()
        if not needle:
            return []
        names = {row["speaker_id"]: row["display_name"] for row in self.list_speakers(session_id)}
        result = []
        for item in self.list_segments(session_id):
            haystack = "\n".join((item.get("original", ""),
                                  (item.get("translation") or {}).get("text", ""),
                                  names.get(item.get("speaker_id"), "未知說話人"))).casefold()
            if needle in haystack:
                result.append({**item, "speaker_display_name": names.get(
                    item.get("speaker_id"), "未知說話人")})
                if len(result) >= max(1, min(limit, 500)):
                    break
        return result

    def delete(self, session_id: str) -> None:
        session = self.get(session_id)
        if not session:
            return
        if session["status"] == "active":
            raise ValueError("請先結束或封存 Session，再執行刪除。")
        folder = Path(session["folder_path"]).resolve()
        root = self.root.resolve()
        if root not in folder.parents:
            raise ValueError("Session 資料夾不在預期位置，拒絕刪除。")
        with self.db.connection:
            self.db.connection.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
        if folder.exists():
            shutil.rmtree(folder)

    def clear_temporary_cache(self, session_id: str) -> None:
        session = self.get(session_id)
        if not session:
            return
        folder = Path(session["folder_path"])
        for name in ("cache", "tmp", "temporary_pcm", "diarization_chunks", "translation_buffers"):
            path = folder / name
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()

    def finish(self, session_id: str, subtitle_mode: str = "translation") -> dict:
        session = self.get(session_id)
        if session is None:
            raise KeyError(session_id)
        if session["status"] != "active":
            return session
        # Keep the Session active when any required durable output fails.
        self.reconcile_transcript(session_id)
        now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        try:
            self.db.connection.execute("UPDATE sessions SET status=?, updated_at=?, ended_at=? WHERE session_id=?",
                                       ("completed", now, now, session_id))
            self._write_session_json(session_id)
            self.render_exports(session_id, subtitle_mode)
            self.db.connection.commit()
        except Exception:
            self.db.connection.rollback()
            with self.db.connection:
                self.db.connection.execute(
                    "UPDATE sessions SET status='active',ended_at=NULL WHERE session_id=?", (session_id,))
            self._write_session_json(session_id)
            raise
        self.db.connection.execute("PRAGMA wal_checkpoint(PASSIVE)")
        self.clear_temporary_cache(session_id)
        return self.get(session_id) or session

    def archive_interrupted(self, session_id: str, subtitle_mode: str = "translation") -> dict:
        session = self.get(session_id)
        if not session or session["status"] != "interrupted":
            raise ValueError("只能封存中斷的 Session。")
        with self.db.connection:
            self.db.connection.execute("UPDATE sessions SET status='active' WHERE session_id=?", (session_id,))
        try:
            return self.finish(session_id, subtitle_mode)
        except Exception:
            with self.db.connection:
                self.db.connection.execute(
                    "UPDATE sessions SET status='interrupted',ended_at=NULL WHERE session_id=?", (session_id,))
            self._write_session_json(session_id)
            raise

    def mark_interrupted(self) -> int:
        rows = self.db.connection.execute("SELECT session_id, folder_path FROM sessions WHERE status='active'").fetchall()
        with self.db.connection:
            self.db.connection.execute("UPDATE sessions SET status='interrupted' WHERE status='active'")
        for row in rows:
            self._write_session_json(row["session_id"])
        return len(rows)
