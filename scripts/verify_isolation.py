"""Live Windows QA: Chrome and a separate synthetic-tone process play together.

Capture is held in RAM only. A strong 1733 Hz component should appear in the
tone process stream and be absent from the Chrome process stream.
"""

import argparse
import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import psutil

from vlt.audio.base import AudioSource
from vlt.audio.windows_process_loopback import WindowsProcessLoopback, enumerate_audio_sources


def tone_amplitude(samples: np.ndarray, frequency: float = 1733) -> float:
    if len(samples) == 0:
        return 0.0
    centered = samples.astype(np.float64) / 32768.0
    window = np.hanning(len(centered))
    phase = np.exp(-2j * np.pi * frequency * np.arange(len(centered)) / 16000)
    return float(2 * np.abs(np.sum(centered * window * phase)) / np.sum(window))


async def collect(backend: WindowsProcessLoopback, seconds: float) -> np.ndarray:
    samples = []
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        chunk = backend.buffer.pop()
        if chunk:
            samples.append(np.frombuffer(chunk.pcm, dtype="<i2").copy())
        await asyncio.sleep(0.01)
    return np.concatenate(samples) if samples else np.empty(0, dtype="<i2")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chrome-pid", type=int, required=True)
    args = parser.parse_args()
    chrome = next((source for source in enumerate_audio_sources() if source.pid == args.chrome_pid), None)
    if chrome is None:
        raise SystemExit("Chrome audio session not found")
    own = psutil.Process()
    print(f"chrome_pid={chrome.pid} capture_process_pid={own.pid}")
    chrome_backend = WindowsProcessLoopback(source_provider=lambda: [chrome])
    await chrome_backend.select_source(chrome.id)
    await chrome_backend.start()
    tone_script = Path(__file__).with_name("play_test_tone.py")
    tone_process = subprocess.Popen([sys.executable, str(tone_script), "--seconds", "12"],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
    tone_backend = None
    try:
        print(tone_process.stdout.readline().strip())
        tone = AudioSource(str(tone_process.pid), "python.exe", "process", tone_process.pid, True, 0)
        tone_backend = WindowsProcessLoopback(source_provider=lambda: [tone])
        await tone_backend.select_source(tone.id)
        await tone_backend.start()
        own.cpu_percent(None)
        chrome_samples, tone_samples = await asyncio.gather(collect(chrome_backend, 3), collect(tone_backend, 3))
        chrome_amp = tone_amplitude(chrome_samples)
        tone_amp = tone_amplitude(tone_samples)
        print(f"chrome_samples={len(chrome_samples)} tone_samples={len(tone_samples)}")
        print(f"chrome_1733_amplitude={chrome_amp:.5f} tone_1733_amplitude={tone_amp:.5f}")
        print(f"ratio={tone_amp / max(chrome_amp, 1e-9):.1f}x")
        print(f"capture_cpu_percent={own.cpu_percent(None):.1f} rss_mib={own.memory_info().rss / 1048576:.1f}")
        print(f"buffer_limit_bytes={chrome_backend.buffer.max_bytes}")
    finally:
        await chrome_backend.stop()
        if tone_backend:
            await tone_backend.stop()
        if tone_process.poll() is None:
            tone_process.terminate()
            tone_process.wait(timeout=3)


if __name__ == "__main__":
    asyncio.run(main())
