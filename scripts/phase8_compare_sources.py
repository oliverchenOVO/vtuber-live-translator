"""Measure a known browser tone in two process-tree captures; no audio files."""
import asyncio
import json
from vlt.audio.windows_process_loopback import WindowsProcessLoopback, enumerate_audio_sources
from verify_isolation import collect, tone_amplitude


async def main():
    available = enumerate_audio_sources()
    records, captures = [], []
    try:
        for label in ("chrome.exe", "msedge.exe"):
            source = next(s for s in available if s.label.lower() == label and s.is_outputting)
            backend = WindowsProcessLoopback()
            await backend.select_source(source.id)
            await backend.start()
            captures.append(backend)
            records.append({"label": label, "pid": source.pid})
        samples = await asyncio.gather(*(collect(backend, 5) for backend in captures))
        for row, sample, backend in zip(records, samples, captures):
            row.update(samples=len(sample), amplitude_1733_hz=tone_amplitude(sample),
                       ring_bound_bytes=backend.buffer.max_bytes)
        print(json.dumps(records, indent=2), flush=True)
    finally:
        for backend in captures:
            await backend.stop()


asyncio.run(main())
