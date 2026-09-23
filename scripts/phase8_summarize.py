"""Summarize recorded resource samples without reading or exporting transcript text."""
import argparse
import json
import re
import statistics
from pathlib import Path


def slope(rows, key):
    points = [(row["elapsed_s"] / 60, row[key]) for row in rows if isinstance(row.get(key), (float, int))]
    if len(points) < 2:
        return None
    x0, y0 = (statistics.mean(p[i] for p in points) for i in (0, 1))
    denominator = sum((x - x0) ** 2 for x, _ in points)
    return sum((x - x0) * (y - y0) for x, y in points) / denominator if denominator else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--idle-start", type=float, default=120)
    parser.add_argument("--idle-end", type=float, default=None)
    args = parser.parse_args()
    rows = [json.loads(line) for line in (args.root / "resources.jsonl").read_text("utf8").splitlines()]
    active = [row for row in rows if 60 <= row["elapsed_s"] <= args.idle_start * 60]
    steady = [row for row in active if row["elapsed_s"] >= 15 * 60]
    second_hour = [row for row in active if row["elapsed_s"] >= 60 * 60]
    last_half_hour = [row for row in active if row["elapsed_s"] >= (args.idle_start - 30) * 60]
    idle = [row for row in rows if row["elapsed_s"] >= (args.idle_start + 2) * 60
            and (args.idle_end is None or row["elapsed_s"] <= args.idle_end * 60)]
    table = []
    for minute in range(15, int(rows[-1]["elapsed_s"] / 60) + 1, 15):
        row = min(rows, key=lambda row: abs(row["elapsed_s"] - minute * 60))
        table.append(row)
    result = {"sample_count": len(rows), "observed_minutes": rows[-1]["elapsed_s"] / 60,
              "active_private_mb_per_min": slope(active, "private_mb"),
              "after_15_min_private_mb_per_min": slope(steady, "private_mb"),
              "second_hour_private_mb_per_min": slope(second_hour, "private_mb"),
              "last_30_active_min_private_mb_per_min": slope(last_half_hour, "private_mb"),
              "idle_private_mb_per_min": slope(idle, "private_mb"),
              "quarter_hour_samples": table}
    latencies = {}
    for log in (args.root / "logs").glob("app.log*"):
        for family, kind, milliseconds in re.findall(
                r"(ASR|Translation) latency: kind=(\w+) ms=([\d.]+)",
                log.read_text("utf8", errors="replace")):
            latencies.setdefault(f"{family}_{kind}", []).append(float(milliseconds) / 1000)
    result["latency_seconds"] = {
        key: {"count": len(values), "mean": statistics.mean(values),
              "median": statistics.median(values), "p95": sorted(values)[max(0, int(len(values) * .95) - 1)],
              "max": max(values)} for key, values in latencies.items()}
    result["pipeline_maxima"] = {
        key: max((float(row.get("pipeline", {}).get(key, 0)) for row in rows), default=0)
        for key in ("asr_queue_bytes", "asr_dropped", "translation_queue", "diarization_queue", "dropped")}
    for label, group in (("active", active), ("idle", idle)):
        if group:
            result[label] = {key + "_mean": statistics.mean(row[key] for row in group)
                             for key in ("cpu_one_core_percent", "rss_mb", "private_mb", "ollama_rss_mb", "ollama_cpu_one_core_percent")}
            result[label].update(private_min_mb=min(row["private_mb"] for row in group),
                                 private_max_mb=max(row["private_mb"] for row in group),
                                 segments_first=group[0]["segments"], segments_last=group[-1]["segments"],
                                 speakers_first=group[0]["speakers"], speakers_last=group[-1]["speakers"])
    (args.root / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
