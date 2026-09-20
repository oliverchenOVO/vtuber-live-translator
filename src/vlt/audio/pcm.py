"""Explicit streaming conversion from WASAPI PCM to ASR-ready mono 16 kHz PCM."""

import numpy as np
import soxr


class PcmConverter:
    def __init__(self, input_rate: int = 44_100, input_channels: int = 2):
        if input_rate <= 0 or input_channels <= 0:
            raise ValueError("Invalid input audio format")
        self.input_rate = input_rate
        self.input_channels = input_channels
        self.output_rate = 16_000
        self.output_channels = 1
        self.output_dtype = "int16"
        self._resampler = soxr.ResampleStream(input_rate, self.output_rate, 1, dtype="float32", quality="HQ")

    def convert(self, pcm: bytes) -> bytes:
        if len(pcm) % (2 * self.input_channels):
            raise ValueError("PCM packet is not aligned to complete frames")
        if not pcm:
            return b""
        # WASAPI stream: interleaved signed little-endian 16-bit samples.
        frames = np.frombuffer(pcm, dtype="<i2").reshape(-1, self.input_channels)
        mono = frames.astype(np.float32).mean(axis=1) / 32768.0
        resampled = self._resampler.resample_chunk(mono)
        scaled = np.clip(np.rint(resampled * 32768.0), -32768, 32767).astype("<i2")
        return scaled.tobytes()

    def finish(self) -> bytes:
        """Drain resampler delay when an audio stream ends."""
        tail = self._resampler.resample_chunk(np.empty(0, dtype=np.float32), last=True)
        return np.clip(np.rint(tail * 32768.0), -32768, 32767).astype("<i2").tobytes()

    @staticmethod
    def peak(pcm: bytes) -> float:
        if not pcm:
            return 0.0
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.int32)
        return float(np.max(np.abs(samples)) / 32768.0)
