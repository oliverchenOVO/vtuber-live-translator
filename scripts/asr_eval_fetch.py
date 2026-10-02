"""Fetch the public FLEURS dev archives with bounded HTTP range requests.

The official Hugging Face Xet endpoint sometimes stalls on this Windows PC
for a single long transfer. Each chunk is verified by the final SHA-256 from
the dataset repository API. Files remain in ignored data/asr-eval/.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import threading
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "data/asr-eval/fleurs"
CHUNK = 8 * 1024 * 1024


def fetch(locale: str) -> Path:
    if locale not in {"ja_jp", "en_us"}:
        raise ValueError(locale)
    listing = json.load(urllib.request.urlopen(
        f"https://huggingface.co/api/datasets/google/fleurs/tree/main/data/{locale}/audio?recursive=false",
        timeout=30))
    metadata = next(item for item in listing if item["path"].endswith("dev.tar.gz"))
    expected_size = metadata["size"]
    expected_sha = metadata["lfs"]["oid"]
    destination = TARGET / f"{locale}-dev.tar.gz"
    url = f"https://huggingface.co/datasets/google/fleurs/resolve/main/data/{locale}/audio/dev.tar.gz?download=true"
    archive = download_verified(url, destination, expected_size, expected_sha, locale)
    rows = json.load(urllib.request.urlopen(
        f"https://huggingface.co/api/datasets/google/fleurs/tree/main/data/{locale}?recursive=false",
        timeout=30))
    tsv = next(item for item in rows if item["path"].endswith("dev.tsv"))
    tsv_path = TARGET / f"{locale}-dev.tsv"
    content = urllib.request.urlopen(
        f"https://huggingface.co/datasets/google/fleurs/resolve/main/data/{locale}/dev.tsv",
        timeout=60).read()
    blob_sha = hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
    if len(content) != tsv["size"] or blob_sha != tsv["oid"]:
        raise OSError("FLEURS reference TSV did not match repository metadata")
    tsv_path.write_bytes(content)
    return archive


def download_verified(url: str, destination: Path, expected_size: int,
                      expected_sha: str, label: str) -> Path:
    if destination.exists() and destination.stat().st_size == expected_size:
        with destination.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest == expected_sha:
            return destination
    temporary = destination.with_suffix(".part")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with temporary.open("wb") as output:
        output.truncate(expected_size)
    write_lock = threading.Lock()

    def fetch_chunk(offset: int) -> int:
        end = min(expected_size, offset + CHUNK) - 1
        for attempt in range(3):
            try:
                request = urllib.request.Request(url, headers={"Range": f"bytes={offset}-{end}"})
                with urllib.request.urlopen(request, timeout=90) as response:
                    if response.status != 206:
                        raise OSError("Range request was not honored")
                    data = response.read()
                if len(data) != end - offset + 1:
                    raise OSError("Incomplete audio archive chunk")
                with write_lock, temporary.open("r+b") as output:
                    output.seek(offset)
                    output.write(data)
                return len(data)
            except (OSError, TimeoutError):
                if attempt == 2:
                    raise
        raise AssertionError("unreachable")

    offsets = range(0, expected_size, CHUNK)
    completed = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        for future in as_completed(pool.submit(fetch_chunk, offset) for offset in offsets):
            completed += future.result()
            print(f"{label}: {completed / expected_size:.0%}", flush=True)
    with temporary.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != expected_sha:
        raise OSError("Downloaded file SHA-256 did not match repository metadata")
    temporary.replace(destination)
    return destination


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("locale", choices=("ja_jp", "en_us"))
    args = parser.parse_args()
    print(fetch(args.locale), flush=True)
