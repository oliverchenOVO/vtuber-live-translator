"""Manual QA: verify capture reports a closed source without crashing."""

import asyncio
import subprocess
import sys
from pathlib import Path

from vlt.audio.base import AudioSource
from vlt.audio.windows_process_loopback import WindowsProcessLoopback


async def main() -> None:
    tone_script = Path(__file__).with_name("play_test_tone.py")
    process = subprocess.Popen([sys.executable, str(tone_script), "--seconds", "2"],
                               stdout=subprocess.PIPE, text=True,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    backend = None
    try:
        print(process.stdout.readline().strip())
        source = AudioSource(str(process.pid), "python.exe", "process", process.pid, True, 0)
        backend = WindowsProcessLoopback(source_provider=lambda: [source])
        await backend.select_source(source.id)
        await backend.start()
        await asyncio.to_thread(process.wait, 5)
        for _ in range(30):
            if backend.state == "error":
                break
            await asyncio.sleep(0.1)
        print(f"state={backend.state} error={backend.error}")
        if backend.state != "error" or "關閉" not in backend.error:
            raise RuntimeError("Closed-process handling did not reach a readable error state")
    finally:
        if backend:
            await backend.stop()
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=3)


if __name__ == "__main__":
    asyncio.run(main())
