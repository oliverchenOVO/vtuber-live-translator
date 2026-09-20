from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot, QUrl
from PySide6.QtGui import QDesktopServices

from vlt.audio.windows_process_loopback import WindowsProcessLoopback
from vlt.sessions.manager import SessionManager
from vlt.settings.manager import SettingsManager


class StudioController(QObject):
    changed = Signal()
    audioChanged = Signal()
    sourcesReady = Signal(object)
    audioOperationDone = Signal(str)

    def __init__(self, sessions: SessionManager, settings: SettingsManager,
                 audio: WindowsProcessLoopback | None = None):
        super().__init__()
        self.sessions = sessions
        self.settings = settings
        self._selected_id = ""
        self._overlay_visible = False
        self._message = "Phase 2：可擷取指定程式音訊；語音辨識與翻譯尚未接入。"
        self.audio = audio or WindowsProcessLoopback()
        self._audio_sources: list[dict] = []
        self._pending_audio_source = ""
        self._audio_busy = False
        self._refresh_inflight = False
        self._audio_status = "請選擇音訊來源"
        self._display_peak = 0.0
        self.sourcesReady.connect(self._on_sources_ready)
        self.audioOperationDone.connect(self._on_audio_operation_done)
        self._audio_timer = QTimer(self)
        self._audio_timer.setInterval(100)
        self._audio_timer.timeout.connect(self._poll_audio)
        self._audio_timer.start()
        self._source_timer = QTimer(self)
        self._source_timer.setInterval(2500)
        self._source_timer.timeout.connect(self.refreshAudioSources)
        self._source_timer.start()
        self.refreshAudioSources()

    @Property("QVariantList", notify=changed)
    def history(self) -> list[dict]:
        return self.sessions.list_sessions()

    @Property("QVariantMap", notify=changed)
    def selectedSession(self) -> dict:
        return self.sessions.get(self._selected_id) or {}

    @Property("QVariantMap", notify=changed)
    def preferences(self) -> dict:
        return dict(self.settings.values)

    @Property(bool, notify=changed)
    def overlayVisible(self) -> bool:
        return self._overlay_visible

    @Property(str, notify=changed)
    def message(self) -> str:
        return self._message

    @Property("QVariantList", notify=audioChanged)
    def audioSources(self) -> list[dict]:
        return self._audio_sources

    @Property(str, notify=audioChanged)
    def audioStatus(self) -> str:
        return self._audio_status

    @Property(str, notify=audioChanged)
    def audioState(self) -> str:
        return self.audio.state

    @Property(float, notify=audioChanged)
    def audioPeak(self) -> float:
        return self._display_peak

    @Property(bool, notify=audioChanged)
    def audioBusy(self) -> bool:
        return self._audio_busy

    @Property(str, notify=audioChanged)
    def selectedAudioSource(self) -> str:
        return self._pending_audio_source

    @Slot()
    def refreshAudioSources(self) -> None:
        if self._refresh_inflight:
            return
        self._refresh_inflight = True

        def run() -> None:
            try:
                sources = asyncio.run(self.audio.list_sources())
                payload = [{"id": source.id, "pid": source.pid, "label": source.label,
                            "isOutputting": source.is_outputting, "peak": source.peak,
                            "display": f"{source.label}  ·  PID {source.pid}  ·  "
                                       f"{'有音訊' if source.is_outputting else '目前無聲'}"}
                           for source in sources]
                self.sourcesReady.emit({"sources": payload, "error": ""})
            except Exception:
                logging.exception("Audio source enumeration failed")
                self.sourcesReady.emit({"sources": [], "error": "無法讀取 Windows 音訊來源。請確認音訊裝置可用，再按重新偵測。"})

        threading.Thread(target=run, name="audio-source-refresh", daemon=True).start()

    @Slot(object)
    def _on_sources_ready(self, result: dict) -> None:
        self._refresh_inflight = False
        sources = result["sources"]
        self._audio_sources = sources
        if result["error"] and self.audio.state != "capturing":
            self._audio_status = result["error"]
        if not self._pending_audio_source and sources:
            self._pending_audio_source = sources[0]["id"]
        self.audioChanged.emit()

    @Slot(str)
    def selectAudioSource(self, source_id: str) -> None:
        self._pending_audio_source = source_id
        self._audio_status = "已選擇來源，按「開始監聽」檢查音量。"
        self.audioChanged.emit()

    @Slot()
    def startAudioCapture(self) -> None:
        if self._audio_busy or not self._pending_audio_source:
            return
        source_id = self._pending_audio_source
        self._audio_busy = True
        self._audio_status = "正在連線到指定程式的音訊…"
        self.audioChanged.emit()

        def run() -> None:
            try:
                asyncio.run(self.audio.select_source(source_id))
                asyncio.run(self.audio.start())
                self.audioOperationDone.emit("")
            except Exception as exc:
                self.audioOperationDone.emit(str(exc))

        threading.Thread(target=run, name="audio-connect", daemon=True).start()

    @Slot()
    def stopAudioCapture(self) -> None:
        if self._audio_busy:
            return
        self._audio_busy = True
        self.audioChanged.emit()

        def run() -> None:
            try:
                asyncio.run(self.audio.stop())
                self.audioOperationDone.emit("")
            except Exception as exc:
                self.audioOperationDone.emit(str(exc))

        threading.Thread(target=run, name="audio-disconnect", daemon=True).start()

    @Slot(str)
    def _on_audio_operation_done(self, error: str) -> None:
        self._audio_busy = False
        self._audio_status = error or ("正在擷取指定程式音訊" if self.audio.state == "capturing" else "已停止監聽")
        self.audioChanged.emit()

    @Slot()
    def _poll_audio(self) -> None:
        self._display_peak = max(float(self.audio.peak), self._display_peak * 0.72)
        if self.audio.state == "error" and self._audio_status != self.audio.error:
            self._audio_status = self.audio.error
            self.refreshAudioSources()
        self.audioChanged.emit()

    def shutdown(self) -> None:
        self._audio_timer.stop()
        self._source_timer.stop()
        if self.audio.state in ("capturing", "connecting", "error"):
            asyncio.run(self.audio.stop())

    @Slot()
    def createSession(self) -> None:
        values = self.settings.values
        session = self.sessions.create(source_language=values["source_language"],
                                       target_language=values["target_language"],
                                       translation_style=values["translation_style"])
        self._selected_id = session["session_id"]
        self._message = "空白 Session 已建立。音訊監聽可在上方啟動；翻譯功能尚未接入。"
        self.changed.emit()

    @Slot(str)
    def selectSession(self, session_id: str) -> None:
        if self.sessions.get(session_id):
            self._selected_id = session_id
            self.changed.emit()

    @Slot()
    def finishSession(self) -> None:
        session = self.selectedSession
        if session and session["status"] == "active":
            self.sessions.finish(session["session_id"])
            self._message = "Session 已結束並保存。"
            self.changed.emit()

    @Slot(str, "QVariant")
    def setPreference(self, key: str, value: object) -> None:
        self.settings.set(key, value)
        self.changed.emit()

    @Slot()
    def toggleOverlay(self) -> None:
        self._overlay_visible = not self._overlay_visible
        self.changed.emit()

    @Slot()
    def openSessionFolder(self) -> None:
        session = self.selectedSession
        if session:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(session["folder_path"]))))
