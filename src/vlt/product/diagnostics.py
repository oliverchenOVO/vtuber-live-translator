"""Privacy-preserving support archive: no arbitrary settings or raw log lines."""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

from vlt.product.compatibility import windows_build
from vlt.product.models import OLLAMA_VERSION
from vlt.version import __version__


def export_diagnostics(destination: Path, settings: dict, hardware: dict, logs: Path) -> Path:
    safe = {}
    enums = {"source_language": {"ja", "en", "auto"}, "target_language": {"zh-TW", "zh-CN"},
             "performance_preset": {"gaming", "balanced", "quality"},
             "overlay_mode": {"gaming", "watching", "minimal"},
             "translation_style": {"natural", "faithful", "minimal"}}
    for key, allowed in enums.items():
        value = settings.get(key)
        if isinstance(value, str) and value in allowed:
            safe[key] = value
    summary = {"app_version": __version__, "windows_build": windows_build(),
               "settings": safe,
               "hardware": {key: value for key, value in hardware.items()
                            if key in ("logical_cores", "ram_gb", "vram_gb", "cuda_available")
                            and type(value) in (int, float, bool)},
               "models": {"ollama_runtime": OLLAMA_VERSION,
                          "asr": "faster-whisper base/small", "translation": "qwen2.5:1.5b",
                          "speaker": "pyannote 3.0 int8 / CampPlus"}}
    metrics = []
    # Parse only numeric metrics; never include exception messages, prompts or paths.
    for file in sorted(logs.glob("app.log*"))[:6]:
        with file.open("r", encoding="utf-8", errors="replace") as source:
            for line in source:
                if "Pipeline metrics:" in line:
                    allowed = {"partials", "finals", "audio_peak", "asr_queue_bytes", "asr_dropped",
                               "gap_finals", "infer_pending", "windows", "dropped",
                               "translation_queue", "diarization_queue"}
                    metrics.append({key: float(value) for key, value in
                                    re.findall(r"\b(\w+)=(\d+(?:\.\d+)?)\b", line) if key in allowed})
                    metrics = metrics[-300:]
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(".zip.tmp")
    with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("diagnostics.json", json.dumps(summary, ensure_ascii=False, indent=2))
        archive.writestr("recent-metrics.json", json.dumps(metrics))
        archive.writestr("PRIVACY.txt", "No transcripts, audio, credentials, paths, identities or embeddings included.\n"
                          "Logs are limited to parsed numeric pipeline metrics.\n")
    temp.replace(destination)
    return destination
