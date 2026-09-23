from __future__ import annotations

import hashlib
import os
import shutil
import urllib.request
import urllib.error
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
    if target.exists() and expected_sha256 and sha256(target).lower() == expected_sha256.lower():
        return target
    partial = target.with_suffix(target.suffix + ".part")
    existing = partial.stat().st_size if partial.exists() else 0
    request = urllib.request.Request(url, headers={"Range": f"bytes={existing}-"} if existing else {})
    try:
        response = opener(request, timeout=120)
    except urllib.error.HTTPError as exc:
        # A crash after the last byte but before rename leaves a complete .part;
        # the server correctly answers Range-at-EOF with 416 on the next launch.
        if exc.code == 416 and existing and expected_sha256:
            if sha256(partial).lower() == expected_sha256.lower():
                partial.replace(target)
                return target
            partial.unlink(missing_ok=True)
            return download_resumable(url, target, expected_sha256, progress, opener)
        raise
    with response:
        status = getattr(response, "status", 200)
        if existing and status == 206:
            content_range = response.headers.get("Content-Range", "")
            if content_range and not content_range.startswith(f"bytes {existing}-"):
                raise RuntimeError("下載續傳範圍不符，請重試。")
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
            output.flush()
            os.fsync(output.fileno())
        if remaining and existing != total:
            raise RuntimeError("下載中斷，已保留進度；請重試以繼續下載。")
    if expected_sha256 and sha256(partial).lower() != expected_sha256.lower():
        partial.unlink(missing_ok=True)
        raise RuntimeError("下載檔案驗證失敗，請重試。")
    partial.replace(target)
    return target


def has_disk_space(folder: Path, required_bytes: int, reserve_bytes: int = 1024 ** 3) -> bool:
    folder.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(folder).free >= required_bytes + reserve_bytes
