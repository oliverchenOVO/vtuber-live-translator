"""Verify and repair a deliberately damaged COPY of the downloaded ASR model."""
import json
import shutil
import time
from pathlib import Path

from vlt.product.models import ModelManager

root = Path("data/phase8-model-repair")
root.mkdir(parents=True, exist_ok=True)
shutil.copytree("data/first-run-managed/models", root / "models", dirs_exist_ok=True)
manager = ModelManager(root / "models", root / "cache", root / "runtime")
manager.verify("asr")
target = manager.asr_snapshot() / "model.bin"
# copytree dereferences any source symlinks, so this cannot damage the source cache.
assert not target.is_symlink() and target.resolve().is_relative_to(root.resolve())
with target.open("r+b") as model:
    model.seek(1024); model.write(b"PHASE8-CORRUPTION")
result = {"original_verified": True}
try:
    manager.verify("asr")
    result["corruption_detected"] = False
except RuntimeError:
    result["corruption_detected"] = True
started = time.perf_counter()
manager.install("asr", lambda *_: None)
manager.verify("asr")
result.update(repaired=True, repair_seconds=time.perf_counter() - started)
(root / "result.json").write_text(json.dumps(result, indent=2))
print(json.dumps(result), flush=True)
