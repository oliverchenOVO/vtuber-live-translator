from __future__ import annotations

import json
import os
from pathlib import Path


DEFAULTS = {
    "source_language": "ja",
    "target_language": "zh-TW",
    "translation_style": "natural",
    "overlay_mode": "gaming",
    "overlay_opacity": 0.9,
    "save_audio": False,
}


def data_directory() -> Path:
    override = os.environ.get("VLT_DATA_DIR")
    return Path(override) if override else Path(os.environ["LOCALAPPDATA"]) / "VtuberLiveTranslator"


class SettingsManager:
    def __init__(self, root: Path):
        self.path = root / "settings.json"
        self.values = dict(DEFAULTS)
        if self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.values.update({key: value for key, value in raw.items() if key in DEFAULTS})

    def set(self, key: str, value: object) -> None:
        if key not in DEFAULTS:
            raise KeyError(key)
        self.values[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.values, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

