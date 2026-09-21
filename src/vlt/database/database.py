from __future__ import annotations

import sqlite3
from pathlib import Path


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                folder_path TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                ended_at TEXT,
                status TEXT NOT NULL CHECK(status IN ('active','completed','interrupted')),
                source_language TEXT NOT NULL,
                target_language TEXT NOT NULL,
                translation_style TEXT NOT NULL,
                audio_source TEXT,
                save_audio INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS speakers (
                session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                speaker_id TEXT NOT NULL,
                display_name TEXT NOT NULL,
                joined_at_ms INTEGER NOT NULL DEFAULT 0,
                left_at_ms INTEGER,
                person_id TEXT,
                PRIMARY KEY(session_id, speaker_id)
            );
            CREATE TABLE IF NOT EXISTS segments (
                session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                segment_id TEXT NOT NULL,
                start_ms INTEGER NOT NULL,
                end_ms INTEGER NOT NULL,
                type TEXT NOT NULL,
                speaker_id TEXT,
                original TEXT,
                translation TEXT,
                payload_json TEXT NOT NULL,
                PRIMARY KEY(session_id, segment_id)
            );
            CREATE TABLE IF NOT EXISTS speaker_embeddings (
                session_id TEXT NOT NULL,
                speaker_id TEXT NOT NULL,
                sample_index INTEGER NOT NULL,
                vector_json TEXT NOT NULL,
                PRIMARY KEY(session_id, speaker_id, sample_index),
                FOREIGN KEY(session_id, speaker_id) REFERENCES speakers(session_id, speaker_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS speaker_audit (
                audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                operation TEXT NOT NULL,
                details_json TEXT NOT NULL,
                at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS speaker_sequence (
                session_id TEXT PRIMARY KEY REFERENCES sessions(session_id) ON DELETE CASCADE,
                next_number INTEGER NOT NULL
            );
        """)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()
