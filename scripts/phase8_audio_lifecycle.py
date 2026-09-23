"""Native audio-only repeated activation audit, without ASR or disk audio."""
import asyncio
import gc
import json
import time

import psutil
from comtypes import COMObject
from vlt.audio.windows_process_loopback import WindowsProcessLoopback, enumerate_audio_sources


async def main():
    chrome = next(s for s in enumerate_audio_sources() if s.label.lower() == "chrome.exe")
    p = psutil.Process()
    baseline = p.num_handles()
    for cycle in range(20):
        backend = WindowsProcessLoopback(source_provider=lambda: [chrome])
        await backend.select_source(chrome.id)
        await backend.start()
        await asyncio.sleep(.25)
        await backend.stop()
        print(json.dumps({"cycle": cycle, "handles": p.num_handles(), "baseline": baseline,
                          "private_mb": p.memory_info().private / 1024**2,
                          "com_objects": len(COMObject._instances_)}), flush=True)
    gc.collect()
    print(json.dumps({"after_gc_handles": p.num_handles(), "com_objects": len(COMObject._instances_)}))


asyncio.run(main())
