from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from vlt.database.database import Database
from vlt.sessions.manager import SessionManager
from vlt.settings.manager import SettingsManager, data_directory
from vlt.ui.controller import StudioController


def main() -> int:
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Material")
    os.environ.setdefault("QT_QUICK_CONTROLS_MATERIAL_THEME", "Dark")
    os.environ.setdefault("QT_QUICK_CONTROLS_MATERIAL_ACCENT", "Teal")
    root = data_directory()
    root.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=root / "app.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    database = Database(root / "app.db")
    sessions = SessionManager(root, database)
    interrupted = sessions.mark_interrupted()
    if interrupted:
        logging.warning("Marked %d unfinished session(s) as interrupted", interrupted)

    app = QGuiApplication(sys.argv)
    app.setApplicationName("Vtuber Live Translator")
    app.setOrganizationName("VtuberLiveTranslator")
    families = set(QFontDatabase.families())
    for family in ("Microsoft JhengHei UI", "Noto Sans TC", "Microsoft YaHei UI"):
        if family in families:
            app.setFont(QFont(family, 10))
            break
    settings = SettingsManager(root)
    controller = StudioController(sessions, settings)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("studio", controller)
    qml_dir = Path(__file__).parent / "ui" / "qml"
    engine.load(qml_dir / "Main.qml")
    if not engine.rootObjects():
        database.close()
        return 1
    engine.load(qml_dir / "Overlay.qml")
    if len(engine.rootObjects()) != 2:
        database.close()
        return 1
    if "--smoke-test" in sys.argv:
        screenshot = os.environ.get("VLT_SCREENSHOT_PATH")
        if screenshot:
            from shiboken6 import getCppPointer, wrapInstance
            from PySide6.QtQuick import QQuickWindow
            quick_window = wrapInstance(getCppPointer(engine.rootObjects()[0])[0], QQuickWindow)
            QTimer.singleShot(200, lambda: quick_window.grabWindow().save(screenshot))
        QTimer.singleShot(350, app.quit)
    try:
        return app.exec()
    finally:
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
