"""Single CPU translation worker with coalesced partials and durable final backlog."""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable

from vlt.translation.base import TranslationBackend, TranslationRequest


class BoundedTranslationQueue:
    def __init__(self, capacity: int = 12):
        self.capacity = capacity
        self._items: deque[TranslationRequest] = deque()
        self._lock = threading.Condition()
        self.dropped_partials = 0

    def push(self, request: TranslationRequest) -> bool:
        with self._lock:
            if not request.final:
                prior = [item for item in self._items if not item.final and item.segment_id == request.segment_id]
                self.dropped_partials += len(prior)
                self._items = deque(item for item in self._items if item not in prior)
            elif any(item.final and item.segment_id == request.segment_id for item in self._items):
                return False
            if len(self._items) >= self.capacity:
                for item in self._items:
                    if not item.final:
                        self._items.remove(item)
                        self.dropped_partials += 1
                        break
                else:
                    # Finals are already in SQLite as pending and may be retried later.
                    return False
            self._items.append(request)
            self._lock.notify()
            return True

    def pop(self, timeout: float = 0.5) -> TranslationRequest | None:
        with self._lock:
            if not self._items:
                self._lock.wait(timeout)
            if not self._items:
                return None
            for item in self._items:
                if item.final:
                    self._items.remove(item)
                    return item
            return self._items.popleft()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


class TranslationPipeline:
    def __init__(self, backend_factory: Callable[[], TranslationBackend],
                 callback: Callable[[TranslationRequest, str | None, float, str], None],
                 *, capacity: int = 12, partial_interval: float = 1.2):
        self.queue = BoundedTranslationQueue(capacity)
        self.backend_factory = backend_factory
        self.callback = callback
        self.partial_interval = partial_interval
        self._last_partial: dict[str, tuple[float, str]] = {}
        self._deferred_partial: TranslationRequest | None = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._inflight: set[str] = set()
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name="translation-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def submit(self, request: TranslationRequest) -> bool:
        if not request.original.strip():
            return False
        if not request.final:
            last_at, last_text = self._last_partial.get(request.segment_id, (0.0, ""))
            if request.original == last_text:
                return False
            if (time.monotonic() - last_at < self.partial_interval
                 and not request.original.rstrip().endswith(("。", "！", "？", ".", "?", "!"))):
                self._deferred_partial = request  # One latest partial; send even if ASR pauses.
                return True
            self._deferred_partial = None
            self._last_partial[request.segment_id] = (time.monotonic(), request.original)
        else:
            if self._deferred_partial and self._deferred_partial.segment_id == request.segment_id:
                self._deferred_partial = None
            self._last_partial.pop(request.segment_id, None)
            with self._lock:
                if request.segment_id in self._inflight:
                    return False
                self._inflight.add(request.segment_id)
        inserted = self.queue.push(request)
        if request.final and not inserted:
            with self._lock:
                self._inflight.discard(request.segment_id)
        return inserted

    def _run(self) -> None:
        backend = self.backend_factory()
        while self._running:
            request = self.queue.pop()
            if request is None:
                deferred = self._deferred_partial
                if deferred is None:
                    continue
                last_at, _ = self._last_partial.get(deferred.segment_id, (0.0, ""))
                if time.monotonic() - last_at < self.partial_interval:
                    continue
                request = deferred
                self._deferred_partial = None
                self._last_partial[request.segment_id] = (time.monotonic(), request.original)
            started = request.submitted_at  # Includes time waiting in the bounded queue.
            try:
                result = backend.translate_final(request) if request.final else backend.translate_partial(request)
                if self._running:
                    self.callback(request, result, (time.monotonic() - started) * 1000, "")
            except Exception as exc:
                logging.warning("Translation failed: %s", exc)
                if self._running:
                    self.callback(request, None, (time.monotonic() - started) * 1000,
                                  str(exc) if isinstance(exc, RuntimeError) else "翻譯暫時不可用，原文辨識仍在繼續。")
            finally:
                if request.final:
                    with self._lock:
                        self._inflight.discard(request.segment_id)
