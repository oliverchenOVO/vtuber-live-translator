import asyncio
import os
import threading
import time

import numpy as np
import pytest

from vlt.audio.base import AudioChunk, AudioSource
from vlt.audio.buffer import BoundedAudioBuffer
from vlt.audio.pcm import PcmConverter
from vlt.audio import windows_process_loopback as module


def run(coro):
    return asyncio.run(coro)


def test_audio_source_enumeration(monkeypatch):
    class Process:
        pid = 123
        def name(self): return "chrome.exe"
        def parent(self): return None
        def is_running(self): return True

    class Meter:
        def GetPeakValue(self): return 0.25

    class Control:
        def QueryInterface(self, _interface): return Meter()

    class Session:
        pass

    Session.Process = Process()
    Session._ctl = Control()

    monkeypatch.setattr(module, "_render_sessions", lambda: [Session()])
    sources = module.enumerate_audio_sources()
    assert [(s.label, s.pid, s.is_outputting) for s in sources] == [("chrome.exe", 123, True)]


def test_source_selection_and_capture(monkeypatch):
    monkeypatch.setattr(module.platform, "version", lambda: "10.0.26200")
    source = AudioSource(str(os.getpid()), "test.exe", "process", os.getpid(), True, 0.3)
    frame = np.full((441, 2), 8000, dtype="<i2").tobytes()

    def fake_capture(_pid, stop, on_pcm, ready, alive):
        assert alive()
        ready()
        for _ in range(20):
            on_pcm(frame)
        stop.wait(1)

    backend = module.WindowsProcessLoopback(source_provider=lambda: [source], capture_function=fake_capture)
    run(backend.select_source(source.id))
    assert backend.selected == source
    run(backend.start())
    assert backend.state == "capturing"
    deadline = time.monotonic() + 1
    while backend.buffer.size_bytes == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert backend.buffer.size_bytes > 0
    assert backend.peak > 0
    run(backend.stop())
    assert backend.buffer.size_bytes == 0


def test_process_closed_is_human_readable(monkeypatch):
    monkeypatch.setattr(module.platform, "version", lambda: "10.0.26200")
    source = AudioSource(str(os.getpid()), "closed.exe", "process", os.getpid(), False, 0)

    def closed_capture(_pid, _stop, _on_pcm, ready, _alive):
        ready()
        raise ProcessLookupError("closed")

    backend = module.WindowsProcessLoopback(source_provider=lambda: [source], capture_function=closed_capture)
    run(backend.select_source(source.id))
    try:
        run(backend.start())
    except RuntimeError:
        pass
    deadline = time.monotonic() + 1
    while backend.state != "error" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert backend.state == "error"
    assert "關閉" in backend.error
    run(backend.stop())


def test_source_can_be_selected_after_it_reappears():
    source = AudioSource("456", "chrome.exe", "process", 456, False, 0)
    available = []
    backend = module.WindowsProcessLoopback(source_provider=lambda: available)
    with pytest.raises(ValueError, match="重新偵測"):
        run(backend.select_source(source.id))
    available.append(source)
    run(backend.select_source(source.id))
    assert backend.selected == source


def test_ring_buffer_has_fixed_upper_bound():
    buffer = BoundedAudioBuffer(max_bytes=64)
    for index in range(1000):
        buffer.push(AudioChunk(bytes([index % 256]) * 16, 16000, 1, index))
    assert buffer.size_bytes == 64
    chunks = [buffer.pop() for _ in range(4)]
    assert [chunk.timestamp_ms for chunk in chunks] == [996, 997, 998, 999]
    assert buffer.pop() is None


def test_pcm_conversion_stereo_44k_to_mono_16k_int16():
    converter = PcmConverter(44_100, 2)
    t = np.arange(44_100) / 44_100
    signal = (np.sin(2 * np.pi * 440 * t) * 12000).astype("<i2")
    stereo = np.stack([signal, signal], axis=1)
    converted = b"".join(converter.convert(part.tobytes()) for part in np.array_split(stereo, 100)) + converter.finish()
    samples = np.frombuffer(converted, dtype="<i2")
    assert 15_900 <= len(samples) <= 16_100
    assert 0.30 < converter.peak(converted) < 0.40
    assert np.sqrt(np.mean(samples.astype(np.float64) ** 2)) > 7000
    with pytest.raises(ValueError):
        converter.convert(b"bad")
