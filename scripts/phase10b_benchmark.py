"""Resumable, same-corpus local translation bake-off.

Outputs are evidence, not automatic semantic grades.  `output_rate` only says
that a backend returned text; safe coverage needs independent source review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import statistics
import subprocess
import time
import urllib.request
from pathlib import Path

import psutil

from vlt.translation.base import TranslationRequest
from vlt.translation.madlad_backend import MadladTranslationBackend
from vlt.translation.ollama_backend import OllamaTranslationBackend
from vlt.translation.translategemma_backend import TranslateGemmaBackend


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests/fixtures/translation_bakeoff_650.json"
CRITICAL = ROOT / "tests/fixtures/translation_regression_critical.json"
GLOSSARY = ROOT / "tests/fixtures/translation_bakeoff_glossary.json"
MODEL = Path(os.environ.get(
    "VLT_PHASE10B_MADLAD_DIR", str(ROOT / "data/phase10b/models/madlad400-3b-mt-ct2-int8")))


def backend(name: str):
    if name == "madlad":
        return MadladTranslationBackend(MODEL, device="cpu", cpu_threads=4)
    if name == "gemma":
        return TranslateGemmaBackend()
    if name == "qwen":
        return OllamaTranslationBackend(model="qwen2.5:1.5b", cpu_threads=4,
                                        allow_fallback=False)
    raise ValueError(name)


def gpu_memory_mib() -> int | None:
    try:
        output = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            text=True, timeout=3, stderr=subprocess.DEVNULL)
        return int(output.splitlines()[0].strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def process_memory_mib() -> int:
    total = psutil.Process().memory_info().rss
    for process in psutil.process_iter(["name", "memory_info"]):
        if "ollama" in (process.info["name"] or "").lower():
            total += process.info["memory_info"].rss
    return round(total / 1024**2)


def backend_cpu_seconds() -> float:
    own = psutil.Process().cpu_times()
    total = own.user + own.system
    for process in psutil.process_iter(["name", "cpu_times"]):
        if "ollama" in (process.info["name"] or "").lower():
            times = process.info["cpu_times"]
            total += times.user + times.system
    return total


def ollama_model_bytes(name: str) -> int | None:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3) as response:
            for item in json.load(response).get("models", []):
                if item.get("name") == name:
                    return int(item["size"])
    except (OSError, ValueError, KeyError):
        pass
    return None


def automated_flags(source: str, output: str) -> list[str]:
    if not output:
        return ["empty"]
    flags = []
    source_digits = re.findall(r"\d+(?:[.,]\d+)?", source)
    output_digits = re.findall(r"\d+(?:[.,]\d+)?", output)
    if source_digits != output_digits:
        flags.append("digit_mismatch_review")
    if re.search(r"[ぁ-んァ-ヶ]", output):
        flags.append("untranslated_japanese_review")
    if source.strip() == output.strip():
        flags.append("untranslated_source_review")
    if re.search(r"VLT\s*T\s*E\s*R\s*M", output, re.I):
        flags.append("placeholder_leak")
    if len(output) > max(30, len(source) * 4):
        flags.append("length_expansion_review")
    return flags


def summarize(records: list[dict]) -> dict:
    latencies = sorted(row["elapsed_ms"] for row in records)
    cpu_samples = [row.get("backend_cpu_percent_one_core", row.get("own_cpu_percent_one_core"))
                   for row in records]
    cpu_samples = [value for value in cpu_samples if value is not None]
    percentile = lambda q: latencies[min(len(latencies)-1, round((len(latencies)-1)*q))] if latencies else None
    return {
        "rows": len(records), "output_count": sum(bool(row["translation"]) for row in records),
        "operational_output_rate_not_safe_coverage":
            round(sum(bool(row["translation"]) for row in records) / len(records), 4) if records else None,
        "latency_ms": {"mean": round(statistics.mean(latencies)) if latencies else None,
                       "p50": percentile(.5), "p95": percentile(.95),
                       "max": max(latencies) if latencies else None},
        "peak_process_rss_mib": max((row["process_rss_mib"] for row in records), default=None),
        "peak_gpu_used_mib": max((row["gpu_used_mib"] or 0 for row in records), default=None),
        "mean_backend_cpu_percent_one_core": round(statistics.mean(cpu_samples), 1) if cpu_samples else None,
        "peak_backend_cpu_percent_one_core": max(cpu_samples, default=None),
        "automated_flag_counts": {flag: sum(flag in row["automated_flags"] for row in records)
                                  for flag in sorted({flag for row in records for flag in row["automated_flags"]})},
        "human_semantic_review": "NOT_PERFORMED",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("madlad", "gemma", "qwen"), required=True)
    parser.add_argument("--set", choices=("corpus", "critical", "glossary"), default="corpus")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--target", choices=("zh-TW", "zh-CN"), default="zh-TW")
    args = parser.parse_args()
    path = {"corpus": CORPUS, "critical": CRITICAL, "glossary": GLOSSARY}[args.set]
    content = path.read_bytes()
    rows = json.loads(content)
    output = ROOT / "data/phase10b" / f"{args.backend}-{args.set}-{args.target}.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    prior = ({json.loads(line)["id"] for line in output.read_text(encoding="utf-8").splitlines()}
             if output.exists() else set())
    engine = backend(args.backend)
    gpu_baseline = gpu_memory_mib()
    records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()] if output.exists() else []
    sampled_rss = None
    sampled_gpu = None
    with output.open("a", encoding="utf-8") as stream:
        for index, row in enumerate(rows):
            if args.limit and index >= args.limit:
                break
            uid = row.get("id") or row.get("sample_id")
            if uid in prior:
                continue
            source = row.get("source") or row.get("original")
            request = TranslationRequest(uid, source, row["language"], args.target, "faithful",
                                         glossary=tuple(row.get("glossary", ())), final=True)
            resource_sampled = (index % 10 == 0 or sampled_rss is None)
            before_cpu = backend_cpu_seconds() if resource_sampled else None
            started = time.monotonic()
            try:
                translation = engine.translate_final(request)
                error = ""
            except Exception as exc:
                translation, error = "", f"{type(exc).__name__}: {exc}"
            elapsed = time.monotonic() - started
            after_cpu = backend_cpu_seconds() if resource_sampled else None
            if resource_sampled:
                sampled_rss = process_memory_mib()
                sampled_gpu = gpu_memory_mib()
            record = {
                "id": uid, "backend": args.backend, "language": row["language"],
                "category": row.get("category", "critical"), "provenance": row.get("provenance", "phase9"),
                "source": source, "target": args.target, "translation": translation,
                "error": error, "elapsed_ms": round(elapsed * 1000),
                "backend_cpu_percent_one_core": (round(100 * (after_cpu - before_cpu) / max(elapsed, .001))
                                                 if resource_sampled else None),
                "process_rss_mib": sampled_rss, "gpu_used_mib": sampled_gpu,
                "resource_sampled": resource_sampled,
                "automated_flags": automated_flags(source, translation),
                "semantic_judgement": "UNREVIEWED",
            }
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            stream.flush()
            records.append(record)
            print(f"{len(records)}/{len(rows)} {uid} {record['elapsed_ms']} ms "
                  f"{'OK' if translation else error[:60]}", flush=True)
    model_bytes = ((MODEL / "model.bin").stat().st_size if (MODEL / "model.bin").exists() else None) if args.backend == "madlad" else ollama_model_bytes(
        "translategemma:4b" if args.backend == "gemma" else "qwen2.5:1.5b")
    metadata = {
        "backend": args.backend, "set": args.set, "target": args.target,
        "expected_rows": len(rows), "complete": len(records) == len(rows),
        "corpus_sha256_canonical": hashlib.sha256(json.dumps(
            rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "hardware": {"platform": platform.platform(), "cpu": platform.processor(),
                     "ram_gib": round(psutil.virtual_memory().total / 1024**3, 2)},
        "runtime": "CPU, 4 threads", "model_bytes": model_bytes,
        "gpu_used_baseline_mib_system_wide": gpu_baseline,
        "summary": summarize(records),
    }
    output.with_suffix(".summary.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata["summary"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
