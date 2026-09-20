from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from collections.abc import Callable

from PySide6.QtCore import QCoreApplication, QObject, Property, QTimer, Signal, Slot, QUrl
from PySide6.QtGui import QDesktopServices

from vlt.audio.windows_process_loopback import WindowsProcessLoopback
from vlt.asr.base import ASRBackend, Recognition
from vlt.asr.pipeline import ASRPipeline
from vlt.sessions.manager import SessionManager
from vlt.settings.manager import SettingsManager
from vlt.subtitles.live import TranscriptCoordinator


class StudioController(QObject):
    changed = Signal()
    audioChanged = Signal()
    sourcesReady = Signal(object)
    audioOperationDone = Signal(str)
    asrRecognition = Signal(object)
    asrStatusEvent = Signal(str, str)
    asrDone = Signal()
    asrAudioAnchor = Signal(object)
    transcriptChanged = Signal()

    def __init__(self, sessions: SessionManager, settings: SettingsManager,
                 asr_backend_factory: Callable[[], ASRBackend],
                 audio: WindowsProcessLoopback | None = None):
        super().__init__()
        self.sessions = sessions
        self.settings = settings
        self._asr_backend_factory = asr_backend_factory
        self._selected_id = ""
        self._overlay_visible = False
        self._message = "選擇程式音訊後開始監聽；逐字稿會即時保存至 Session。"
        self.audio = audio or WindowsProcessLoopback()
        self._audio_sources: list[dict] = []
        self._pending_audio_source = ""
        self._audio_busy = False
        self._refresh_inflight = False
        self._audio_status = "請選擇音訊來源"
        self._display_peak = 0.0
        self._asr_state = "idle"
        self._asr_status = "正在等待語音…"
        self._asr_pipeline: ASRPipeline | None = None
        self._asr_thread: threading.Thread | None = None
        self._transcript: TranscriptCoordinator | None = None
        self._finish_requested = False
        self.sourcesReady.connect(self._on_sources_ready)
        self.audioOperationDone.connect(self._on_audio_operation_done)
        self.asrRecognition.connect(self._on_asr_recognition)
        self.asrStatusEvent.connect(self._on_asr_status)
        self.asrDone.connect(self._on_asr_done)
        self.asrAudioAnchor.connect(self._on_asr_audio_anchor)
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
        return self._audio_busy or bool(self._asr_thread and self._asr_thread.is_alive()
                                        and self.audio.state != "capturing")

    @Property(str, notify=audioChanged)
    def selectedAudioSource(self) -> str:
        return self._pending_audio_source

    @Property("QVariantList", notify=transcriptChanged)
    def transcriptSegments(self) -> list[dict]:
        return list(self._transcript.finals) if self._transcript else []

    @Property("QVariantMap", notify=transcriptChanged)
    def liveSegment(self) -> dict:
        return self._transcript.live or {} if self._transcript else {}

    @Property(str, notify=transcriptChanged)
    def asrState(self) -> str:
        return self._asr_state

    @Property(str, notify=transcriptChanged)
    def asrStatus(self) -> str:
        return self._asr_status

    @Property(str, notify=transcriptChanged)
    def asrLatency(self) -> str:
        if not self._transcript:
            return ""
        value = self._transcript.partial_latency_ms
        return f"ASR latency {value / 1000:.1f} s" if value is not None else ""

    @Property(str, notify=transcriptChanged)
    def detectedLanguage(self) -> str:
        if not self._transcript:
            return ""
        if self._transcript.live:
            return self._transcript.live.get("language", "")
        return self._transcript.finals[-1].get("language", "") if self._transcript.finals else ""

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
        if self.audioBusy or not self._pending_audio_source:
            return
        session = self.selectedSession
        try:
            if not session or session["status"] == "completed":
                self.createSession()
                session = self.selectedSession
            elif session["status"] == "interrupted":
                session = self.sessions.resume(session["session_id"])
            elapsed = int((datetime.now().astimezone() - datetime.fromisoformat(session["created_at"])).total_seconds() * 1000)
            prior = self.sessions.list_segments(session["session_id"])
            offset = max(0, elapsed, max((item["end_ms"] for item in prior), default=0))
            self._transcript = TranscriptCoordinator(self.sessions, session["session_id"], offset)
            self.transcriptChanged.emit()
            self.changed.emit()
        except Exception:
            logging.exception("Session could not start")
            self._message = "無法建立或恢復 Session，請檢查資料儲存位置。"
            self.changed.emit()
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
        if self._asr_pipeline:
            self._asr_pipeline.stop()
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
        if not error and self.audio.state == "capturing":
            self._start_asr()
        elif self.audio.state != "capturing" and self._asr_pipeline:
            self._asr_pipeline.stop()
        if self._finish_requested and self.audio.state == "capturing":
            self.stopAudioCapture()
        elif self._finish_requested and not self._asr_pipeline and self.audio.state != "capturing":
            self._finish_requested = False
            self._complete_session()

    def _start_asr(self) -> None:
        if self._asr_thread and self._asr_thread.is_alive():
            return
        pipeline = ASRPipeline(
            self.audio,
            self._asr_backend_factory,
            self.settings.values["source_language"],
            lambda result: self.asrRecognition.emit(result),
            lambda result: self.asrRecognition.emit(result),
            lambda state, message: self.asrStatusEvent.emit(state, message),
            lambda timestamp: self.asrAudioAnchor.emit(timestamp),
        )
        self._asr_pipeline = pipeline

        def run() -> None:
            try:
                asyncio.run(pipeline.run())
            except Exception:
                logging.exception("ASR pipeline failed")
                self.asrStatusEvent.emit("error", "語音辨識發生錯誤，請停止後重試。")
            finally:
                self.asrDone.emit()

        self._asr_thread = threading.Thread(target=run, name="asr-pipeline", daemon=True)
        self._asr_thread.start()

    @Slot(object)
    def _on_asr_recognition(self, result: Recognition) -> None:
        if not self._transcript:
            return
        try:
            if result.is_final:
                self._transcript.apply_final(result)
            else:
                self._transcript.apply_partial(result)
            self.transcriptChanged.emit()
        except Exception:
            logging.exception("Could not persist transcript")
            self._on_asr_status("error", "逐字稿無法保存，請檢查資料儲存位置。")

    @Slot(str, str)
    def _on_asr_status(self, state: str, message: str) -> None:
        if state in ("reconnecting", "error", "idle") and self._transcript:
            self._transcript.live = None
        self._asr_state = state
        self._asr_status = message
        self.transcriptChanged.emit()

    @Slot(object)
    def _on_asr_audio_anchor(self, chunk_monotonic_ms: int) -> None:
        if not self._transcript:
            return
        session = self.selectedSession
        if not session:
            return
        first_chunk_wall_ms = int(time.time() * 1000) - (int(time.monotonic() * 1000) - chunk_monotonic_ms)
        created_ms = int(datetime.fromisoformat(session["created_at"]).timestamp() * 1000)
        latest_end = max((item["end_ms"] for item in self._transcript.finals), default=0)
        self._transcript.offset_ms = max(0, first_chunk_wall_ms - created_ms, latest_end)

    @Slot()
    def _on_asr_done(self) -> None:
        self._asr_pipeline = None
        self._asr_thread = None
        self.audioChanged.emit()
        if self._finish_requested:
            self._finish_requested = False
            self._complete_session()

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
        if self._asr_pipeline:
            self._asr_pipeline.stop()
        if self.audio.state in ("capturing", "connecting", "error"):
            asyncio.run(self.audio.stop())
        if self._asr_thread and self._asr_thread.is_alive():
            self._asr_thread.join(timeout=10)
        QCoreApplication.processEvents()

    @Slot()
    def createSession(self) -> None:
        if self._audio_busy or self.audio.state == "capturing":
            self._message = "請先停止監聽，再建立新的 Session。"
            self.changed.emit()
            return
        values = self.settings.values
        session = self.sessions.create(source_language=values["source_language"],
                                       target_language=values["target_language"],
                                       translation_style=values["translation_style"])
        self._selected_id = session["session_id"]
        self._transcript = TranscriptCoordinator(self.sessions, self._selected_id)
        self._message = "Session 已建立。開始監聽後，辨識結果會即時保存。"
        self.transcriptChanged.emit()
        self.changed.emit()

    @Slot(str)
    def selectSession(self, session_id: str) -> None:
        if self._audio_busy or self.audio.state == "capturing" or self._asr_pipeline:
            return
        if self.sessions.get(session_id):
            self._selected_id = session_id
            self._transcript = TranscriptCoordinator(self.sessions, session_id)
            self.transcriptChanged.emit()
            self.changed.emit()

    @Slot()
    def finishSession(self) -> None:
        session = self.selectedSession
        if session and session["status"] == "active":
            if self._audio_busy or self.audio.state in ("capturing", "connecting") or self._asr_pipeline:
                self._finish_requested = True
                if self.audio.state == "capturing" and not self._audio_busy:
                    self.stopAudioCapture()
                return
            self._complete_session()

    def _complete_session(self) -> None:
        session = self.selectedSession
        if session and session["status"] == "active":
            self.sessions.finish(session["session_id"])
            self._message = "Session 已結束並保存。"
            self.changed.emit()

    @Slot(str, "QVariant")
    def setPreference(self, key: str, value: object) -> None:
        self.settings.set(key, value)
        if key == "source_language" and self._asr_pipeline:
            self._asr_pipeline.set_language(str(value))
        if key == "source_language" and self._selected_id:
            self.sessions.set_source_language(self._selected_id, str(value))
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
