from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Property, Signal, Slot, QUrl
from PySide6.QtGui import QDesktopServices

from vlt.sessions.manager import SessionManager
from vlt.settings.manager import SettingsManager


class StudioController(QObject):
    changed = Signal()

    def __init__(self, sessions: SessionManager, settings: SettingsManager):
        super().__init__()
        self.sessions = sessions
        self.settings = settings
        self._selected_id = ""
        self._overlay_visible = False
        self._message = "目前為 Phase 1。音訊擷取與即時翻譯尚未接入。"

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

    @Slot()
    def createSession(self) -> None:
        values = self.settings.values
        session = self.sessions.create(source_language=values["source_language"],
                                       target_language=values["target_language"],
                                       translation_style=values["translation_style"])
        self._selected_id = session["session_id"]
        self._message = "空白 Session 已建立。翻譯功能會在後續階段接入。"
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

