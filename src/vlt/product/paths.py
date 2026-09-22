from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProductPaths:
    root: Path
    sessions: Path
    models: Path
    cache: Path
    logs: Path
    runtime: Path

    @classmethod
    def discover(cls) -> "ProductPaths":
        override = os.environ.get("VLT_DATA_DIR")
        root = Path(override) if override else Path(os.environ["LOCALAPPDATA"]) / "VtuberLiveTranslator"
        return cls(root, root / "sessions", root / "models", root / "cache", root / "logs", root / "runtime")

    def ensure(self) -> None:
        for path in (self.root, self.sessions, self.models, self.cache, self.logs, self.runtime):
            path.mkdir(parents=True, exist_ok=True)
        legacy_diarization = self.root / "diarization-models"
        current_diarization = self.models / "diarization"
        if legacy_diarization.exists() and not current_diarization.exists():
            legacy_diarization.replace(current_diarization)
