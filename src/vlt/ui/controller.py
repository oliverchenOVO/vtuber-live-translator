from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from collections.abc import Callable

from PySide6.QtCore import QCoreApplication, QObject, Property, QTimer, Signal, Slot, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication

from vlt.audio.windows_process_loopback import WindowsProcessLoopback
from vlt.asr.base import ASRBackend, Recognition
from vlt.asr.pipeline import ASRPipeline
from vlt.diarization.base import DiarizationBackend, SpeakerObservation
from vlt.sessions.manager import SessionManager
from vlt.settings.manager import SettingsManager
from vlt.subtitles.live import TranscriptCoordinator
from vlt.translation.base import TranslationBackend, TranslationRequest
from vlt.translation.glossary import Glossary
from vlt.translation.ollama_backend import OllamaTranslationBackend
from vlt.translation.pipeline import TranslationPipeline
from vlt.product.cache import CacheManager
from vlt.product.diagnostics import export_diagnostics
from vlt.product.compatibility import windows_build
from vlt.product.hardware import detect_hardware, recommended_preset
from vlt.product.models import ModelManager
from vlt.product.paths import ProductPaths
from vlt.product.startup import set_start_with_windows
from vlt.product.updates import UpdateChecker
from vlt.version import __version__


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
    translationReady = Signal(object, object, float, str)
    diarizationNew = Signal(str, int)
    diarizationUpdated = Signal(int)
    diarizationOverlap = Signal(object, int)
    componentProgress = Signal(str, int, str)
    updateResult = Signal(str)

    def __init__(self, sessions: SessionManager, settings: SettingsManager,
                 asr_backend_factory: Callable[[], ASRBackend],
                 audio: WindowsProcessLoopback | None = None,
                 translation_backend_factory: Callable[[], TranslationBackend] | None = None,
                 diarization_backend_factory: Callable[[], DiarizationBackend] | None = None):
        super().__init__()
        self.sessions = sessions
        self.settings = settings
        self.paths = ProductPaths(settings.path.parent, sessions.root,
                                  settings.path.parent / "models", settings.path.parent / "cache",
                                  settings.path.parent / "logs", settings.path.parent / "runtime")
        self.paths.ensure()
        self.hardware = detect_hardware()
        self.model_manager = ModelManager(self.paths.models, self.paths.cache, self.paths.runtime)
        self.cache_manager = CacheManager(self.paths.cache)
        self.cache_manager.prune()
        self.update_checker = UpdateChecker(os.environ.get("VLT_RELEASES_API", ""))
        self._component_state = {"component": "", "percent": 0, "message": "", "busy": False,
                                 **self.model_manager.status()}
        self._audio_test_only = False
        self._cancel_start = False
        self._asr_backend_factory = asr_backend_factory
        self._selected_id = ""
        self._overlay_visible = bool(settings.values["show_overlay_on_start"])
        self._message = "選擇程式音訊後開始監聽；逐字稿會即時保存至 Session。"
        self.audio = audio or WindowsProcessLoopback()
        self._audio_sources: list[dict] = []
        self._pending_audio_source = ""
        self._audio_busy = False
        self._refresh_inflight = False
        self._refresh_thread: threading.Thread | None = None
        self._shutting_down = False
        self._audio_status = "請選擇音訊來源"
        self._display_peak = 0.0
        self._asr_state = "idle"
        self._asr_status = "正在等待語音…"
        self._asr_pipeline: ASRPipeline | None = None
        self._asr_thread: threading.Thread | None = None
        self._asr_partial_count = 0
        self._asr_final_count = 0
        self._last_pipeline_log = 0.0
        self._transcript: TranscriptCoordinator | None = None
        self._visible_segment_limit = 120
        self._search_results: list[dict] = []
        self._focused_segment: dict = {}
        self._pending_delete_session_id = ""
        self._finalizing = False
        self._finalize_deadline = 0.0
        self._source_error_handled = False
        self._last_audible_at = time.monotonic()
        self._diarization_factory = diarization_backend_factory
        self._diarization: DiarizationBackend | None = None
        self._diarization_epoch = 0
        self._speaker_rows: list[dict] = []
        self._speaker_new_until: dict[str, float] = {}
        self._finish_requested = False
        self.glossary = Glossary(settings.path.parent / "glossary.json")
        self._translation_status = "正在等待語音…"
        self._translation_latency_ms: float | None = None
        self._translation_ready = False
        self._translation_retry_after: dict[str, float] = {}
        self._translation_retry_counts: dict[str, int] = {}
        self._idle_translation_retry_at = 0.0
        self._translation_backend_factory = translation_backend_factory or OllamaTranslationBackend
        self._translation_pipeline = TranslationPipeline(
            self._translation_backend_factory,
            lambda request, result, latency, error: self.translationReady.emit(request, result, latency, error))
        self._translation_pipeline.start()
        self.translationReady.connect(self._on_translation_ready)
        self.diarizationNew.connect(self._on_diarization_new)
        self.diarizationUpdated.connect(self._on_diarization_updated)
        self.diarizationOverlap.connect(self._on_diarization_overlap)
        self.componentProgress.connect(self._on_component_progress)
        self.updateResult.connect(self._on_update_result)
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
        self._pending_timer = QTimer(self)
        self._pending_timer.setInterval(3000)
        self._pending_timer.timeout.connect(self._enqueue_pending_translations)
        self._pending_timer.start()
        self.refreshAudioSources()

    @Property(str, constant=True)
    def appVersion(self) -> str:
        return __version__

    @Property(str, constant=True)
    def appBuild(self) -> str:
        return f"{__version__}.{windows_build()}"

    @Property(bool, notify=changed)
    def firstRunComplete(self) -> bool:
        return bool(self.settings.values["first_run_complete"])

    @Property("QVariantMap", notify=changed)
    def hardwareProfile(self) -> dict:
        value = self.hardware.to_dict()
        value["recommended"] = recommended_preset(self.hardware)
        return value

    @Property("QVariantMap", notify=changed)
    def componentState(self) -> dict:
        return dict(self._component_state)

    @Property(str, notify=changed)
    def dataFolder(self) -> str:
        return str(self.paths.root)

    @Property(str, constant=True)
    def logFolder(self) -> str:
        return str(self.paths.logs)

    @Property(str, notify=changed)
    def sessionFolder(self) -> str:
        return str(self.sessions.root)

    @Property(str, notify=changed)
    def cacheSize(self) -> str:
        return f"{self.cache_manager.size() / 1024 ** 2:.1f} MB"

    @Property("QVariantList", notify=audioChanged)
    def startupStages(self) -> list[dict]:
        diar = getattr(self._diarization, "status", "idle")
        states = [("音訊引擎", self.audio.state == "capturing"),
                  ("語音辨識", self._asr_state == "live"),
                  ("本機翻譯", self._translation_ready),
                  ("Speaker 分析", diar in ("live", "limited"))]
        return [{"name": name, "ready": ready} for name, ready in states]

    @Slot()
    def exportDiagnostics(self) -> None:
        try:
            path = self.paths.root / "diagnostics" / ("diagnostics-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".zip")
            export_diagnostics(path, self.settings.values, self.hardware.to_dict(), self.paths.logs)
            self._message = "診斷資料已匯出（不含逐字稿、音訊或個人聲紋）：" + str(path)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
        except Exception:
            self._message = "診斷資料無法匯出，請檢查可用磁碟空間。"
        self.changed.emit()

    @Slot(str)
    def verifyComponent(self, component: str) -> None:
        if self._component_state["busy"] or self.audio.state == "capturing":
            return
        self._component_state.update(component=component, busy=True, percent=0, message="正在驗證模型…")
        self.changed.emit()
        def run() -> None:
            try:
                self.model_manager.verify(component)
                self.componentProgress.emit(component, 100, "模型驗證通過")
            except Exception:
                self.componentProgress.emit(component, -1, "模型未通過驗證，請按修復；已保留下載進度。")
        threading.Thread(target=run, name="model-verify", daemon=True).start()

    @Slot(str, str, str)
    def assignUnknownRange(self, start: str, end: str, speaker_id: str) -> None:
        if not self._transcript:
            return
        try:
            def millis(value: str) -> int:
                parts = value.strip().split(":")
                if len(parts) != 3 or not all(p.isdigit() for p in parts):
                    raise ValueError()
                h, m, s = map(int, parts)
                if m >= 60 or s >= 60:
                    raise ValueError()
                return (h * 3600 + m * 60 + s) * 1000
            count = self.sessions.assign_unknown_range(self._transcript.session_id, millis(start),
                                                       millis(end), speaker_id)
            self._transcript.reload_loaded()
            self._refresh_speakers()
            self._message = f"已指定 {count} 筆未知 Speaker（依開始時間，包含起點、不含終點）。"
            self.transcriptChanged.emit()
        except ValueError:
            self._message = "請輸入有效的 HH:MM:SS 範圍及 Speaker。"
        except Exception:
            self._message = "Speaker 指定無法完成，請檢查磁碟空間後重試。"
        self.changed.emit()

    @Slot(str)
    def selectPerformancePreset(self, name: str) -> None:
        if name not in ("gaming", "balanced", "quality"):
            return
        self.settings.set("performance_preset", name)
        self._translation_pipeline.stop()
        self._translation_pipeline = TranslationPipeline(
            self._translation_backend_factory,
            lambda request, result, latency, error:
                self.translationReady.emit(request, result, latency, error))
        self._translation_pipeline.start()
        if self.audio.state != "capturing":
            self._message = "效能模式已套用；下一次監聽會使用新的 ASR 與 Speaker 設定。"
        else:
            self._message = "翻譯效能模式已套用；ASR 與 Speaker 設定會在下一個 Session 套用。"
        self.changed.emit()

    @Slot(str)
    def installComponent(self, component: str) -> None:
        if self.audioBusy or self.audio.state == "capturing" or self._asr_pipeline:
            self._message = "請先停止監聽，再安裝或修復 AI 元件。"
            self.changed.emit()
            return
        if self._component_state["busy"] or component not in ("asr", "translation", "diarization"):
            return
        self._component_state.update(component=component, percent=0, message="正在檢查元件…", busy=True)
        self.changed.emit()

        def run() -> None:
            try:
                self.model_manager.install(component,
                    lambda message, percent: self.componentProgress.emit(component, min(percent, 99), message))
                self.componentProgress.emit(component, 100, "安裝完成")
            except Exception as exc:
                logging.exception("Component installation failed: %s", component)
                self.componentProgress.emit(component, -1, str(exc))
        threading.Thread(target=run, name=f"install-{component}", daemon=True).start()

    @Slot(str)
    def removeComponent(self, component: str) -> None:
        if self.audioBusy or self.audio.state == "capturing" or self._asr_pipeline:
            self._message = "請先停止監聽，再移除 AI 元件。"
            self.changed.emit()
            return
        if self._component_state["busy"] or component not in ("asr", "translation", "diarization"):
            return
        self._component_state.update(component=component, percent=0, message="正在移除元件…", busy=True)
        self.changed.emit()

        def run() -> None:
            try:
                self.model_manager.remove(component)
                self.componentProgress.emit(component, 100, "元件已移除；需要時可重新下載。")
            except Exception as exc:
                logging.exception("Component removal failed: %s", component)
                self.componentProgress.emit(component, -1, str(exc))
        threading.Thread(target=run, name=f"remove-{component}", daemon=True).start()

    @Slot(str, int, str)
    def _on_component_progress(self, component: str, percent: int, message: str) -> None:
        self._component_state.update(component=component, percent=max(0, percent), message=message,
                                     busy=0 <= percent < 100)
        if percent == 100:
            self._component_state.update(self.model_manager.status())
        self.changed.emit()

    @Slot()
    def completeFirstRun(self) -> None:
        self.settings.set("first_run_complete", True)
        self.changed.emit()

    @Slot()
    def clearCache(self) -> None:
        freed = self.cache_manager.clear()
        self._message = f"已清除 {freed / 1024 ** 2:.1f} MB 快取。"
        self.changed.emit()

    @Slot()
    def checkForUpdates(self) -> None:
        self._message = "正在檢查更新…"
        self.changed.emit()

        def run() -> None:
            try:
                info = self.update_checker.check(__version__)
                if info.available:
                    message = f"Vtuber Live Translator {info.version} 已可下載。"
                else:
                    message = info.message or "目前已是最新版本。"
            except Exception:
                logging.exception("Update check failed")
                message = "目前無法檢查更新，請稍後再試。"
            self.updateResult.emit(message)
        threading.Thread(target=run, name="update-check", daemon=True).start()

    @Slot(str)
    def _on_update_result(self, message: str) -> None:
        self._message = message
        self.changed.emit()

    @Slot()
    def quitApplication(self) -> None:
        QCoreApplication.quit()

    @Slot()
    def openDataFolder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.paths.root)))

    @Slot()
    def openLogFolder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.paths.logs)))

    def _open_bundled_document(self, name: str) -> None:
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
        target = base / name
        if target.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
        else:
            self._message = f"找不到 {name}。請重新安裝應用程式。"
            self.changed.emit()

    @Slot()
    def openLicense(self) -> None:
        self._open_bundled_document("LICENSE.txt")

    @Slot()
    def openOpenSourceNotices(self) -> None:
        self._open_bundled_document("THIRD_PARTY_NOTICES.txt")

    @Slot(str)
    def setSessionRoot(self, value: str) -> None:
        path = Path(value.strip()).expanduser() if value.strip() else self.paths.sessions
        try:
            path.mkdir(parents=True, exist_ok=True)
            free = shutil.disk_usage(path).free
            required = 512 * 1024 ** 2
            if free < required:
                self._message = (f"Session 儲存空間不足。Available: {free / 1024 ** 3:.1f} GB · "
                                 f"Required: {required / 1024 ** 3:.1f} GB")
                self.changed.emit()
                return
            probe = path / ".vlt-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            self.sessions.root = path
            self.settings.set("session_root", "" if path == self.paths.sessions else str(path.resolve()))
            self._message = "新的 Session 將保存到指定位置；既有 History 保持可用。"
        except OSError:
            self._message = "無法使用此 Session 儲存位置，請確認路徑與寫入權限。"
        self.changed.emit()

    @Slot()
    def startAudioTest(self) -> None:
        if self.audioBusy or not self._pending_audio_source:
            return
        self._audio_test_only = True
        source_id = self._pending_audio_source
        self._audio_busy = True
        self._audio_status = "正在測試指定程式音訊…"
        self.audioChanged.emit()
        def run() -> None:
            try:
                asyncio.run(self.audio.select_source(source_id))
                asyncio.run(self.audio.start())
                self.audioOperationDone.emit("")
            except Exception as exc:
                self.audioOperationDone.emit(str(exc))
        threading.Thread(target=run, name="audio-test", daemon=True).start()

    @Property("QVariantList", notify=changed)
    def history(self) -> list[dict]:
        return [item for item in self.sessions.list_sessions()
                if item["status"] in ("completed", "interrupted")]

    @Property("QVariantMap", notify=changed)
    def interruptedSession(self) -> dict:
        return next((item for item in self.sessions.list_sessions()
                     if item["status"] == "interrupted"), {})

    @Property(bool, notify=changed)
    def finalizing(self) -> bool:
        return self._finalizing

    @Property(str, notify=changed)
    def pendingDeleteSessionId(self) -> str:
        return self._pending_delete_session_id

    @Property("QVariantList", notify=transcriptChanged)
    def searchResults(self) -> list[dict]:
        return [self._decorate_segment(item) for item in self._search_results]

    @Property("QVariantMap", notify=transcriptChanged)
    def focusedSegment(self) -> dict:
        return self._decorate_segment(self._focused_segment) if self._focused_segment else {}

    @Property("QVariantMap", notify=changed)
    def exportPaths(self) -> dict:
        if not self._selected_id:
            return {}
        session = self.sessions.get(self._selected_id)
        if not session:
            return {}
        folder = Path(session["folder_path"])
        return {"markdown": str(folder / "transcript.md"),
                "srt": str(folder / "exports" / "transcript.srt"),
                "vtt": str(folder / "exports" / "transcript.vtt"),
                "json": str(folder / "transcript.json"), "folder": str(folder)}

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
        return ([self._decorate_segment(item) for item in self._transcript.finals[-self._visible_segment_limit:]]
                if self._transcript else [])

    @Property(int, notify=transcriptChanged)
    def earlierSegmentCount(self) -> int:
        if not self._transcript:
            return 0
        return max(self._transcript.earlier_count,
                   len(self._transcript.finals) - self._visible_segment_limit)

    @Slot()
    def loadEarlierSegments(self) -> None:
        if self._transcript and self.earlierSegmentCount:
            if self._transcript.earlier_count:
                self._transcript.load_earlier(120)
                self._visible_segment_limit = len(self._transcript.finals)
            else:
                self._visible_segment_limit += 120
            self.transcriptChanged.emit()

    @Property("QVariantMap", notify=transcriptChanged)
    def liveSegment(self) -> dict:
        return self._decorate_segment(self._transcript.live) if self._transcript and self._transcript.live else {}

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

    @Property(str, notify=transcriptChanged)
    def translationStatus(self) -> str:
        return self._translation_status

    @Property(str, notify=transcriptChanged)
    def translationLatency(self) -> str:
        value = self._translation_latency_ms
        return f"Translation {value / 1000:.1f} s" if value is not None else ""

    @Property("QVariantMap", notify=transcriptChanged)
    def overlaySegment(self) -> dict:
        if self._transcript:
            if self._transcript.live and self._transcript.live.get("translation"):
                return self._decorate_segment(self._transcript.live)
            for segment in reversed(self._transcript.finals):
                if segment.get("translation"):
                    return self._decorate_segment(segment)
        return {}

    @Property("QVariantList", notify=transcriptChanged)
    def speakers(self) -> list[dict]:
        return list(self._speaker_rows)

    @Property(str, notify=transcriptChanged)
    def diarizationStatus(self) -> str:
        if not self._diarization:
            return "Speaker 待機"
        state = getattr(self._diarization, "status", "live")
        if state == "error":
            return "Speaker 辨識暫不可用，逐字稿仍正常"
        if state == "limited":
            limit = getattr(self._diarization, "max_speakers", 4)
            return f"Speaker 已達 {limit} 人 · 其他聲音暫標 Unknown"
        latency = getattr(self._diarization, "latency_ms", None)
        return f"Speaker {latency / 1000:.1f}s" if latency is not None else "Speaker 載入中…"

    def _refresh_speakers(self) -> None:
        self._speaker_rows = self.sessions.list_speakers(self._selected_id) if self._selected_id else []
        self.transcriptChanged.emit()

    def _decorate_segment(self, segment: dict) -> dict:
        speaker_id = segment.get("speaker_id")
        row = next((item for item in self._speaker_rows if item["speaker_id"] == speaker_id), None)
        palette = ("#62dfc2", "#e6bc79", "#8ca9ff", "#ef94b5", "#b6cf78", "#a899e8")
        number = int(speaker_id.split("_")[-1]) if speaker_id and speaker_id.startswith("speaker_") else 0
        return {**segment,
                "speaker_display_name": row["display_name"] if row else "",
                "speaker_color": palette[(number - 1) % len(palette)] if number else "#78919d",
                "speaker_new": time.monotonic() < self._speaker_new_until.get(speaker_id, 0),
                "show_speaker": bool(row and (len(self._speaker_rows) > 1 or
                                                row["display_name"] != "Speaker 1"))}

    @Slot(str, str)
    def renameSpeaker(self, speaker_id: str, name: str) -> None:
        try:
            if self._selected_id:
                self.sessions.update_speaker(self._selected_id, speaker_id, display_name=name)
                self.sessions.render_exports(
                    self._selected_id, str(self.settings.values["subtitle_mode"]))
                self._refresh_speakers()
        except ValueError as exc:
            self._message = str(exc)
            self.changed.emit()

    @Slot(str, str)
    def mapSpeakerPerson(self, speaker_id: str, person_id: str) -> None:
        if self._selected_id:
            self.sessions.update_speaker(self._selected_id, speaker_id, person_id=person_id)
            self.sessions.render_exports(
                self._selected_id, str(self.settings.values["subtitle_mode"]))
            self._refresh_speakers()

    @Slot(str, str)
    def mergeSpeakers(self, source_id: str, target_id: str) -> None:
        try:
            if self._selected_id:
                self.sessions.merge_speakers(self._selected_id, source_id, target_id)
                self.sessions.render_exports(
                    self._selected_id, str(self.settings.values["subtitle_mode"]))
                if self._diarization and hasattr(self._diarization, "remap_speaker"):
                    self._diarization.remap_speaker(source_id, target_id)
                if self._transcript:
                    self._transcript.reload_loaded()
                self._refresh_speakers()
        except ValueError as exc:
            self._message = str(exc)
            self.changed.emit()

    @Slot(str, str)
    def assignSegmentSpeaker(self, segment_id: str, speaker_id: str) -> None:
        if self._selected_id and self.sessions.assign_segment_speaker(self._selected_id, segment_id, speaker_id):
            self.sessions.render_exports(
                self._selected_id, str(self.settings.values["subtitle_mode"]))
            if self._transcript:
                self._transcript.reload_loaded()
            self._refresh_speakers()

    @Slot(str)
    def searchTranscript(self, query: str) -> None:
        self._search_results = self.sessions.search(self._selected_id, query) if self._selected_id else []
        self._focused_segment = {}
        self.transcriptChanged.emit()

    @Slot(str)
    def showSearchResult(self, segment_id: str) -> None:
        self._focused_segment = next((item for item in self._search_results
                                      if item.get("id") == segment_id), {})
        self.transcriptChanged.emit()

    @Slot(str)
    def openSessionFolderFor(self, session_id: str) -> None:
        session = self.sessions.get(session_id)
        if session:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(session["folder_path"]))))

    @Slot(str)
    def exportSession(self, session_id: str) -> None:
        if not self.sessions.get(session_id):
            return
        try:
            self.sessions.render_exports(session_id, str(self.settings.values["subtitle_mode"]))
            self._message = "Markdown、SRT、VTT 已重新輸出。"
        except Exception:
            logging.exception("Session export failed")
            self._message = "匯出失敗，SQLite 與 transcript.json 仍保留。"
        self.changed.emit()

    @Slot(str, str)
    def renameSession(self, session_id: str, title: str) -> None:
        try:
            self.sessions.rename(session_id, title)
            self.sessions.render_exports(session_id, str(self.settings.values["subtitle_mode"]))
            self._message = "Session 名稱與匯出已更新。"
        except (KeyError, ValueError, OSError) as exc:
            self._message = str(exc) or "Session 改名失敗。"
        self.changed.emit()

    @Slot(str)
    def requestDeleteSession(self, session_id: str) -> None:
        self._pending_delete_session_id = session_id
        self.changed.emit()

    @Slot()
    def cancelDeleteSession(self) -> None:
        self._pending_delete_session_id = ""
        self.changed.emit()

    @Slot()
    def confirmDeleteSession(self) -> None:
        session_id = self._pending_delete_session_id
        if not session_id:
            return
        try:
            self.sessions.delete(session_id)
            if self._selected_id == session_id:
                self._selected_id = ""
                self._transcript = None
                self._speaker_rows = []
            self._message = "Session 已刪除。"
        except (OSError, ValueError):
            logging.exception("Session deletion failed")
            self._message = "Session 刪除失敗，資料仍保留。"
        self._pending_delete_session_id = ""
        self.transcriptChanged.emit()
        self.changed.emit()

    @Slot(str)
    def continueInterruptedSession(self, session_id: str) -> None:
        try:
            self.sessions.resume(session_id)
            self.selectSession(session_id)
            self._message = "已恢復原 Session；選擇音訊來源後可繼續。"
        except (KeyError, ValueError) as exc:
            self._message = str(exc)
        self.changed.emit()

    @Slot(str)
    def archiveInterruptedSession(self, session_id: str) -> None:
        try:
            self.sessions.archive_interrupted(session_id, str(self.settings.values["subtitle_mode"]))
            self.selectSession(session_id)
            self._message = "中斷的 Session 已完成匯出並封存。"
        except Exception:
            logging.exception("Interrupted Session archive failed")
            self._message = "封存失敗；Session 仍保留，可重試。"
        self.changed.emit()

    @Slot()
    def exportCurrentSession(self) -> None:
        if not self._selected_id:
            return
        try:
            self.sessions.render_exports(self._selected_id, str(self.settings.values["subtitle_mode"]))
            self._message = "Markdown、SRT、VTT 已重新輸出。"
        except Exception:
            logging.exception("Manual export failed")
            self._message = "匯出失敗，SQLite 與 transcript.json 仍保留。"
        self.changed.emit()

    @Slot(str)
    def copyPath(self, path: str) -> None:
        QGuiApplication.clipboard().setText(path)
        self._message = "路徑已複製。"
        self.changed.emit()

    @Property("QVariantList", notify=changed)
    def glossaryEntries(self) -> list[dict]:
        return self.glossary.list()

    @Property(str, notify=changed)
    def glossaryDefaultExportPath(self) -> str:
        return str(self.settings.path.parent / "glossary-export.json")

    @Slot(str, str, str, str)
    def saveGlossaryEntry(self, source: str, zh_tw: str, zh_cn: str, aliases: str) -> None:
        try:
            self.glossary.upsert(source, zh_tw, zh_cn, aliases.split(","))
            self._message = "譯名已保存。"
        except ValueError as exc:
            self._message = str(exc)
        self.changed.emit()

    @Slot(str)
    def deleteGlossaryEntry(self, source: str) -> None:
        self.glossary.delete(source)
        self.changed.emit()

    @Slot(str)
    def importGlossary(self, file_path: str) -> None:
        try:
            self.glossary.import_file(Path(file_path))
            self._message = "詞庫已匯入。"
        except (OSError, ValueError, KeyError, TypeError):
            self._message = "詞庫匯入失敗，請確認路徑與 JSON 格式。"
        self.changed.emit()

    @Slot(str)
    def exportGlossary(self, file_path: str) -> None:
        try:
            self.glossary.export_file(Path(file_path))
            self._message = "詞庫已匯出。"
        except OSError:
            self._message = "詞庫無法匯出至指定路徑。"
        self.changed.emit()

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
                if not self._shutting_down:
                    try:
                        self.sourcesReady.emit({"sources": payload, "error": ""})
                    except RuntimeError:
                        pass
            except Exception:
                logging.exception("Audio source enumeration failed")
                if not self._shutting_down:
                    try:
                        self.sourcesReady.emit({"sources": [], "error": "無法讀取 Windows 音訊來源。請確認音訊裝置可用，再按重新偵測。"})
                    except RuntimeError:
                        pass

        self._refresh_thread = threading.Thread(target=run, name="audio-source-refresh", daemon=True)
        self._refresh_thread.start()

    @Slot(object)
    def _on_sources_ready(self, result: dict) -> None:
        self._refresh_inflight = False
        sources = result["sources"]
        if result["error"] and self.audio.state != "capturing":
            self._audio_status = result["error"]
        remembered = str(self.settings.values.get("last_audio_source_label", ""))
        selected = (next((item for item in sources if item["label"] == remembered), None)
                    if self.settings.values.get("remember_audio_source") else None)
        if selected:
            sources = [selected, *(item for item in sources if item["id"] != selected["id"])]
            if not any(item["id"] == self._pending_audio_source for item in sources):
                self._pending_audio_source = selected["id"]
        elif self.audio.state != "capturing" and not any(
                item["id"] == self._pending_audio_source for item in sources):
            self._pending_audio_source = ""
        if not self._pending_audio_source and sources:
            self._pending_audio_source = (selected or sources[0])["id"]
        self._audio_sources = sources
        self.audioChanged.emit()

    @Slot(str)
    def selectAudioSource(self, source_id: str) -> None:
        if self.audioBusy or self.audio.state == "capturing" or self._asr_pipeline:
            self._audio_status = "請先停止監聽，再切換音訊來源。"
            self.audioChanged.emit()
            return
        self._pending_audio_source = source_id
        if self.settings.values.get("remember_audio_source"):
            selected = next((item for item in self._audio_sources if item["id"] == source_id), None)
            if selected:
                self.settings.set("last_audio_source_label", selected["label"])
        self._audio_status = "已選擇來源，按「開始監聽」檢查音量。"
        self.audioChanged.emit()

    @Slot()
    def startAudioCapture(self) -> None:
        if self.audioBusy or not self._pending_audio_source:
            return
        self._audio_test_only = False
        self._cancel_start = False
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
            self._transcript = TranscriptCoordinator(
                self.sessions, session["session_id"], offset, initial_limit=120)
            self._visible_segment_limit = 120
            selected_source = next((item for item in self._audio_sources
                                    if item["id"] == self._pending_audio_source), None)
            if selected_source:
                self.sessions.set_audio_source(session["session_id"],
                                               f"{selected_source['label']} · PID {selected_source['pid']}")
            self._refresh_speakers()
            self._enqueue_pending_translations()
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
        if self.audioBusy and not self._audio_busy:
            self._audio_status = "正在釋放語音辨識元件，請稍候…"
            self.audioChanged.emit()
            return
        if self._audio_busy:
            self._cancel_start = True
            self._audio_status = "正在取消啟動…"
            self.audioChanged.emit()
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
        if self._cancel_start and self.audio.state == "capturing":
            self._cancel_start = False
            self.stopAudioCapture()
            return
        self._audio_status = error or ("正在擷取指定程式音訊" if self.audio.state == "capturing" else "已停止監聽")
        self.audioChanged.emit()
        if not error and self.audio.state == "capturing":
            self._source_error_handled = False
            self._last_audible_at = time.monotonic()
            if not self._audio_test_only:
                self._start_asr()
        elif self.audio.state != "capturing" and self._asr_pipeline:
            self._asr_pipeline.stop()
        if self.audio.state != "capturing":
            self._audio_test_only = False
        if self._finish_requested and self.audio.state == "capturing":
            self.stopAudioCapture()
        elif self._finish_requested and not self._asr_pipeline and self.audio.state != "capturing":
            self._finish_requested = False
            self._complete_session()

    def _start_asr(self) -> None:
        if self._asr_thread and self._asr_thread.is_alive():
            return
        if self._transcript and self._diarization_factory:
            try:
                self._diarization_epoch += 1
                epoch = self._diarization_epoch
                diarization = self._diarization_factory()
                diarization.reset_session(self.sessions.list_speakers(self._transcript.session_id),
                                           self.sessions.list_embeddings(self._transcript.session_id))
                if hasattr(diarization, "set_next_number"):
                    diarization.set_next_number(self.sessions.next_speaker_number(self._transcript.session_id))
                diarization.on_speaker_detected(lambda speaker: self.diarizationNew.emit(speaker, epoch))
                diarization.on_overlap_detected(lambda event: self.diarizationOverlap.emit(event, epoch))
                if hasattr(diarization, "on_updated"):
                    diarization.on_updated(lambda: self.diarizationUpdated.emit(epoch))
                diarization.start()
                self._diarization = diarization
                self._transcript.speaker_for_interval = diarization.get_speaker_for_interval
            except Exception:
                logging.exception("Diarization could not start; ASR continues")
                self._diarization = None
        pipeline = ASRPipeline(
            self.audio,
            self._asr_backend_factory,
            self.settings.values["source_language"],
            lambda result: self.asrRecognition.emit(result),
            lambda result: self.asrRecognition.emit(result),
            lambda state, message: self.asrStatusEvent.emit(state, message),
            lambda timestamp: self.asrAudioAnchor.emit(timestamp),
            lambda chunk: self._diarization.push_audio(chunk) if self._diarization else None,
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
        if result.is_final:
            self._asr_final_count += 1
        else:
            self._asr_partial_count += 1
        try:
            if result.is_final:
                if self._transcript.apply_final(result):
                    segment = next(item for item in self._transcript.finals
                                   if item["id"] == f"segment_{result.utterance_id}")
                    self._submit_translation(segment, True)
            else:
                if self._transcript.apply_partial(result):
                    self._submit_translation(self._transcript.live, False)
            self.transcriptChanged.emit()
        except Exception:
            logging.exception("Could not persist transcript")
            self._on_asr_status("error", "逐字稿無法保存，請檢查資料儲存位置。")

    @Slot(str, int)
    def _on_diarization_new(self, speaker_id: str, epoch: int = -1) -> None:
        if epoch != -1 and epoch != self._diarization_epoch:
            return
        if not self._transcript or not self._diarization:
            return
        try:
            first_ms = self._transcript.offset_ms + getattr(
                self._diarization, "joined_ms", lambda _speaker: 0)(speaker_id)
            created = self.sessions.register_speaker(
                self._transcript.session_id, speaker_id, first_ms,
                getattr(self._diarization, "get_representation", lambda _speaker: None)(speaker_id))
            if not created and speaker_id not in self.sessions.list_embeddings(self._transcript.session_id):
                embedding = getattr(self._diarization, "get_representation", lambda _speaker: None)(speaker_id)
                if embedding:
                    self.sessions.add_embedding(self._transcript.session_id, speaker_id, embedding)
            if created:
                self._speaker_new_until[speaker_id] = time.monotonic() + 6
                self._message = f"偵測到新聲音 · {speaker_id}"
                self.changed.emit()
            self._refresh_speakers()
        except Exception:
            logging.exception("Speaker registration failed")

    @Slot(int)
    def _on_diarization_updated(self, epoch: int = -1) -> None:
        if epoch != -1 and epoch != self._diarization_epoch:
            return
        if not self._transcript or not self._diarization:
            return
        try:
            session_id = self._transcript.session_id
            representations = getattr(self._diarization, "get_representations", None)
            if representations:
                stored = self.sessions.list_embeddings(session_id)
                for speaker in self.sessions.list_speakers(session_id):
                    speaker_id = speaker["speaker_id"]
                    for vector in representations(speaker_id)[len(stored.get(speaker_id, [])):]:
                        self.sessions.add_embedding(session_id, speaker_id, vector)
            changed = False
            for item in self._transcript.finals[-32:]:
                if item.get("type") != "speech" or item.get("speaker_id") not in (None, "unknown"):
                    continue
                start = item["start_ms"] - self._transcript.offset_ms
                end = item["end_ms"] - self._transcript.offset_ms
                decision = self._diarization.get_speaker_for_interval(start, end)
                if decision.speaker_id and self.sessions.update_automatic_assignment(
                        session_id, item["id"], decision.speaker_id, decision.confidence):
                    item.update(speaker_id=decision.speaker_id,
                                speaker_confidence=round(decision.confidence, 3),
                                speaker_assignment="automatic")
                    changed = True
            if changed:
                self._refresh_speakers()
            else:
                self.transcriptChanged.emit()
        except Exception:
            logging.exception("Diarization update failed; ASR continues")

    @Slot(object, int)
    def _on_diarization_overlap(self, observation: SpeakerObservation, epoch: int = -1) -> None:
        if epoch != -1 and epoch != self._diarization_epoch:
            return
        if not self._transcript:
            return
        try:
            session_id = self._transcript.session_id
            start = self._transcript.offset_ms + observation.start_ms
            end = self._transcript.offset_ms + observation.end_ms
            if self.sessions.append_overlap_event(session_id, start, end,
                                                  list(observation.speaker_ids),
                                                  "overlapping_speech" if len(observation.speaker_ids) > 1
                                                  else "unknown_overlap", observation.confidence):
                self._transcript.reload_loaded()
                self.transcriptChanged.emit()
        except Exception:
            logging.exception("Overlap event could not be saved")

    def _submit_translation(self, segment: dict, final: bool) -> bool:
        if not segment or not self._transcript:
            return False
        recent = [item["original"] for item in self._transcript.finals
                  if item.get("type") == "speech" and item.get("original") and
                  item["id"] != segment["id"] and
                  0 <= segment["start_ms"] - item["end_ms"] <= 30000][-5:]
        session = self.sessions.get(self._transcript.session_id) or {}
        request = TranslationRequest(
            segment["id"], segment["original"], segment["language"],
            str(session.get("target_language", self.settings.values["target_language"])),
            str(session.get("translation_style", self.settings.values["translation_style"])),
            tuple(recent), tuple(self.glossary.list()), final, self._transcript.session_id)
        submitted = self._translation_pipeline.submit(request)
        if submitted:
            self._translation_status = "翻譯中…"
            self.transcriptChanged.emit()
        return submitted

    @Slot(object, object, float, str)
    def _on_translation_ready(self, request: TranslationRequest, result: str | None,
                              latency: float, error: str) -> None:
        if error:
            self._translation_ready = False
            self._translation_status = "原文辨識正常 · 翻譯暫時不可用：" + error
            if request.final:
                attempts = min(6, self._translation_retry_counts.get(request.segment_id, 0) + 1)
                self._translation_retry_counts[request.segment_id] = attempts
                self._translation_retry_after[request.segment_id] = time.monotonic() + min(900, 30 * 2 ** (attempts - 1))
                if len(self._translation_retry_after) > 256:
                    expired = next(iter(self._translation_retry_after))
                    self._translation_retry_after.pop(expired)
                    self._translation_retry_counts.pop(expired, None)
        elif result:
            self._translation_ready = True
            logging.info("Translation latency: kind=%s ms=%.1f", "final" if request.final else "partial", latency)
            translation = {"target": request.target_language, "style": request.style, "text": result}
            try:
                if request.final:
                    changed = self.sessions.update_final_translation(request.session_id, request.segment_id, translation)
                    self._translation_retry_after.pop(request.segment_id, None)
                    self._translation_retry_counts.pop(request.segment_id, None)
                    if changed and (self.sessions.get(request.session_id) or {}).get("status") == "completed":
                        self.sessions.render_exports(
                            request.session_id, str(self.settings.values["subtitle_mode"]))
                    if changed and self._transcript and self._transcript.session_id == request.session_id:
                        for item in self._transcript.finals:
                            if item["id"] == request.segment_id:
                                item["translation"] = translation
                                item["translation_state"] = "final"
                                item["translation_status"] = "final"
                                break
                elif self._transcript and self._transcript.session_id == request.session_id:
                    self._transcript.apply_partial_translation(request.segment_id, request.original, translation)
                self._translation_status = "翻譯正常"
                self._translation_latency_ms = latency if self._translation_latency_ms is None else (0.7 * self._translation_latency_ms + 0.3 * latency)
            except Exception:
                logging.exception("Translation persistence failed")
                self._translation_status = "翻譯無法保存，原文仍保留。"
        self.transcriptChanged.emit()

    @Slot()
    def _enqueue_pending_translations(self) -> None:
        if not self._transcript:
            return
        try:
            quiet = not self._finalizing and (self.audio.state != "capturing" or
                                               time.monotonic() - self._last_audible_at > 30)
            if quiet and time.monotonic() < self._idle_translation_retry_at:
                return
            for segment in self.sessions.pending_translations(self._transcript.session_id):
                if time.monotonic() >= self._translation_retry_after.get(segment["id"], 0):
                    submitted = self._submit_translation(segment, True)
                    if quiet and submitted:
                        self._idle_translation_retry_at = time.monotonic() + 30
                        break
        except Exception:
            logging.exception("Pending translation scan failed")

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
        self._diarization_epoch += 1
        if self._diarization:
            self._diarization.stop()
            self._diarization = None
        self._asr_pipeline = None
        self._asr_thread = None
        self.audioChanged.emit()
        if self._finish_requested:
            self._finish_requested = False
            self._complete_session()

    @Slot()
    def _poll_audio(self) -> None:
        self._display_peak = max(float(self.audio.peak), self._display_peak * 0.72)
        now = time.monotonic()
        if self.audio.state == "capturing" and float(self.audio.peak) >= 0.002:
            self._last_audible_at = now
        expired = [speaker for speaker, until in self._speaker_new_until.items() if now >= until]
        if expired:
            for speaker in expired:
                self._speaker_new_until.pop(speaker, None)
            self.transcriptChanged.emit()
        if self.audio.state == "capturing" and now - self._last_pipeline_log >= 10:
            self._last_pipeline_log = now
            backend = self._asr_pipeline._backend if self._asr_pipeline else None
            logging.info("Pipeline metrics: asr=%s partials=%d finals=%d audio_peak=%.3f "
                         "asr_queue_bytes=%s asr_dropped=%s gap_finals=%s infer_pending=%s infer_busy=%s "
                         "diarization=%s windows=%s dropped=%s translation_queue=%s diarization_queue=%s",
                         self._asr_state, self._asr_partial_count, self._asr_final_count,
                         self.audio.peak,
                         getattr(getattr(backend, "queue", None), "size_bytes", None),
                         getattr(getattr(backend, "queue", None), "dropped_bytes", None),
                         getattr(backend, "gap_finalizations", None),
                         getattr(getattr(backend, "_requests", None), "qsize", lambda: None)(),
                         getattr(backend, "_inference_busy", None),
                         getattr(self._diarization, "status", None),
                         getattr(self._diarization, "processed_windows", None),
                         getattr(self._diarization, "dropped_chunks", None),
                         len(self._translation_pipeline.queue),
                         getattr(getattr(self._diarization, "_queue", None), "qsize", lambda: 0)())
        if self.audio.state == "error" and self._audio_status != self.audio.error:
            self._audio_status = self.audio.error
            self.refreshAudioSources()
        if (self.audio.state == "error" and not self._source_error_handled and
                self.settings.values.get("auto_finalize_source_closed") and
                self.selectedSession.get("status") == "active"):
            self._source_error_handled = True
            self._finish_requested = True
            if self._asr_pipeline:
                self._asr_pipeline.stop()
            else:
                self._finish_requested = False
                self._complete_session()
        silence_minutes = int(self.settings.values.get("silence_timeout_minutes", 0) or 0)
        if (silence_minutes > 0 and self.audio.state == "capturing" and
                not self._finish_requested and
                now - self._last_audible_at >= silence_minutes * 60 and
                self.selectedSession.get("status") == "active"):
            self._finish_requested = True
            self._message = f"已連續 {silence_minutes} 分鐘未收到聲音，正在完成 Session。"
            self.changed.emit()
            self.stopAudioCapture()
        self.audioChanged.emit()

    def shutdown(self) -> None:
        self._shutting_down = True
        self._audio_timer.stop()
        self._source_timer.stop()
        self._pending_timer.stop()
        self._translation_pipeline.stop()
        self.model_manager.close()
        if self._diarization:
            self._diarization.stop()
        if self._asr_pipeline:
            self._asr_pipeline.stop()
        if self.audio.state in ("capturing", "connecting", "error"):
            asyncio.run(self.audio.stop())
        if self._asr_thread and self._asr_thread.is_alive():
            self._asr_thread.join(timeout=10)
        if self._refresh_thread and self._refresh_thread.is_alive():
            self._refresh_thread.join(timeout=15)
        QCoreApplication.processEvents()

    @Slot()
    def createSession(self) -> None:
        if self.audioBusy or self.audio.state == "capturing" or self._asr_pipeline or self._finalizing:
            self._message = "請先停止監聽，再建立新的 Session。"
            self.changed.emit()
            return
        values = self.settings.values
        session = self.sessions.create(source_language=values["source_language"],
                                       target_language=values["target_language"],
                                       translation_style=values["translation_style"])
        self._selected_id = session["session_id"]
        self._speaker_new_until.clear()
        self._transcript = TranscriptCoordinator(
            self.sessions, self._selected_id, initial_limit=120)
        self._visible_segment_limit = 120
        self._refresh_speakers()
        self._enqueue_pending_translations()
        self._message = "Session 已建立。開始監聽後，辨識結果會即時保存。"
        self.transcriptChanged.emit()
        self.changed.emit()

    @Slot(str)
    def selectSession(self, session_id: str) -> None:
        if self._audio_busy or self.audio.state == "capturing" or self._asr_pipeline:
            return
        if self.sessions.get(session_id):
            self._selected_id = session_id
            self._search_results = []
            self._focused_segment = {}
            self._speaker_new_until.clear()
            self._transcript = TranscriptCoordinator(
                self.sessions, session_id, initial_limit=120)
            self._visible_segment_limit = 120
            self._refresh_speakers()
            self._enqueue_pending_translations()
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
        if not session or session["status"] != "active" or self._finalizing:
            return
        self._finalizing = True
        self._finalize_deadline = time.monotonic() + 15
        if self._transcript:
            final_partial = self._transcript.finalize_live()
            if final_partial:
                self._submit_translation(final_partial, True)
        self._enqueue_pending_translations()
        self._message = "正在完成待處理翻譯與記錄檔…"
        self.changed.emit()
        QTimer.singleShot(100, self._finish_after_pending)

    @Slot()
    def _finish_after_pending(self) -> None:
        if not self._finalizing:
            return
        self._enqueue_pending_translations()
        pending = self._translation_pipeline.pending_final_count()
        if pending and time.monotonic() < self._finalize_deadline:
            QTimer.singleShot(200, self._finish_after_pending)
            return
        session = self.selectedSession
        try:
            if session and session["status"] == "active":
                self.sessions.finish(session["session_id"], str(self.settings.values["subtitle_mode"]))
            self._message = ("Session 已完成；逾時的翻譯保留為待補。" if pending else
                             "Session 已完成並輸出 Markdown、SRT、VTT。")
            should_close = bool(self.settings.values.get("auto_close_after_finalize"))
        except Exception:
            logging.exception("Session finalization failed")
            self._message = "完成記錄檔失敗，Session 尚未封存；請重試。"
            should_close = False
        self._finalizing = False
        self.changed.emit()
        if should_close:
            QTimer.singleShot(50, QCoreApplication.quit)

    @Slot(str, "QVariant")
    def setPreference(self, key: str, value: object) -> None:
        self.settings.set(key, value)
        if key == "start_with_windows":
            set_start_with_windows(bool(value))
        if key == "source_language" and self._asr_pipeline:
            self._asr_pipeline.set_language(str(value))
        if key == "source_language" and self._selected_id:
            self.sessions.set_source_language(self._selected_id, str(value))
        if key in ("target_language", "translation_style") and self._selected_id:
            self.sessions.set_translation_preferences(self._selected_id, key, str(value))
        if key in ("target_language", "translation_style"):
            self._enqueue_pending_translations()
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
