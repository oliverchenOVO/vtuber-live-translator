from __future__ import annotations

import platform
import subprocess
from dataclasses import asdict, dataclass

import psutil


@dataclass(frozen=True)
class HardwareProfile:
    cpu: str
    logical_cores: int
    ram_gb: float
    gpu: str
    vram_gb: float
    cuda_available: bool

    def to_dict(self) -> dict:
        return asdict(self)


PRESETS = {
    "gaming": {"label": "Gaming", "asr_model": "base", "asr_device": "cpu", "cpu_threads": 2,
               "translation_model": "qwen2.5:1.5b", "translation_fallback": False, "max_speakers": 3,
               "diarization_interval_ms": 5000},
    "balanced": {"label": "Balanced", "asr_model": "base", "asr_device": "auto", "cpu_threads": 4,
                 "translation_model": "qwen2.5:1.5b", "translation_fallback": False, "max_speakers": 4,
                 "diarization_interval_ms": 3000},
    "quality": {"label": "High Quality", "asr_model": "small", "asr_device": "auto", "cpu_threads": 6,
                "translation_model": "qwen2.5:1.5b", "translation_fallback": True, "max_speakers": 4,
                "diarization_interval_ms": 2000},
}


def detect_hardware() -> HardwareProfile:
    gpu, vram = "未偵測到 NVIDIA GPU", 0.0
    try:
        flags = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
        value = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            text=True, timeout=4, creationflags=flags).splitlines()[0]
        gpu, raw_vram = (part.strip() for part in value.rsplit(",", 1))
        vram = round(float(raw_vram) / 1024, 1)
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        pass
    return HardwareProfile(platform.processor() or "Windows CPU", psutil.cpu_count() or 1,
                           round(psutil.virtual_memory().total / 1024 ** 3, 1), gpu, vram, vram > 0)


def recommended_preset(profile: HardwareProfile) -> str:
    if profile.ram_gb < 12 or profile.logical_cores < 6:
        return "gaming"
    if profile.cuda_available and profile.vram_gb >= 10 and profile.ram_gb >= 24:
        return "quality"
    return "balanced"


def preset(name: str) -> dict:
    return dict(PRESETS.get(name, PRESETS["balanced"]))
