"""Identify which native model lifecycle retains allocations, without saving audio."""
import argparse
import gc
import json
from pathlib import Path

import psutil


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("component", choices=["ct2", "tokenizer", "whisper", "ct2-infer"])
    args = parser.parse_args()
    root = next(Path("data/first-run-managed/models/models--Systran--faster-whisper-base/snapshots").iterdir())
    import ctranslate2
    from tokenizers import Tokenizer
    from faster_whisper import WhisperModel
    import numpy as np
    process = psutil.Process()
    for cycle in range(30):
        if args.component == "tokenizer":
            model = Tokenizer.from_file(str(root / "tokenizer.json"))
            model.encode("Hello world")
        elif args.component == "whisper":
            model = WhisperModel(str(root), device="cpu", compute_type="int8", cpu_threads=2)
            model.model.unload_model()
        else:
            model = ctranslate2.models.Whisper(str(root), device="cpu", compute_type="int8", intra_threads=2)
            if args.component == "ct2-infer":
                features = ctranslate2.StorageView.from_array(np.zeros((1, 80, 3000), dtype="float32"))
                model.detect_language(features)
            model.unload_model()
        del model
        gc.collect()
        print(json.dumps({"component": args.component, "cycle": cycle, "private_mb": process.memory_info().private / 1024**2,
                          "rss_mb": process.memory_info().rss / 1024**2,
                          "handles": process.num_handles(), "threads": process.num_threads()}), flush=True)


if __name__ == "__main__":
    main()
