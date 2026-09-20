"""Windows application audio sources and in-memory process-tree capture."""

from __future__ import annotations

import asyncio
import logging
import platform
import threading
import time
from typing import AsyncIterator, Callable

import comtypes
import psutil
from pycaw.api.audiopolicy import IAudioSessionControl2
from pycaw.constants import DEVICE_STATE, EDataFlow
from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
from pycaw.utils import AudioSession

from vlt.audio.base import AudioChunk, AudioSource
from vlt.audio.buffer import BoundedAudioBuffer
from vlt.audio.native.process_loopback import capture
from vlt.audio.pcm import PcmConverter


def _root_of_process_tree(process: psutil.Process) -> psutil.Process:
    """Resolve browser multi-process audio sessions to the browser's root PID."""
    name = process.name().casefold()
    current = process
    while True:
        parent = current.parent()
        if parent is None or parent.name().casefold() != name:
            return current
        current = parent


def _render_sessions() -> list[AudioSession]:
    sessions = []
    devices = AudioUtilities.GetAllDevices(data_flow=EDataFlow.eRender.value,
                                           device_state=DEVICE_STATE.ACTIVE.value)
    for device in devices:
        try:
            enumerator = device.AudioSessionManager.GetSessionEnumerator()
            for index in range(enumerator.GetCount()):
                control = enumerator.GetSession(index)
                if control is not None:
                    sessions.append(AudioSession(control.QueryInterface(IAudioSessionControl2)))
        except (OSError, comtypes.COMError):
            continue
    return sessions


def enumerate_audio_sources() -> list[AudioSource]:
    """Read actual Windows render audio sessions; a zero peak means currently silent."""
    comtypes.CoInitialize()
    try:
        found: dict[int, AudioSource] = {}
        for session in _render_sessions():
            try:
                process = session.Process
                if process is None or not process.is_running():
                    continue
                root = _root_of_process_tree(process)
                meter = session._ctl.QueryInterface(IAudioMeterInformation)
                peak = float(meter.GetPeakValue())
                pid = root.pid
                existing = found.get(pid)
                max_peak = max(peak, existing.peak if existing else 0.0)
                found[pid] = AudioSource(str(pid), root.name(), "process", pid,
                                         max_peak > 0.001, max_peak)
            except (psutil.Error, OSError, comtypes.COMError):
                continue
        return sorted(found.values(), key=lambda source: (not source.is_outputting, source.label.casefold(), source.pid))
    finally:
        comtypes.CoUninitialize()


class WindowsProcessLoopback:
    INPUT_RATE = 44_100
    INPUT_CHANNELS = 2
    OUTPUT_RATE = 16_000
    OUTPUT_CHANNELS = 1
    OUTPUT_DTYPE = "int16"

    def __init__(self, *, buffer_seconds: int = 5,
                 source_provider: Callable[[], list[AudioSource]] = enumerate_audio_sources,
                 capture_function: Callable = capture):
        self.buffer = BoundedAudioBuffer(buffer_seconds * self.OUTPUT_RATE * 2)
        self._source_provider = source_provider
        self._capture_function = capture_function
        self._selected: AudioSource | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._started = threading.Event()
        self._converter: PcmConverter | None = None
        self.state = "idle"
        self.error = ""
        self.peak = 0.0

    async def list_sources(self) -> list[AudioSource]:
        return await asyncio.to_thread(self._source_provider)

    async def select_source(self, source_id: str) -> None:
        sources = await self.list_sources()
        source = next((item for item in sources if item.id == source_id), None)
        if source is None:
            raise ValueError("音訊來源已消失。請重新偵測並選擇程式。")
        if self._thread and self._thread.is_alive():
            await self.stop()
        self._selected = source
        self.state = "selected"
        self.error = ""

    @property
    def selected(self) -> AudioSource | None:
        return self._selected

    async def start(self) -> None:
        if self._selected is None:
            raise ValueError("請先選擇要監聽的音訊程式。")
        if self._thread and self._thread.is_alive():
            return
        if int(platform.version().split(".")[-1]) < 20348:
            raise RuntimeError("此 Windows 版本不支援指定程式音訊擷取；需要 Build 20348 或更新版本。")
        if not psutil.pid_exists(self._selected.pid):
            raise RuntimeError("來源程式已關閉。請重新偵測並選擇音訊來源。")
        self._stop.clear()
        self._started.clear()
        self._converter = PcmConverter(self.INPUT_RATE, self.INPUT_CHANNELS)
        self.buffer.clear()
        self.peak = 0.0
        self.error = ""
        self.state = "connecting"
        self._thread = threading.Thread(target=self._run, name="process-loopback", daemon=True)
        self._thread.start()
        await asyncio.to_thread(self._started.wait, 10)
        if self.state == "error":
            raise RuntimeError(self.error)
        if self.state != "capturing":
            raise TimeoutError("Windows 音訊來源連線逾時。請確認程式正在播放聲音後重試。")

    def _run(self) -> None:
        assert self._selected is not None
        pid = self._selected.pid
        try:
            def on_pcm(raw: bytes) -> None:
                assert self._converter is not None
                normalized = self._converter.convert(raw)
                if normalized:
                    self.peak = self._converter.peak(normalized)
                    self.buffer.push(AudioChunk(normalized, self.OUTPUT_RATE, 1, int(time.monotonic() * 1000)))

            def ready() -> None:
                self.state = "capturing"
                self._started.set()

            self._capture_function(pid, self._stop, on_pcm, ready,
                                   lambda: psutil.pid_exists(pid))
            if not self._stop.is_set():
                self.error = "音訊來源已停止或程式已關閉。請重新偵測來源。"
                self.state = "error"
        except ProcessLookupError:
            self.error = "音訊來源程式已關閉。請重新偵測並選擇來源。"
            self.state = "error"
        except Exception:
            logging.exception("Process loopback capture failed for PID %d", pid)
            self.error = "無法擷取此程式的音訊。請確認程式正在播放聲音、Windows 音訊裝置可用，然後重新連接。"
            self.state = "error"
        finally:
            self._started.set()
            self.peak = 0.0

    async def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            await asyncio.to_thread(self._thread.join, 2)
        if self._thread and self._thread.is_alive():
            raise TimeoutError("音訊擷取仍在關閉中，請稍候再試。")
        self._thread = None
        self.buffer.clear()
        self.peak = 0.0
        self.state = "idle"

    async def audio_stream(self) -> AsyncIterator[AudioChunk]:
        while self.state in ("connecting", "capturing") or self.buffer.size_bytes:
            chunk = self.buffer.pop()
            if chunk is not None:
                yield chunk
            else:
                await asyncio.sleep(0.02)
