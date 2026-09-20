"""Bounded in-memory PCM queue. Audio is never written to disk here."""

from collections import deque
from threading import Lock

from vlt.audio.base import AudioChunk


class BoundedAudioBuffer:
    def __init__(self, max_bytes: int = 160_000):
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self.max_bytes = max_bytes
        self._chunks: deque[AudioChunk] = deque()
        self._size = 0
        self._lock = Lock()

    @property
    def size_bytes(self) -> int:
        with self._lock:
            return self._size

    def push(self, chunk: AudioChunk) -> None:
        pcm = chunk.pcm[-self.max_bytes:]
        if not pcm:
            return
        if len(pcm) != len(chunk.pcm):
            chunk = AudioChunk(pcm, chunk.sample_rate, chunk.channels, chunk.timestamp_ms)
        with self._lock:
            self._chunks.append(chunk)
            self._size += len(pcm)
            while self._size > self.max_bytes:
                removed = self._chunks.popleft()
                self._size -= len(removed.pcm)

    def pop(self) -> AudioChunk | None:
        with self._lock:
            if not self._chunks:
                return None
            chunk = self._chunks.popleft()
            self._size -= len(chunk.pcm)
            return chunk

    def clear(self) -> None:
        with self._lock:
            self._chunks.clear()
            self._size = 0
