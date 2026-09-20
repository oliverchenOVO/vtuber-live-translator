"""Manual diagnostic for the Windows process capture backend; never saves audio."""

import argparse
import asyncio
import time

from vlt.audio.windows_process_loopback import WindowsProcessLoopback


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int)
    parser.add_argument("--seconds", type=float, default=5)
    args = parser.parse_args()
    backend = WindowsProcessLoopback()
    sources = await backend.list_sources()
    for source in sources:
        print(f"{source.label:32} PID={source.pid:7} outputting={source.is_outputting} peak={source.peak:.3f}")
    if args.pid is None:
        return
    await backend.select_source(str(args.pid))
    await backend.start()
    started = time.monotonic()
    try:
        while time.monotonic() - started < args.seconds:
            print(f"state={backend.state} peak={backend.peak:.3f} buffered={backend.buffer.size_bytes}")
            await asyncio.sleep(0.2)
    finally:
        await backend.stop()


if __name__ == "__main__":
    asyncio.run(main())
