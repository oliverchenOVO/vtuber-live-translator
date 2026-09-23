"""Separate native ASR/Speaker lifetimes; captured PCM is bounded and stays in RAM."""
import argparse
import asyncio
import gc
import json
import time
import weakref
from pathlib import Path

import psutil
from vlt.asr.faster_whisper_backend import FasterWhisperBackend
from vlt.audio.base import AudioChunk
from vlt.audio.windows_process_loopback import WindowsProcessLoopback
from vlt.diarization.sherpa_backend import SherpaOnnxDiarizationBackend


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("component", choices=["asr", "speaker"])
    args = parser.parse_args()
    capture = WindowsProcessLoopback()
    chrome = next(s for s in await capture.list_sources() if s.label.lower() == "chrome.exe")
    await capture.select_source(chrome.id); await capture.start()
    pcm = bytearray()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        chunk = capture.buffer.pop()
        if chunk:
            pcm.extend(chunk.pcm)
            del pcm[:max(0, len(pcm) - 8 * 32000)]
        await asyncio.sleep(.01)
    await capture.stop()
    assert len(pcm) >= 6 * 32000
    process = psutil.Process()
    for i in range(20):
        if args.component == "asr":
            backend = FasterWhisperBackend("base", Path("data/first-run-managed/models"), device="cpu", cpu_threads=2)
            await backend.start()
            await asyncio.to_thread(backend._transcribe, bytes(pcm))
            await backend.stop()
        else:
            backend = SherpaOnnxDiarizationBackend(Path("data/first-run-managed/models/diarization"))
            backend.start()
            deadline = time.monotonic() + 30
            while backend.status != "live" and time.monotonic() < deadline:
                await asyncio.sleep(.05)
            for offset in range(0, len(pcm), 32000):
                backend.push_audio(AudioChunk(bytes(pcm[offset:offset+32000]), 16000, 1, 1000 + offset // 32))
            while not backend.processed_windows and time.monotonic() < deadline:
                await asyncio.sleep(.05)
            assert backend.processed_windows
            backend.stop()
        reference = weakref.ref(backend)
        del backend
        before = process.memory_info().private / 1024**2
        collected = gc.collect()
        print(json.dumps({"component": args.component, "cycle": i, "private_before_gc_mb": before,
                          "private_after_gc_mb": process.memory_info().private / 1024**2,
                          "backend_released": reference() is None, "collected": collected,
                          "handles": process.num_handles(), "threads": process.num_threads()}), flush=True)


asyncio.run(main())
