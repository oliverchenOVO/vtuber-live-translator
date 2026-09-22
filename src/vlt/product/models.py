from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from vlt.product.downloads import download_resumable, has_disk_space


OLLAMA_VERSION = "0.34.2"
OLLAMA_URL = f"https://github.com/ollama/ollama/releases/download/v{OLLAMA_VERSION}/ollama-windows-amd64.zip"
OLLAMA_SHA256 = "8f3fd071a2a2f9497b562f43502c77c2b701a99d1ee5dfda28da8c786373063b"


def _download_message(label: str, done: int, total: int, started_at: float) -> str:
    elapsed = max(time.monotonic() - started_at, 0.001)
    speed = done / elapsed
    remaining = max(total - done, 0) / speed if speed else 0
    def size(value: float) -> str:
        return f"{value / 1024 ** 3:.2f} GB" if value >= 1024 ** 3 else f"{value / 1024 ** 2:.1f} MB"
    eta = f"{int(remaining // 60)}:{int(remaining % 60):02d}" if total and speed else "--:--"
    return f"{label}  {size(done)} / {size(total)}  ·  {size(speed)}/s  ·  剩餘 {eta}"


def hidden_process_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


class ModelManager:
    """Owns optional AI components; the capture and transcript pipelines stay independent."""

    def __init__(self, root: Path, cache: Path, runtime: Path):
        self.root, self.cache, self.runtime = root, cache, runtime
        for folder in (root, cache, runtime):
            folder.mkdir(parents=True, exist_ok=True)
        self._ollama_process: subprocess.Popen | None = None

    def ollama_executable(self) -> Path | None:
        managed = self.runtime / "ollama" / "ollama.exe"
        if managed.exists():
            return managed
        found = shutil.which("ollama")
        if found:
            return Path(found)
        installed = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
        return installed if installed.exists() else None

    def status(self) -> dict:
        asr_ready = any(self.root.rglob("model.bin"))
        diar_ready = (self.root / "diarization" / "segmentation.onnx").exists()
        ollama = self.ollama_executable()
        translation_ready = False
        if ollama:
            try:
                result = subprocess.run([str(ollama), "list"], capture_output=True, text=True,
                                        timeout=8, creationflags=hidden_process_flags())
                translation_ready = "qwen2.5:1.5b" in result.stdout
            except (OSError, subprocess.SubprocessError):
                pass
        return {"asr": asr_ready, "translation": translation_ready, "diarization": diar_ready,
                "ollama": bool(ollama)}

    def install_ollama(self, progress: Callable[[str, int], None]) -> Path:
        existing = self.ollama_executable()
        if existing:
            return existing
        # Keep room for the 1.36 GiB archive, 1.80 GiB runtime and the model
        # that is pulled next. has_disk_space also reserves another 1 GiB.
        required = 6 * 1024 ** 3
        if not has_disk_space(self.runtime, required):
            raise RuntimeError("磁碟空間不足；安裝本機翻譯服務至少需要 7.0 GB 可用空間。")
        archive = self.cache / f"ollama-{OLLAMA_VERSION}.zip"
        started_at = time.monotonic()
        download_resumable(OLLAMA_URL, archive, OLLAMA_SHA256,
                           lambda done, total: progress(
                               _download_message("正在下載本機翻譯服務", done, total, started_at),
                               int(done * 100 / total) if total else 0))
        target = self.runtime / "ollama"
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as bundle:
            root = target.resolve()
            for member in bundle.infolist():
                destination = (target / member.filename).resolve()
                if root not in destination.parents and destination != root:
                    raise RuntimeError("下載套件包含不安全的路徑。")
            bundle.extractall(target)
        executable = next(target.rglob("ollama.exe"), None)
        if not executable:
            raise RuntimeError("本機翻譯服務安裝檔不完整。")
        if executable.parent != target:
            for item in executable.parent.iterdir():
                destination = target / item.name
                if not destination.exists():
                    shutil.move(str(item), destination)
        progress("本機翻譯服務已安裝", 100)
        return target / "ollama.exe"

    def ensure_server(self) -> Path:
        executable = self.ollama_executable()
        if not executable:
            raise RuntimeError("尚未安裝本機翻譯服務。")
        try:
            urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2).close()
            return executable
        except OSError:
            env = dict(os.environ)
            env["OLLAMA_MODELS"] = str(self.root / "translation")
            self._ollama_process = subprocess.Popen(
                [str(executable), "serve"], env=env, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=hidden_process_flags())
            for _ in range(30):
                try:
                    urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1).close()
                    return executable
                except OSError:
                    time.sleep(.25)
            raise RuntimeError("本機翻譯服務無法啟動，請重新啟動應用程式後重試。")

    def pull_translation(self, model: str, progress: Callable[[str, int], None]) -> None:
        if not has_disk_space(self.root, 2 * 1024 ** 3):
            raise RuntimeError("磁碟空間不足；翻譯模型至少需要 3.0 GB 可用空間。")
        self.ensure_server()
        started_at = time.monotonic()
        payload = json.dumps({"name": model, "stream": True}).encode()
        request = urllib.request.Request("http://127.0.0.1:11434/api/pull", payload,
                                         {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=1800) as response:
            for line in response:
                event = json.loads(line)
                completed, total = event.get("completed", 0), event.get("total", 0)
                percent = int(completed * 100 / total) if total else 0
                status = event.get("status", "正在準備翻譯模型")
                message = (_download_message(status, completed, total, started_at)
                           if completed and total else status)
                progress(message, percent)

    def install(self, component: str, progress: Callable[[str, int], None]) -> None:
        if component == "translation":
            self.install_ollama(progress)
            self.pull_translation("qwen2.5:1.5b", progress)
        elif component == "asr":
            from faster_whisper import WhisperModel
            progress("正在準備語音辨識模型", 5)
            had_existing = any(self.root.glob("models--Systran--faster-whisper-*"))
            try:
                WhisperModel("base", device="cpu", compute_type="int8",
                             download_root=str(self.root), cpu_threads=2)
            except Exception:
                if not had_existing:
                    raise
                self.remove("asr")
                WhisperModel("base", device="cpu", compute_type="int8",
                             download_root=str(self.root), cpu_threads=2)
            progress("語音辨識模型已就緒", 100)
        elif component == "diarization":
            from vlt.diarization.sherpa_backend import ensure_models
            progress("正在準備 Speaker 模型", 5)
            ensure_models(self.root / "diarization")
            progress("Speaker 模型已就緒", 100)
        else:
            raise ValueError(component)

    def remove(self, component: str) -> None:
        """Remove model payloads while keeping the reusable runtime installed."""
        if component == "asr":
            for path in self.root.glob("models--Systran--faster-whisper-*"):
                if path.is_dir():
                    shutil.rmtree(path)
        elif component == "diarization":
            shutil.rmtree(self.root / "diarization", ignore_errors=True)
        elif component == "translation":
            if not self.ollama_executable():
                return
            self.ensure_server()
            payload = json.dumps({"name": "qwen2.5:1.5b"}).encode()
            request = urllib.request.Request(
                "http://127.0.0.1:11434/api/delete", payload,
                {"Content-Type": "application/json"}, method="DELETE")
            try:
                urllib.request.urlopen(request, timeout=60).close()
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    raise
        else:
            raise ValueError(component)

    def close(self) -> None:
        if self._ollama_process and self._ollama_process.poll() is None:
            self._ollama_process.terminate()
