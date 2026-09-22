from __future__ import annotations

import hashlib
import shutil
import urllib.request
from pathlib import Path
from typing import Callable


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def download_resumable(url: str, target: Path, expected_sha256: str | None = None,
                       progress: Callable[[int, int], None] | None = None,
                       opener=urllib.request.urlopen) -> Path:
    """Download to a fixed size .part file and resume using HTTP Range."""
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    existing = partial.stat().st_size if partial.exists() else 0
    request = urllib.request.Request(url, headers={"Range": f"bytes={existing}-"} if existing else {})
    with opener(request, timeout=120) as response:
        status = getattr(response, "status", 200)
        if existing and status != 206:
            partial.unlink(missing_ok=True)
            existing = 0
        mode = "ab" if existing else "wb"
        remaining = int(response.headers.get("Content-Length", 0))
        total = existing + remaining
        with partial.open(mode) as output:
            while block := response.read(1024 * 1024):
                output.write(block)
                existing += len(block)
                if progress:
                    progress(existing, total)
    if expected_sha256 and sha256(partial).lower() != expected_sha256.lower():
        partial.unlink(missing_ok=True)
        raise RuntimeError("下載檔案驗證失敗，請重試。")
    partial.replace(target)
    return target


def has_disk_space(folder: Path, required_bytes: int, reserve_bytes: int = 1024 ** 3) -> bool:
    folder.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(folder).free >= required_bytes + reserve_bytes

