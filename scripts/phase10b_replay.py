"""Replay persisted Phase 10 ASR Finals at their original 30-minute timestamps.

No audio is loaded or written.  The worker receives the same TranslationRequest
objects as Studio and must clear its bounded queue before the replay finishes.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path

from vlt.translation.base import TranslationRequest
from vlt.translation.pipeline import TranslationPipeline

from phase10b_benchmark import ROOT, backend


def load_final_rows() -> list[dict]:
    connection = sqlite3.connect(ROOT / "data/phase10/live-soak/app.db")
    try:
        rows = [json.loads(row[0]) for row in connection.execute(
            "SELECT payload_json FROM segments WHERE type='speech' ORDER BY start_ms, segment_id")]
    finally:
        connection.close()
    assert len(rows) == 193
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("madlad", "gemma"), required=True)
    parser.add_argument("--speed", type=float, default=1.0,
                        help="Use 1.0 for the required real-time replay; higher is diagnostic only")
    args = parser.parse_args()
    if args.speed <= 0:
        raise ValueError("speed must be positive")
    rows = load_final_rows()
    output = ROOT / "data/phase10b" / f"replay-{args.backend}-{args.speed:g}x.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    events = []
    started = time.monotonic()

    def finished(request: TranslationRequest, text: str | None, latency: float, error: str) -> None:
        events.append({"id": request.segment_id, "start_ms": next(
            row["start_ms"] for row in rows if row["id"] == request.segment_id),
            "received_at_s": round(time.monotonic() - started, 3),
            "translation": text or "", "error": error,
            "end_to_end_latency_ms": round(latency)})

    pipeline = TranslationPipeline(lambda: backend(args.backend), finished, partial_interval=.45)
    pipeline.start()
    max_depth = 0
    max_age = 0
    snapshots = []
    first_start_ms = rows[0]["start_ms"]
    last_slot = -1
    try:
        for row in rows:
            due = (row["start_ms"] - first_start_ms) / 1000 / args.speed
            while time.monotonic() - started < due:
                slot = int(time.monotonic() - started) // 5
                if slot != last_slot:
                    metric = pipeline.metrics()
                    snapshots.append({"at_s": round(time.monotonic() - started, 2), **metric})
                    max_depth = max(max_depth, metric["queue_depth"])
                    max_age = max(max_age, metric["oldest_age_ms"])
                    last_slot = slot
                time.sleep(max(0.0, min(.25, due - (time.monotonic() - started))))
            request = TranslationRequest(
                row["id"], row["original"], row["language"], "zh-TW", "faithful", final=True)
            accepted = pipeline.submit(request)
            metric = pipeline.metrics()
            max_depth = max(max_depth, metric["queue_depth"])
            max_age = max(max_age, metric["oldest_age_ms"])
            if not accepted:
                events.append({"id": request.segment_id, "start_ms": row["start_ms"],
                               "received_at_s": round(time.monotonic() - started, 3),
                               "translation": "", "error": "queue_full_durable_pending",
                               "end_to_end_latency_ms": None})
        deadline = time.monotonic() + 120
        while pipeline.pending_final_count() and time.monotonic() < deadline:
            time.sleep(.25)
    finally:
        pipeline.stop()
    with output.open("w", encoding="utf-8") as stream:
        for event in events:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
    latencies = sorted(event["end_to_end_latency_ms"] for event in events
                       if event["end_to_end_latency_ms"] is not None)
    duration_s = time.monotonic() - started
    translated_count = sum(bool(event["translation"]) for event in events)
    summary = {"backend": args.backend, "speed": args.speed,
               "source_rows": len(rows), "duration_s": round(duration_s, 1),
               "translated": translated_count,
               "pending": sum(not event["translation"] for event in events),
               "average_output_segments_per_minute": round(translated_count * 60 / duration_s, 2),
               "peak_recent_output_segments_per_minute": max(
                   (item["throughput_finals_per_minute"] for item in snapshots), default=0),
               "queue_max_depth": max_depth, "queue_oldest_age_max_ms": max_age,
               "latency_p50_ms": latencies[round((len(latencies)-1)*.5)] if latencies else None,
               "latency_p95_ms": latencies[round((len(latencies)-1)*.95)] if latencies else None,
               "snapshots": snapshots}
    output.with_suffix(".summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "snapshots"},
                     ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
