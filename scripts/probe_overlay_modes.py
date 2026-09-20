"""Render all three real-data Overlay modes into ignored local PNGs for visual QA."""
import os
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from shiboken6 import getCppPointer, wrapInstance

from vlt.database.database import Database
from vlt.sessions.manager import SessionManager
from vlt.settings.manager import SettingsManager, data_directory
from vlt.ui.controller import StudioController


class QuietAudio:
    state = "idle"
    peak = 0.0
    async def list_sources(self): return []


root = data_directory()
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Material")
os.environ.setdefault("QT_QUICK_CONTROLS_MATERIAL_THEME", "Dark")
app = QGuiApplication([])
db = Database(root / "app.db")
sessions = SessionManager(root, db)
settings = SettingsManager(root)
previous = settings.values["overlay_mode"]
controller = StudioController(sessions, settings, lambda: None, audio=QuietAudio())
controller.selectSession(sessions.list_sessions()[0]["session_id"])
controller.toggleOverlay()
engine = QQmlApplicationEngine()
engine.rootContext().setContextProperty("studio", controller)
engine.load(Path(__file__).resolve().parents[1] / "src/vlt/ui/qml/Overlay.qml")
assert engine.rootObjects()
overlay = wrapInstance(getCppPointer(engine.rootObjects()[0])[0], QQuickWindow)


def capture(index=0):
    if index == 3:
        settings.set("overlay_mode", previous)
        controller.changed.emit()
        app.quit()
        return
    mode = ("gaming", "watching", "minimal")[index]
    settings.set("overlay_mode", mode)
    controller.changed.emit()
    path = root / f"overlay_{mode}_verified.png"
    QTimer.singleShot(400, lambda: save(index, path))


def save(index, path):
    assert overlay.grabWindow().save(str(path))
    print(f"{index} {path} {controller.overlaySegment.get('translation', {}).get('text', '')}", flush=True)
    capture(index + 1)


QTimer.singleShot(600, capture)
try:
    app.exec()
finally:
    controller.shutdown()
    db.close()
