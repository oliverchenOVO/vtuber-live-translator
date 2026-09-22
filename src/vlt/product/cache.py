from __future__ import annotations

import shutil
import time
from pathlib import Path


class CacheManager:
    def __init__(self, root: Path, maximum_bytes: int = 2 * 1024 ** 3):
        self.root = root
        self.maximum_bytes = maximum_bytes
        root.mkdir(parents=True, exist_ok=True)

    def size(self) -> int:
        return sum(path.stat().st_size for path in self.root.rglob("*") if path.is_file())

    def clear(self) -> int:
        before = self.size()
        for path in tuple(self.root.iterdir()):
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
        return before

    def prune(self) -> int:
        files = sorted((p for p in self.root.rglob("*") if p.is_file()),
                       key=lambda p: p.stat().st_mtime)
        removed = 0
        total = sum(p.stat().st_size for p in files)
        for path in files:
            if total <= self.maximum_bytes:
                break
            size = path.stat().st_size
            path.unlink(missing_ok=True)
            total -= size
            removed += size
        return removed

