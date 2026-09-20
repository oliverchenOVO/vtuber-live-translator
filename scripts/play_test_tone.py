"""Play a synthetic tone from a separate process for loopback isolation QA."""

import argparse
import io
import math
import struct
import time
import wave
import winsound


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=12)
    parser.add_argument("--frequency", type=float, default=1733)
    args = parser.parse_args()
    with io.BytesIO() as output:
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(48000)
            frames = (int(16000 * math.sin(2 * math.pi * args.frequency * i / 48000))
                      for i in range(48000))
            wav.writeframes(b"".join(struct.pack("<h", sample) for sample in frames))
        sound = output.getvalue()
    print(f"tone_pid={__import__('os').getpid()} frequency={args.frequency}", flush=True)
    deadline = time.monotonic() + args.seconds
    while time.monotonic() < deadline:
        winsound.PlaySound(sound, winsound.SND_MEMORY)


if __name__ == "__main__":
    main()
