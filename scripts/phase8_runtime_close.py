"""Real managed Ollama runner cleanup on an isolated, temporary localhost port."""
import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import psutil
from vlt.product.models import ModelManager, hidden_process_flags


def main():
    root = Path("data/phase8-runtime-close")
    root.mkdir(parents=True, exist_ok=True)
    executable = Path("data/first-run-managed/runtime/ollama/ollama.exe").resolve()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    env = {**os.environ, "OLLAMA_HOST": f"127.0.0.1:{port}",
           "OLLAMA_MODELS": str(Path.home() / ".ollama" / "models")}
    manager = ModelManager(root / "models", root / "cache", root / "runtime")
    process = subprocess.Popen([str(executable), "serve"], env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=hidden_process_flags())
    manager._ollama_process = process
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            assert process.poll() is None, "Isolated Ollama failed to start"
            try:
                urllib.request.urlopen(base + "/api/tags", timeout=1).close()
                break
            except OSError:
                time.sleep(.2)
        payload = json.dumps({"model": "qwen2.5:1.5b", "prompt": "Say OK.", "stream": False,
                              "keep_alive": "10m", "options": {"num_predict": 1, "num_thread": 1, "num_gpu": 0}}).encode()
        request = urllib.request.Request(base + "/api/generate", payload,
                                         {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=45) as response:
            assert json.load(response).get("done")
        children = psutil.Process(process.pid).children(recursive=True)
        assert children, "A real model runner must have started"
        started = time.monotonic()
        manager.close()
        result = {"server_pid": process.pid, "runner_pids": [p.pid for p in children],
                  "server_stopped": process.poll() is not None,
                  "all_runners_stopped": all(not p.is_running() for p in children),
                  "close_seconds": time.monotonic() - started, "port": port}
        (root / "result.json").write_text(json.dumps(result, indent=2), encoding="utf8")
        print(json.dumps(result), flush=True)
        assert result["server_stopped"] and result["all_runners_stopped"]
    finally:
        manager.close()


if __name__ == "__main__":
    main()
