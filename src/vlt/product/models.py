from __future__ import annotations

import json
import hashlib
import logging
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

import psutil

from vlt.product.downloads import download_resumable, has_disk_space, sha256


OLLAMA_VERSION = "0.34.2"
OLLAMA_URL = f"https://github.com/ollama/ollama/releases/download/v{OLLAMA_VERSION}/ollama-windows-amd64.zip"
OLLAMA_SHA256 = "8f3fd071a2a2f9497b562f43502c77c2b701a99d1ee5dfda28da8c786373063b"
# Official Systran repository metadata, pinned for reproducible RC verification.
ASR_REVISION = "ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66"
ASR_HASHES = {"model.bin": "d01c3014881c9c6f3133c182f3d2887eb6ca1c789a7538c5c007196857a0a6a9",
              "config.json": "867cf1a0fece1394e01d55e287ba2f09a577c046",
              "tokenizer.json": "7818adb6de9fa3064d3ff81226fdd675be1f6344",
              "vocabulary.txt": "c9074644d9d1205686f16d411564729461324b75"}


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
        model_root = (self.root / "translation" if ollama and ollama.is_relative_to(self.runtime)
                      else Path(os.environ.get("OLLAMA_MODELS", str(Path.home() / ".ollama" / "models"))))
        translation_ready = (model_root / "manifests" / "registry.ollama.ai" / "library" / "qwen2.5" / "1.5b").is_file()
        if ollama:
            try:
                with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=.5) as response:
                    translation_ready = translation_ready or any(item.get("name") == "qwen2.5:1.5b"
                                            for item in json.load(response).get("models", []))
            except (OSError, ValueError):
                pass
        return {"asr": asr_ready, "translation": translation_ready, "diarization": diar_ready,
                "ollama": bool(ollama)}

    def install_ollama(self, progress: Callable[[str, int], None]) -> Path:
        existing = self.ollama_executable()
        if existing and not existing.is_relative_to(self.runtime):
            return existing
        # Explicit Install/Repair re-extracts the managed runtime from its checked
        # archive. An interrupted extraction may leave ollama.exe but omit DLLs.
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
            if executable.is_relative_to(self.runtime):
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
            from huggingface_hub import snapshot_download
            if not has_disk_space(self.root, 300 * 1024 ** 2):
                raise RuntimeError("磁碟空間不足；語音辨識元件需要 1.3 GB 可用空間。")
            progress("正在準備語音辨識模型", 5)
            # Only replace individually identified corrupt blobs. A network failure must
            # never erase the repository cache or its resumable .incomplete files.
            damaged = self._damaged_asr_files()
            if damaged:
                for name in damaged:
                    file = self.asr_snapshot() / name
                    if file.exists():
                        # HF force_download updates blobs, but retains an existing
                        # regular snapshot copy on Windows. Quarantine just that
                        # copy so the verified replacement can become the pointer.
                        file.replace(file.with_suffix(file.suffix + ".corrupt"))
                snapshot_download("Systran/faster-whisper-base", cache_dir=str(self.root),
                                  revision=ASR_REVISION, allow_patterns=damaged, force_download=True)
            snapshot = snapshot_download("Systran/faster-whisper-base", cache_dir=str(self.root),
                                         revision=ASR_REVISION, allow_patterns=list(ASR_HASHES))
            if self._damaged_asr_files():
                raise RuntimeError("語音辨識模型驗證失敗，請重試修復。")
            for name in damaged:
                file = self.asr_snapshot() / name
                file.with_suffix(file.suffix + ".corrupt").unlink(missing_ok=True)
            WhisperModel(snapshot, device="cpu", compute_type="int8",
                         download_root=str(self.root), cpu_threads=2, local_files_only=True)
            progress("語音辨識模型已就緒", 100)
        elif component == "diarization":
            from vlt.diarization.sherpa_backend import ensure_models
            progress("正在準備 Speaker 模型", 5)
            ensure_models(self.root / "diarization")
            progress("Speaker 模型已就緒", 100)
        else:
            raise ValueError(component)

    def _damaged_asr_files(self) -> list[str]:
        damaged = set()
        for name, expected in ASR_HASHES.items():
            file = self.asr_snapshot() / name
            if not file.exists() and file.with_suffix(file.suffix + ".corrupt").exists():
                damaged.add(name)
            if file.is_file():
                if len(expected) == 64:
                    digest = sha256(file)
                else:
                    data = file.read_bytes()
                    digest = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
                if digest != expected:
                    damaged.add(file.name)
        return sorted(damaged)

    def asr_snapshot(self) -> Path:
        return self.root / "models--Systran--faster-whisper-base" / "snapshots" / ASR_REVISION

    def verify(self, component: str) -> None:
        if component == "asr":
            from faster_whisper import WhisperModel
            if self._damaged_asr_files() or not all((self.asr_snapshot() / f).is_file() for f in ASR_HASHES):
                raise RuntimeError("語音辨識模型驗證失敗，請按修復。")
            WhisperModel(str(self.asr_snapshot()), device="cpu", compute_type="int8", cpu_threads=2,
                         download_root=str(self.root), local_files_only=True)
        elif component == "diarization":
            from vlt.diarization.sherpa_backend import SEGMENTATION_MODEL_SHA256, EMBEDDING_SHA256
            for name, digest in (("segmentation.onnx", SEGMENTATION_MODEL_SHA256),
                                 ("embedding-campplus.onnx", EMBEDDING_SHA256)):
                file = self.root / "diarization" / name
                if not file.exists() or sha256(file) != digest:
                    raise RuntimeError("Speaker 模型驗證失敗，請按修復。")
        elif component == "translation":
            self.ensure_server()
            payload = json.dumps({"model": "qwen2.5:1.5b"}).encode()
            request = urllib.request.Request("http://127.0.0.1:11434/api/show", payload,
                                             {"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=30) as response:
                if "model_info" not in json.load(response):
                    raise RuntimeError("翻譯模型驗證失敗，請按修復。")
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
        process, self._ollama_process = self._ollama_process, None
        if process is None or process.poll() is not None:
            return
        # Only a runtime launched by this manager is owned here. Snapshot its
        # children before stopping the server: an orphaned runner otherwise loses
        # the server's keep-alive timer and can retain model RAM indefinitely.
        try:
            children = psutil.Process(process.pid).children(recursive=True)
        except psutil.Error:
            children = []
        try:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            logging.warning("Owned translation runtime did not stop cleanly")
        finally:
            for child in children:
                try:
                    child.terminate()
                except psutil.Error:
                    pass
            _, alive = psutil.wait_procs(children, timeout=2)
            for child in alive:
                try:
                    child.kill()
                except psutil.Error:
                    pass
            psutil.wait_procs(alive, timeout=1)
