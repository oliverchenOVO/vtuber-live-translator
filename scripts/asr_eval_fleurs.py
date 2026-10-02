"""Compare local ASR decoding on FLEURS dev audio with published references.

This diagnostic dataset is public CC BY 4.0 speech, separate from user audio.
It measures clean read-speech recognition, not live VTuber accuracy. The two
downloaded language archives and output stay under ignored data/asr-eval/.
"""
from __future__ import annotations

import argparse
import io
import json
import math
from pathlib import Path
import re
import statistics
import tarfile
import time
import unicodedata

import ctranslate2
from faster_whisper import WhisperModel, decode_audio


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/asr-eval/fleurs"


def edit_distance(reference: list[str], hypothesis: list[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for index, item in enumerate(reference, 1):
        current = [index]
        for column, other in enumerate(hypothesis, 1):
            current.append(min(current[-1] + 1, previous[column] + 1,
                               previous[column - 1] + (item != other)))
        previous = current
    return previous[-1]


def tokens(text: str, language: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text).lower()
    if language == "ja":
        return [char for char in text if not char.isspace()
                and not unicodedata.category(char).startswith("P")]
    return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", text)


def load_samples(language: str, limit: int):
    locale = "ja_jp" if language == "ja" else "en_us"
    rows = []
    for line in (DATA / f"{locale}-dev.tsv").read_text("utf-8").splitlines():
        fields = line.split("\t")
        rows.append({"id": fields[1], "reference": fields[2]})
        if len(rows) >= limit:
            break
    wanted = {item["id"] for item in rows}
    audio = {}
    with tarfile.open(DATA / f"{locale}-dev.tar.gz", "r:gz") as archive:
        for member in archive:
            name = Path(member.name).name
            if name in wanted and member.isfile():
                file = archive.extractfile(member)
                if file is not None:
                    # FLEURS uses IEEE float WAV; PyAV decodes it into the same
                    # mono/16 kHz float32 waveform faster-whisper expects.
                    audio[name] = decode_audio(io.BytesIO(file.read()), sampling_rate=16000)
    if len(audio) != len(wanted):
        raise ValueError(f"Archive had {len(audio)}/{len(wanted)} selected WAVs")
    return [(row, audio[row["id"]]) for row in rows]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--language", choices=("ja", "en"), required=True)
    parser.add_argument("--model", choices=("base", "small"), required=True)
    parser.add_argument("--limit", type=int, default=24)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--auto-language", action="store_true",
                        help="Detect language as the app's Auto setting does")
    parser.add_argument("--model-path", type=Path,
                        help="Existing local CTranslate2 model directory (overrides the app cache)")
    args = parser.parse_args()
    if not 1 <= args.limit <= 200:
        parser.error("limit must be between 1 and 200")
    samples = load_samples(args.language, args.limit)
    use_cuda = ctranslate2.get_cuda_device_count() > 0 if args.device == "auto" else args.device == "cuda"
    device = "cuda" if use_cuda else "cpu"
    model_root = ROOT / "data/phase8-final-soak/models"
    snapshot_root = (model_root if args.model == "base"
                     else ROOT / "data/first-run-managed/models")
    snapshots = snapshot_root / f"models--Systran--faster-whisper-{args.model}/snapshots"
    model_name = str(args.model_path or next(snapshots.iterdir()))
    model = WhisperModel(model_name, download_root=str(model_root), device=device,
                         compute_type="float16" if use_cuda else "int8", cpu_threads=4)
    options = lambda beam: dict(language=None if args.auto_language else args.language,
                                task="transcribe",
                                beam_size=beam, best_of=beam,
                                condition_on_previous_text=False,
                                vad_filter=False, without_timestamps=True)
    for beam in (1, 3, 5):
        segments, _ = model.transcribe(samples[0][1], **options(beam))
        list(segments)  # Exclude lazy model initialization from call timing.
    by_beam = {beam: [] for beam in (1, 3, 5)}
    for index, (row, audio) in enumerate(samples):
        beams = (1, 3, 5)
        beams = beams[index % 3:] + beams[:index % 3]
        for beam in beams:
            started = time.monotonic()
            segments, info = model.transcribe(audio, **options(beam))
            segments = list(segments)
            hypothesis = " ".join(segment.text.strip() for segment in segments).strip()
            logprobs = [float(segment.avg_logprob) for segment in segments
                        if getattr(segment, "avg_logprob", None) is not None]
            confidence = math.exp(sum(logprobs) / len(logprobs)) if logprobs else None
            elapsed = time.monotonic() - started
            reference_units = tokens(row["reference"], args.language)
            errors = edit_distance(reference_units, tokens(hypothesis, args.language))
            by_beam[beam].append({"id": row["id"], "reference": row["reference"],
                "hypothesis": hypothesis, "errors": errors,
                "detected_language": info.language,
                "reference_units": len(reference_units), "elapsed_s": round(elapsed, 3),
                "confidence_proxy": round(confidence, 4) if confidence is not None else None})
    results = {}
    for beam, rows in by_beam.items():
        errors = sum(row["errors"] for row in rows)
        units = sum(row["reference_units"] for row in rows)
        results[str(beam)] = {"error_rate": round(errors / units, 4),
                              "total_errors": errors, "reference_units": units,
                              "mean_call_s": round(statistics.mean(row["elapsed_s"] for row in rows), 3),
                              "wrong_language_count": sum(row["detected_language"] != args.language
                                                          for row in rows),
                              "under_current_0_35_confidence_cutoff": sum(
                                  row["confidence_proxy"] is not None and row["confidence_proxy"] < .35
                                  for row in rows),
                              "rows": rows}
        print(f"{args.language} {args.model} beam={beam}: error_rate={results[str(beam)]['error_rate']}",
              flush=True)
    mode = "-auto" if args.auto_language else ""
    output = DATA / f"{args.language}-{args.model}-{device}-{args.limit}{mode}.json"
    output.write_text(json.dumps({"language": args.language, "model": args.model,
                                  "device": device, "count": len(samples),
                                  "recognition_language": "auto" if args.auto_language else args.language,
                                  "metric": "Japanese character error rate" if args.language == "ja"
                                            else "English word error rate",
                                  "beam_results": results}, ensure_ascii=False, indent=2), "utf-8")


if __name__ == "__main__":
    main()
