"""Run the real audio → ASR → translation → diarization stack for Phase 10.

Launch Chrome with a speech stream first. This writes transcript and resource
samples to ignored data/phase10/live-soak; it never records raw audio.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import psutil
from PySide6.QtCore import QCoreApplication, QTimer

from vlt.asr.faster_whisper_backend import FasterWhisperBackend
from vlt.database.database import Database
from vlt.diarization.sherpa_backend import SherpaOnnxDiarizationBackend
from vlt.sessions.manager import SessionManager
from vlt.settings.manager import SettingsManager
from vlt.translation.ollama_backend import OllamaTranslationBackend
from vlt.ui.controller import StudioController


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=int, default=30)
    parser.add_argument("--pid", type=int, default=0,
                        help="Chrome root process PID; otherwise choose an outputting chrome.exe")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    root = repo / "data/phase10/live-soak"
    root.mkdir(parents=True, exist_ok=True)
    model_root = repo / "data/phase8-final-soak/models"
    snapshot = next((model_root / "models--Systran--faster-whisper-base/snapshots").iterdir())
    app = QCoreApplication([])
    settings = SettingsManager(root)
    settings.set("source_language", "ja")
    settings.set("target_language", "zh-TW")
    settings.set("performance_preset", "balanced")
    database = Database(root / "app.db")
    sessions = SessionManager(root, database)
    controller = StudioController(
        sessions, settings,
        asr_backend_factory=lambda: FasterWhisperBackend(str(snapshot), model_root, "auto", 4),
        translation_backend_factory=lambda: OllamaTranslationBackend(cpu_threads=4),
        diarization_backend_factory=lambda: SherpaOnnxDiarizationBackend(
            model_root / "diarization", max_speakers=4, process_interval_ms=3000))
    if args.dry_run:
        controller.shutdown()
        database.connection.close()
        print("Phase 10 live harness initialized", flush=True)
        return
    process = psutil.Process()
    process.cpu_percent(None)
    started = time.monotonic()
    capture_started = None
    stopping = False
    stop_requested_at = None
    last_print_slot = -1
    output = (root / "resources.jsonl").open("a", encoding="utf-8")

    def tick() -> None:
        nonlocal capture_started, stopping, stop_requested_at, last_print_slot
        elapsed = time.monotonic() - started
        if capture_started is None:
            sources = [item for item in controller.audioSources if item["label"].lower() == "chrome.exe"
                       and item["isOutputting"] and (not args.pid or item["pid"] == args.pid)]
            if sources and not controller.audioBusy:
                controller.selectAudioSource(sources[0]["id"])
                controller.startAudioCapture()
                capture_started = time.monotonic()
            elif elapsed > 120:
                print("No outputting Chrome source within two minutes", flush=True)
                controller.shutdown()
                output.close()
                app.quit()
            return
        session = controller.selectedSession
        rows = sessions.list_segments(session["session_id"]) if session else []
        speech = [item for item in rows if item.get("type") == "speech"]
        mem = process.memory_info()
        sample = {"elapsed_s": round(elapsed), "capture_s": round(time.monotonic() - capture_started),
                  "app_rss_mb": round(mem.rss / 1024**2, 1),
                  "app_cpu_one_core_percent": round(process.cpu_percent(None), 1),
                  "audio_state": controller.audio.state,
                  "asr_state": controller._asr_state,
                  "segments": len(speech),
                  "translated": sum(bool(item.get("translation")) for item in speech),
                  "pending": sum(not item.get("translation") for item in speech),
                  "uncertain_source": sum(item.get("translation_state") == "uncertain_source"
                                          for item in speech),
                  "rejected": sum(item.get("translation_state") == "rejected" for item in speech),
                  "translation_queue": len(controller._translation_pipeline.queue),
                  "translation_latency_ms": controller._translation_latency_ms,
                  "asr_partial_count": controller._asr_partial_count,
                  "asr_final_count": controller._asr_final_count,
                  "speakers": len(controller._speaker_rows)}
        output.write(json.dumps(sample) + "\n")
        output.flush()
        slot = int(elapsed // 30)
        if slot != last_print_slot:
            print(json.dumps(sample), flush=True)
            last_print_slot = slot
        if not stopping and controller.audio.state != "capturing" and time.monotonic() - capture_started > 120:
            print("Chrome capture did not stay active for two minutes", flush=True)
            controller.shutdown()
            output.close()
            app.quit()
            return
        if not stopping and time.monotonic() - capture_started >= args.minutes * 60:
            stopping = True
            stop_requested_at = time.monotonic()
            controller.finishSession()
        if stopping and session and controller.selectedSession.get("status") == "completed":
            controller.shutdown()
            output.close()
            app.quit()
        elif stopping and stop_requested_at and time.monotonic() - stop_requested_at > 120:
            print("Session did not finish within two minutes; transcript remains recoverable", flush=True)
            controller.shutdown()
            output.close()
            app.quit()

    timer = QTimer()
    timer.setInterval(5000)
    timer.timeout.connect(tick)
    timer.start()
    controller.refreshAudioSources()
    QTimer.singleShot(1000, tick)
    try:
        app.exec()
    finally:
        if not controller._shutting_down:
            controller.shutdown()
        output.close()
        database.connection.close()


if __name__ == "__main__":
    main()
