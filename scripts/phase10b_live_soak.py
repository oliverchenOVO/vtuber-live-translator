"""Actual Chrome Process Loopback → ASR → candidate MT soak, no raw audio saved.

This candidate validation does not change the product's default backend.
Start a spoken Japanese or English Chrome stream before running this script.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import statistics
import time
from pathlib import Path

import psutil
from PySide6.QtCore import QCoreApplication, QTimer

from vlt.asr.faster_whisper_backend import FasterWhisperBackend
from vlt.database.database import Database
from vlt.diarization.sherpa_backend import SherpaOnnxDiarizationBackend
from vlt.sessions.manager import SessionManager
from vlt.settings.manager import SettingsManager
from vlt.ui.controller import StudioController

from phase10b_benchmark import ROOT, backend, gpu_memory_mib


def ollama_resources() -> tuple[float, float]:
    rss = cpu = 0.0
    for process in psutil.process_iter(["name", "memory_info"]):
        if "ollama" in (process.info["name"] or "").lower():
            rss += process.info["memory_info"].rss / 1024**2
            cpu += process.cpu_percent(None)
    return round(rss, 1), round(cpu, 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("madlad", "gemma"), required=True)
    parser.add_argument("--language", choices=("ja", "en"), required=True)
    parser.add_argument("--minutes", type=int, required=True)
    parser.add_argument("--pid", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    root = ROOT / "data/phase10b" / f"live-{args.backend}-{args.language}"
    root.mkdir(parents=True, exist_ok=True)
    model_root = ROOT / "data/phase8-final-soak/models"
    snapshot = next((model_root / "models--Systran--faster-whisper-base/snapshots").iterdir())
    app = QCoreApplication([])
    settings = SettingsManager(root)
    settings.set("source_language", args.language)
    settings.set("target_language", "zh-TW")
    settings.set("translation_style", "faithful")
    settings.set("performance_preset", "balanced")
    database = Database(root / "app.db")
    sessions = SessionManager(root, database)
    controller = StudioController(
        sessions, settings,
        asr_backend_factory=lambda: FasterWhisperBackend(str(snapshot), model_root, "auto", 4),
        translation_backend_factory=lambda: backend(args.backend),
        diarization_backend_factory=lambda: SherpaOnnxDiarizationBackend(
            model_root / "diarization", max_speakers=4, process_interval_ms=3000))
    controller._translation_pipeline.partial_interval = .45
    controller._translation_pipeline.stale_after_s = 10
    if args.dry_run:
        controller.shutdown()
        database.connection.close()
        print("Phase 10B live harness initialized", flush=True)
        return
    metrics = []
    final_latencies = []
    errors = []
    process = psutil.Process()
    process.cpu_percent(None)
    started = time.monotonic()
    capture_started = None
    stop_requested = None
    peak_queue = 0
    peak_age_ms = 0
    last_print_slot = -1
    output = (root / "resources.jsonl").open("a", encoding="utf-8")
    gpu_baseline = gpu_memory_mib()

    def on_translation(request, result, latency, error):
        if request.final:
            if result:
                final_latencies.append(latency)
            if error:
                errors.append({"id": request.segment_id, "error": error[:120]})

    controller.translationReady.connect(on_translation)

    def finish(reason: str) -> None:
        nonlocal stop_requested
        if stop_requested is not None:
            return
        stop_requested = time.monotonic()
        print(reason, flush=True)
        controller._translation_pipeline.set_live_mode(False)
        controller.finishSession()

    def tick() -> None:
        nonlocal capture_started, peak_queue, peak_age_ms, last_print_slot
        elapsed = time.monotonic() - started
        if capture_started is None:
            sources = [item for item in controller.audioSources if item["label"].lower() == "chrome.exe"
                       and item["isOutputting"] and (not args.pid or item["pid"] == args.pid)]
            if sources and not controller.audioBusy:
                controller.selectAudioSource(sources[0]["id"])
                controller.startAudioCapture()
                controller._translation_pipeline.set_live_mode(True)
                capture_started = time.monotonic()
            elif elapsed > 120:
                print("No outputting Chrome source within two minutes", flush=True)
                app.quit()
            return
        session = controller.selectedSession
        rows = sessions.list_segments(session["session_id"]) if session else []
        speech = [item for item in rows if item.get("type") == "speech"]
        queue = controller._translation_pipeline.metrics()
        ollama_rss, ollama_cpu = ollama_resources()
        peak_queue = max(peak_queue, queue["queue_depth"])
        peak_age_ms = max(peak_age_ms, queue["oldest_age_ms"])
        sample = {"elapsed_s": round(elapsed),
                  "capture_s": round(time.monotonic() - capture_started),
                  "app_rss_mib": round(process.memory_info().rss / 1024**2, 1),
                  "app_cpu_percent_one_core": round(process.cpu_percent(None), 1),
                  "ollama_rss_mib": ollama_rss, "ollama_cpu_percent_one_core": ollama_cpu,
                  "gpu_used_mib_system_wide": gpu_memory_mib(),
                  "audio_state": controller.audio.state, "asr_state": controller._asr_state,
                  "finals": len(speech),
                  "translated": sum(bool(item.get("translation")) for item in speech),
                  "pending": sum(not item.get("translation") for item in speech),
                  "translation_latency_smoothed_ms": controller._translation_latency_ms,
                  "asr_partials": controller._asr_partial_count,
                  "asr_finals": controller._asr_final_count, **queue}
        output.write(json.dumps(sample, ensure_ascii=False) + "\n")
        output.flush()
        metrics.append(sample)
        slot = int(elapsed // 30)
        if slot != last_print_slot:
            print(json.dumps(sample, ensure_ascii=False), flush=True)
            last_print_slot = slot
        if controller.audio.state != "capturing" and stop_requested is None and sample["capture_s"] > 120:
            finish("Chrome capture stopped before the required duration")
        if stop_requested is None and sample["capture_s"] >= args.minutes * 60:
            finish("Requested live duration reached")
        if stop_requested is not None and session and controller.selectedSession.get("status") == "completed":
            app.quit()
        elif stop_requested is not None and time.monotonic() - stop_requested > 120:
            print("Session finalization timed out; data remains recoverable", flush=True)
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
        session = controller.selectedSession
        rows = sessions.list_segments(session["session_id"]) if session else []
        speech = [item for item in rows if item.get("type") == "speech"]
        eligible = [item for item in speech if item.get("translation_state") != "uncertain_source"]
        latencies = sorted(final_latencies)
        percentile = lambda q: latencies[round((len(latencies)-1)*q)] if latencies else None
        summary = {"backend": args.backend, "language": args.language,
                   "requested_minutes": args.minutes,
                   "actual_capture_seconds": round(time.monotonic() - capture_started, 1) if capture_started else 0,
                   "finals": len(speech),
                   "translated": sum(bool(item.get("translation")) for item in speech),
                   "pending": sum(not item.get("translation") for item in speech),
                   "translation_state_counts": dict(Counter(item.get("translation_state") for item in speech)),
                   "eligible_finals": len(eligible),
                   "eligible_translated": sum(bool(item.get("translation")) for item in eligible),
                   "eligible_pending": sum(not item.get("translation") for item in eligible),
                   "final_latency_p50_ms": percentile(.5),
                   "final_latency_p95_ms": percentile(.95),
                   "queue_max_depth": peak_queue, "queue_max_age_ms": peak_age_ms,
                   "peak_recent_output_segments_per_minute": max(
                       (item["throughput_finals_per_minute"] for item in metrics), default=0),
                   "errors": errors, "session_id": session.get("session_id") if session else None,
                   "app_rss_peak_mib": max((item["app_rss_mib"] for item in metrics), default=None),
                   "ollama_rss_peak_mib": max((item["ollama_rss_mib"] for item in metrics), default=None),
                   "gpu_used_baseline_mib_system_wide": gpu_baseline,
                   "gpu_used_peak_mib_system_wide": max((item["gpu_used_mib_system_wide"] or 0
                                                         for item in metrics), default=None),
                   "app_cpu_mean_percent_one_core": round(statistics.mean(
                       item["app_cpu_percent_one_core"] for item in metrics), 1) if metrics else None}
        (root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False), flush=True)
        if not controller._shutting_down:
            controller.shutdown()
        output.close()
        database.connection.close()


if __name__ == "__main__":
    main()
