"""Compare production presets on the same bounded, RAM-only live Chrome sample."""
import argparse
import asyncio
import json
import os
import statistics
import subprocess
import threading
import time
from pathlib import Path

import psutil
from vlt.asr.faster_whisper_backend import FasterWhisperBackend
from vlt.audio.base import AudioChunk
from vlt.audio.windows_process_loopback import WindowsProcessLoopback
from vlt.diarization.sherpa_backend import SherpaOnnxDiarizationBackend
from vlt.product.hardware import preset
from vlt.translation.base import TranslationRequest
from vlt.translation.ollama_backend import OllamaTranslationBackend


def gpu_memory():
    """Windows per-process counters; never attribute system-wide VRAM to this probe."""
    command = (
        "@(Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUProcessMemory "
        f"| Where-Object {{$_.Name -match 'pid_{os.getpid()}_'}} "
        "| Select-Object DedicatedUsage,SharedUsage) | ConvertTo-Json -Compress"
    )
    try:
        raw = subprocess.check_output(["powershell.exe", "-NoProfile", "-Command", command],
                                      text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        rows = json.loads(raw) if raw.strip() else []
        if isinstance(rows, dict):
            rows = [rows]
        return {key: sum(row[key] for row in rows) / 1024**2
                for key in ("DedicatedUsage", "SharedUsage")}
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--download-only", action="store_true")
    parser.add_argument("--language", choices=("ja", "en", "auto"), default="ja")
    parser.add_argument("--seconds", type=int, choices=range(8, 31), default=12)
    args = parser.parse_args()
    model_root = Path("data/first-run-managed/models")
    from faster_whisper.utils import download_model
    small = await asyncio.to_thread(download_model, "small", cache_dir=str(model_root))
    if args.download_only:
        print(json.dumps({"small_ready": small}), flush=True)
        return
    capture = WindowsProcessLoopback()
    chrome = next(s for s in await capture.list_sources() if s.label.lower() == "chrome.exe")
    await capture.select_source(chrome.id)
    await capture.start()
    pcm = bytearray()
    deadline = time.monotonic() + args.seconds + 2
    while time.monotonic() < deadline:
        chunk = capture.buffer.pop()
        if chunk:
            pcm.extend(chunk.pcm)
            del pcm[:max(0, len(pcm) - args.seconds * 32000)]
        await asyncio.sleep(.01)
    await capture.stop()
    assert len(pcm) >= 8 * 32000, "Chrome must be playing speech"
    pcm.extend(b"\0" * 32000)
    results = []
    for name in ("gaming", "balanced", "quality"):
        config = preset(name)
        backend = FasterWhisperBackend(small if name == "quality" else "base", model_root,
                                       config["asr_device"], config["cpu_threads"])
        translator = OllamaTranslationBackend(cpu_threads=config["cpu_threads"], allow_fallback=False)
        speaker = SherpaOnnxDiarizationBackend(model_root / "diarization",
                                              max_speakers=config["max_speakers"],
                                              process_interval_ms=config["diarization_interval_ms"])
        events, pending, translation_times, translations = [], [], [], []
        partial_seen = set()
        translate_gate = asyncio.Lock()
        async def translate(result):
            started = time.monotonic()
            try:
                async with translate_gate:
                    text = await asyncio.to_thread(translator.translate_final,
                        TranslationRequest(result.utterance_id, result.text, result.language, "zh-TW", "natural", final=True))
                translations.append({"original": result.text, "translation": text})
            except RuntimeError as exc:
                translations.append({"original": result.text, "error": str(exc)})
            translation_times.append(time.monotonic() - started)
        def callback(result):
            anchor = result.speech_end_at if result.is_final else result.first_audio_at
            kind = "final" if result.is_final else ("partial" if result.utterance_id in partial_seen else "first_partial")
            partial_seen.add(result.utterance_id)
            events.append({"kind": kind,
                           "latency_s": time.monotonic() - anchor if anchor else None})
            if result.is_final and result.text:
                pending.append(asyncio.create_task(translate(result)))
        backend.set_language(args.language)
        backend.set_callbacks(callback, callback, lambda *_: None)
        process = psutil.Process()
        samples, stop = [], threading.Event()
        def sample():
            process.cpu_percent()
            ollama = {}
            iteration = 0
            while not stop.wait(.25):
                if iteration % 4 == 0:
                    alive = {p.pid: p for p in psutil.process_iter(["name"])
                             if "ollama" in (p.info["name"] or "").lower()}
                    ollama = {pid: ollama.get(pid, p) for pid, p in alive.items()}
                iteration += 1
                translation_cpu, translation_ram = 0.0, 0.0
                for service in ollama.values():
                    try:
                        translation_cpu += service.cpu_percent()
                        translation_ram += service.memory_info().rss / 1024**2
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                mem = process.memory_info()
                samples.append({"cpu": process.cpu_percent(), "rss_mb": mem.rss / 1024**2,
                                "private_mb": mem.private / 1024**2,
                                "ollama_cpu": translation_cpu, "ollama_rss_mb": translation_ram})
        sampler = threading.Thread(target=sample, daemon=True)
        sampler.start()
        started = time.monotonic()
        await backend.start()
        speaker.start()
        startup = time.monotonic() - started
        anchor = int(time.monotonic() * 1000)
        for offset in range(0, len(pcm), 640):
            chunk = AudioChunk(bytes(pcm[offset:offset+640]), 16000, 1, anchor + offset // 32)
            await backend.push_audio(chunk)
            speaker.push_audio(chunk)
            await asyncio.sleep(.02)
        await asyncio.sleep(3)
        gpu = await asyncio.to_thread(gpu_memory)
        await backend.stop()
        speaker.stop()
        await asyncio.gather(*pending)
        stop.set(); sampler.join()
        results.append({"preset": name, "language": args.language, "configuration": config, "correction_7b": False,
                        "pcm_seconds": len(pcm) / 32000,
                        "device": backend._active_device, "model_start_s": startup, "events": events,
                        "cpu_one_core_percent_mean": statistics.mean(s["cpu"] for s in samples),
                        "rss_peak_mb": max(s["rss_mb"] for s in samples),
                        "private_peak_mb": max(s["private_mb"] for s in samples),
                        "process_gpu_mb": gpu,
                        "ollama_cpu_one_core_percent_mean": statistics.mean(s["ollama_cpu"] for s in samples),
                        "ollama_rss_peak_mb": max(s["ollama_rss_mb"] for s in samples),
                        "translation_latency_s": translation_times, "output": translations,
                        "asr_dropped_bytes": backend.queue.dropped_bytes})
        args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf8")
        print(json.dumps({"preset_done": name}), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
