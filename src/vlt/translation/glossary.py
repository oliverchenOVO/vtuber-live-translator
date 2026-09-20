"""User managed terminology, stored outside the transcript."""
from __future__ import annotations

import json
from pathlib import Path

from vlt.sessions.manager import _atomic_json


class Glossary:
    def __init__(self, path: Path):
        self.path = path
        self.entries: list[dict] = []
        if path.exists():
            self.import_file(path)

    def list(self) -> list[dict]:
        return [dict(item, aliases=list(item["aliases"])) for item in self.entries]

    def upsert(self, source: str, preferred_zh_tw: str, preferred_zh_cn: str,
               aliases: list[str] | None = None) -> None:
        source = source.strip()
        if not source or not (preferred_zh_tw.strip() and preferred_zh_cn.strip()):
            raise ValueError("請填寫原文、繁體及簡體譯名。")
        entry = {"source": source, "preferred_zh_tw": preferred_zh_tw.strip(),
                 "preferred_zh_cn": preferred_zh_cn.strip(),
                 "aliases": [alias.strip() for alias in (aliases or []) if alias.strip()]}
        self.entries = [item for item in self.entries if item["source"] != source] + [entry]
        self.export_file(self.path)

    def delete(self, source: str) -> None:
        self.entries = [item for item in self.entries if item["source"] != source]
        self.export_file(self.path)

    def export_file(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_json(path, {"version": 1, "entries": self.entries})

    def import_file(self, path: Path) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data["entries"]
        if not isinstance(entries, list) or len(entries) > 10000:
            raise ValueError("詞庫格式錯誤。")
        validated = []
        for item in entries:
            validated.append({"source": str(item["source"]),
                              "preferred_zh_tw": str(item["preferred_zh_tw"]),
                              "preferred_zh_cn": str(item["preferred_zh_cn"]),
                              "aliases": [str(alias) for alias in item.get("aliases", [])]})
        self.entries = validated
        if path != self.path:
            self.export_file(self.path)
