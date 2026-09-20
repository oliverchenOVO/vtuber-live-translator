"""A fixed-size ASR handoff queue. Oldest audio is dropped under sustained load."""

import asyncio
from collections import deque

from vlt.audio.base import AudioChunk


class BoundedAudioQueue:
    def __init__(self, max_bytes: int = 128_000):
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self.max_bytes = max_bytes
        self._chunks: deque[AudioChunk] = deque()
        self._bytes = 0
        self._available = asyncio.Event()
        self.dropped_bytes = 0

    @property
    def size_bytes(self) -> int:
        return self._bytes

    def push(self, chunk: AudioChunk) -> None:
        if len(chunk.pcm) > self.max_bytes:
            self.dropped_bytes += len(chunk.pcm) - self.max_bytes
            chunk = AudioChunk(chunk.pcm[-self.max_bytes:], chunk.sample_rate,
                               chunk.channels, chunk.timestamp_ms)
        self._chunks.append(chunk)
        self._bytes += len(chunk.pcm)
        while self._bytes > self.max_bytes:
            old = self._chunks.popleft()
            self._bytes -= len(old.pcm)
            self.dropped_bytes += len(old.pcm)
        self._available.set()

    async def pop(self) -> AudioChunk:
        while not self._chunks:
            self._available.clear()
            await self._available.wait()
        chunk = self._chunks.popleft()
        self._bytes -= len(chunk.pcm)
        return chunk

    def clear(self) -> None:
        self._chunks.clear()
        self._bytes = 0
        self._available.clear()
