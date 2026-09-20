"""Manual Windows acceptance probe; keeps only transcript and metrics, never PCM."""

import argparse
import asyncio
import json
import tempfile
import time
import sys
from pathlib import Path

import psutil

from vlt.asr.faster_whisper_backend import FasterWhisperBackend
from vlt.asr.pipeline import ASRPipeline
from vlt.audio.windows_process_loopback import WindowsProcessLoopback
from vlt.database.database import Database
from vlt.sessions.manager import SessionManager
from vlt.subtitles.live import TranscriptCoordinator


async def probe(args):
    audio = WindowsProcessLoopback()
    sources = await audio.list_sources()
    chrome = next((source for source in sources if source.label.lower() == "chrome.exe"), None)
    if chrome is None:
        raise RuntimeError("Chrome audio source unavailable; play a video first")
    await audio.select_source(chrome.id)
    await audio.start()
    root = Path(tempfile.mkdtemp(prefix="vlt-asr-probe-"))
    db = Database(root / "app.db")
    sessions = SessionManager(root, db)
    session = sessions.create(source_language=args.language)
    transcript = TranscriptCoordinator(sessions, session["session_id"])
    partials = []
    finals = []
    states = []
    process = psutil.Process()
    process.cpu_percent(None)
    ram_max = 0
    cpu_samples = []
    peak_max = 0

    def partial(result):
        transcript.apply_partial(result)
        partials.append(result.text)
        print("PARTIAL", result.language, repr(result.text), flush=True)

    def final(result):
        if transcript.apply_final(result):
            finals.append(result.text)
            print("FINAL", result.language, repr(result.text), flush=True)

    def status(state, message):
        states.append(state)
        print("STATUS", state, message, flush=True)

    pipeline = ASRPipeline(audio, lambda: FasterWhisperBackend(
        model_dir=Path("data/models")), args.language, partial, final, status)
    task = asyncio.create_task(pipeline.run())
    start = time.monotonic()
    while time.monotonic() - start < args.seconds:
        await asyncio.sleep(1)
        peak_max = max(peak_max, audio.peak)
        ram_max = max(ram_max, process.memory_info().rss)
        cpu_samples.append(process.cpu_percent(None))
    pipeline.stop()
    await audio.stop()
    await task
    sessions.finish(session["session_id"])
    report = {
        "source": chrome.label, "pid": chrome.pid, "language": args.language,
        "seconds": args.seconds, "peak_max": peak_max,
        "partials": len(partials), "finals": len(finals),
        "partial_text": partials[:5], "final_text": finals,
        "partial_latency_ms": transcript.partial_latency_ms,
        "final_latency_ms": transcript.final_latency_ms,
        "cpu_percent_mean": sum(cpu_samples) / len(cpu_samples),
        "ram_max_mb": round(ram_max / 1024 / 1024, 1),
        "states": states,
        "session_dir": session["folder_path"],
        "db_segments": len(sessions.list_segments(session["session_id"])),
    }
    print("REPORT", json.dumps(report, ensure_ascii=False), flush=True)
    db.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--language", choices=["auto", "ja", "en"], default="auto")
    parser.add_argument("--seconds", type=int, default=35)
    asyncio.run(probe(parser.parse_args()))
