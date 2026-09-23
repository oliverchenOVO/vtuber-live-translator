"""Kill only private test download processes, then resume their existing caches."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from vlt.product.models import ModelManager


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--worker", choices=["asr", "ollama"])
    args = parser.parse_args()
    root = args.root.resolve(); root.mkdir(parents=True, exist_ok=True)
    if args.worker == "asr":
        manager = ModelManager(root / "models", root / "cache", root / "runtime")
        manager.install("asr", lambda *_: None)
        manager.verify("asr")
        return
    if args.worker == "ollama":
        req = urllib.request.Request("http://127.0.0.1:11435/api/pull",
            json.dumps({"model": "qwen2.5:1.5b", "stream": True}).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=1200) as response:
            for line in response:
                event = json.loads(line)
                if event.get("error"):
                    raise RuntimeError(event["error"])
                (root / "pull-progress.json").write_text(json.dumps(event))
        return
    flags = subprocess.CREATE_NO_WINDOW
    def worker(kind):
        return subprocess.Popen([sys.executable, __file__, str(root), "--worker", kind],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    def kill(process):
        if process.poll() is None:
            subprocess.run(["taskkill", "/F", "/PID", str(process.pid)], check=True,
                           stdout=subprocess.DEVNULL, creationflags=flags)
            process.wait(timeout=10)
    report = {}
    asr = worker("asr")
    deadline = time.monotonic() + 120
    while asr.poll() is None and time.monotonic() < deadline:
        partials = list((root / "models").rglob("*.incomplete"))
        size = sum(p.stat().st_size for p in partials if p.exists())
        if size > 1024**2:
            kill(asr)
            report["asr_interrupted_partial_bytes"] = size
            break
        time.sleep(.1)
    if asr.poll() is None:
        kill(asr)
    report["asr_resume_exit"] = worker("asr").wait(timeout=600)
    # Use an isolated local endpoint and model store, never the user's active service.
    try:
        urllib.request.urlopen("http://127.0.0.1:11435/api/tags", timeout=.3)
        raise RuntimeError("Test port already in use; will not stop that service")
    except OSError:
        pass
    env = dict(os.environ, OLLAMA_HOST="127.0.0.1:11435", OLLAMA_MODELS=str(root / "ollama-models"))
    def server():
        process = subprocess.Popen([shutil.which("ollama"), "serve"], env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        for _ in range(100):
            try:
                urllib.request.urlopen("http://127.0.0.1:11435/api/tags", timeout=.2).close()
                return process
            except OSError:
                time.sleep(.1)
        kill(process)
        raise RuntimeError("Private model server did not start")
    service = server()
    download = worker("ollama")
    try:
        deadline = time.monotonic() + 180
        while download.poll() is None and time.monotonic() < deadline:
            try:
                event = json.loads((root / "pull-progress.json").read_text())
                if event.get("completed", 0) > 8 * 1024**2:
                    report["ollama_interrupted_completed_bytes"] = event["completed"]
                    break
            except (OSError, ValueError):
                pass
            time.sleep(.1)
        kill(download); kill(service)
        report["ollama_partial_files"] = len(list((root / "ollama-models").rglob("*partial*")))
        service = server()
        report["ollama_resume_exit"] = worker("ollama").wait(timeout=900)
        with urllib.request.urlopen("http://127.0.0.1:11435/api/tags", timeout=5) as response:
            report["ollama_models_after_resume"] = [m["name"] for m in json.load(response)["models"]]
    finally:
        kill(download); kill(service)
    (root / "result.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
