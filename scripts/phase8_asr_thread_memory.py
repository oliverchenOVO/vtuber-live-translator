"""Isolate native memory retained when one ASR model sees different worker threads."""
import asyncio
import gc
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psutil
from vlt.asr.faster_whisper_backend import FasterWhisperBackend
from vlt.audio.windows_process_loopback import WindowsProcessLoopback


async def main():
    capture = WindowsProcessLoopback()
    chrome = next(s for s in await capture.list_sources() if s.label.lower() == "chrome.exe")
    await capture.select_source(chrome.id)
    await capture.start()
    pcm = bytearray()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        chunk = capture.buffer.pop()
        if chunk:
            pcm.extend(chunk.pcm)
            del pcm[:max(0, len(pcm) - 8 * 32000)]
        await asyncio.sleep(.01)
    await capture.stop()
    assert len(pcm) >= 4 * 32000
    backend = FasterWhisperBackend("base", Path("data/first-run-managed/models"), "cpu", 2)
    backend.set_language("ja")
    await backend.start()
    process = psutil.Process()
    results = []
    def sample(label):
        gc.collect()
        row = {"stage": label, "private_mib": process.memory_info().private / 1024**2,
               "rss_mib": process.memory_info().rss / 1024**2, "threads": process.num_threads()}
        results.append(row)
        print(json.dumps(row), flush=True)
    pools = [ThreadPoolExecutor(max_workers=1) for _ in range(8)]
    try:
        sample("model_loaded")
        for cycle in range(2):
            for index, pool in enumerate(pools):
                await asyncio.get_running_loop().run_in_executor(pool, backend._transcribe, bytes(pcm))
                sample(f"pass_{cycle + 1}_thread_{index + 1}")
    finally:
        for pool in pools:
            pool.shutdown(wait=True)
        sample("worker_threads_closed")
        await backend.stop()
        sample("model_stopped")
    Path("data/phase8-asr-thread-memory.json").write_text(json.dumps(results, indent=2), encoding="utf8")


if __name__ == "__main__":
    asyncio.run(main())
