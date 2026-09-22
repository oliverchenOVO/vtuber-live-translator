from __future__ import annotations

import logging
import os
import sys
import threading
import ctypes
import traceback as traceback_module
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QFont, QFontDatabase, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon
from shiboken6 import getCppPointer, wrapInstance

from vlt.asr.faster_whisper_backend import FasterWhisperBackend
from vlt.database.database import Database
from vlt.diarization.sherpa_backend import SherpaOnnxDiarizationBackend
from vlt.product.hardware import preset
from vlt.product.compatibility import MINIMUM_WINDOWS_BUILD, supports_process_loopback, windows_build
from vlt.product.logging_setup import configure_logging
from vlt.product.paths import ProductPaths
from vlt.product.single_instance import SingleInstance
from vlt.product.startup import set_start_with_windows
from vlt.product.windowing import normalize_geometry
from vlt.sessions.manager import SessionManager
from vlt.settings.manager import SettingsManager
from vlt.translation.ollama_backend import OllamaTranslationBackend
from vlt.ui.controller import StudioController
from vlt.version import PRODUCT_NAME, __version__


def resource_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    packaged = base.joinpath(*parts)
    return packaged if packaged.exists() else Path(__file__).parent.joinpath(*parts)


def _save_quick_window(window, path: str) -> None:
    quick_window = wrapInstance(getCppPointer(window)[0], QQuickWindow)
    quick_window.grabWindow().save(path)


def _install_crash_handlers(paths: ProductPaths, sessions: SessionManager) -> None:
    def handle(exc_type, exc, traceback) -> None:
        logging.critical("Uncaught application error", exc_info=(exc_type, exc, traceback))
        try:
            (paths.logs / "crash.log").write_text(
                "".join(traceback_module.format_exception(exc_type, exc, traceback)),
                encoding="utf-8")
        except OSError:
            logging.exception("Could not write crash report")
        try:
            sessions.mark_interrupted()
        except Exception:
            logging.exception("Could not mark active sessions interrupted")
        if QApplication.instance():
            QMessageBox.critical(None, PRODUCT_NAME,
                "應用程式遇到未預期的問題。已保留 Session，請重新開啟後繼續。\n\n"
                f"診斷記錄：{paths.logs}")
    sys.excepthook = handle
    if hasattr(threading, "excepthook"):
        threading.excepthook = lambda args: logging.critical(
            "Unhandled worker error in %s", args.thread.name,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback))


def main() -> int:
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "VtuberLiveTranslator.Desktop.1")
        except OSError:
            logging.exception("Could not set Windows AppUserModelID")
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Material")
    os.environ.setdefault("QT_QUICK_CONTROLS_MATERIAL_THEME", "Dark")
    os.environ.setdefault("QT_QUICK_CONTROLS_MATERIAL_ACCENT", "Teal")
    paths = ProductPaths.discover()
    paths.ensure()
    configure_logging(paths.logs)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName(PRODUCT_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("VtuberLiveTranslator")
    icon = resource_path("assets", "app.ico")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    if sys.platform == "win32" and not supports_process_loopback():
        build = windows_build()
        logging.error("Unsupported Windows build %s", build)
        QMessageBox.critical(None, PRODUCT_NAME,
            "此 Windows 版本不支援指定程式音訊擷取。\n\n"
            f"目前 Build：{build}\n最低需求：{MINIMUM_WINDOWS_BUILD}")
        return 1

    singleton = SingleInstance()
    if not singleton.acquire():
        return 0

    families = set(QFontDatabase.families())
    for family in ("Microsoft JhengHei UI", "Noto Sans TC", "Microsoft YaHei UI"):
        if family in families:
            app.setFont(QFont(family, 10))
            break

    settings = SettingsManager(paths.root)
    if settings.values["start_with_windows"]:
        set_start_with_windows(True)
    session_root = Path(settings.values["session_root"]) if settings.values["session_root"] else paths.sessions
    database = Database(paths.root / "app.db")
    sessions = SessionManager(paths.root, database, session_root=session_root)
    interrupted = sessions.mark_interrupted()
    if interrupted:
        logging.warning("Marked %d unfinished session(s) as interrupted", interrupted)
    _install_crash_handlers(paths, sessions)

    def asr_backend() -> FasterWhisperBackend:
        selected = preset(str(settings.values["performance_preset"]))
        return FasterWhisperBackend(
            selected["asr_model"], paths.models, selected["asr_device"], selected["cpu_threads"])

    def translation_backend() -> OllamaTranslationBackend:
        selected = preset(str(settings.values["performance_preset"]))
        return OllamaTranslationBackend(
            model=selected["translation_model"], allow_fallback=selected["translation_fallback"],
            cpu_threads=selected["cpu_threads"])

    def diarization_backend() -> SherpaOnnxDiarizationBackend:
        selected = preset(str(settings.values["performance_preset"]))
        return SherpaOnnxDiarizationBackend(
            paths.models / "diarization", max_speakers=selected["max_speakers"],
            process_interval_ms=selected["diarization_interval_ms"])

    controller = StudioController(
        sessions, settings,
        asr_backend_factory=asr_backend,
        translation_backend_factory=translation_backend,
        diarization_backend_factory=diarization_backend)
    app.aboutToQuit.connect(controller.shutdown)

    engine = QQmlApplicationEngine()
    engine.warnings.connect(lambda warnings: [logging.error("QML: %s", warning.toString()) for warning in warnings])
    engine.rootContext().setContextProperty("studio", controller)
    qml_dir = resource_path("ui", "qml")
    engine.load(qml_dir / "Main.qml")
    if not engine.rootObjects():
        QMessageBox.critical(None, PRODUCT_NAME,
            f"介面無法載入。請重新安裝應用程式。\n\n診斷記錄：{paths.logs}")
        database.close()
        return 1
    engine.load(qml_dir / "Overlay.qml")
    if len(engine.rootObjects()) != 2:
        QMessageBox.critical(None, PRODUCT_NAME,
            f"Overlay 無法載入。請重新安裝應用程式。\n\n診斷記錄：{paths.logs}")
        database.close()
        return 1
    main_window = engine.rootObjects()[0]
    overlay_window = engine.rootObjects()[1]

    screens = [(g.x(), g.y(), g.width(), g.height())
               for screen in app.screens() for g in (screen.availableGeometry(),)]
    default_overlay = (overlay_window.x(), overlay_window.y(), overlay_window.width(), overlay_window.height())
    ox, oy, ow, oh = normalize_geometry(settings.values["overlay_geometry"], screens, default_overlay)
    overlay_window.setX(ox); overlay_window.setY(oy)
    overlay_window.setWidth(ow); overlay_window.setHeight(oh)
    def recover_overlay_after_screen_change(*_args) -> None:
        available = [(g.x(), g.y(), g.width(), g.height())
                     for screen in app.screens() for g in (screen.availableGeometry(),)]
        current = {"x": overlay_window.x(), "y": overlay_window.y(),
                   "width": overlay_window.width(), "height": overlay_window.height()}
        rx, ry, rw, rh = normalize_geometry(current, available, default_overlay)
        overlay_window.setX(rx); overlay_window.setY(ry)
        overlay_window.setWidth(rw); overlay_window.setHeight(rh)
    app.screenRemoved.connect(
        lambda _screen: QTimer.singleShot(0, recover_overlay_after_screen_change))
    geometry_timer = QTimer(app)
    geometry_timer.setSingleShot(True)
    geometry_timer.setInterval(350)
    def save_overlay_geometry() -> None:
        settings.set("overlay_geometry", {"x": overlay_window.x(), "y": overlay_window.y(),
                                           "width": overlay_window.width(), "height": overlay_window.height()})
    geometry_timer.timeout.connect(save_overlay_geometry)
    overlay_window.xChanged.connect(geometry_timer.start)
    overlay_window.yChanged.connect(geometry_timer.start)
    overlay_window.widthChanged.connect(geometry_timer.start)
    overlay_window.heightChanged.connect(geometry_timer.start)

    def activate() -> None:
        main_window.show()
        main_window.raise_()
        main_window.requestActivate()
    singleton.activateRequested.connect(activate)

    tray = QSystemTrayIcon(app.windowIcon(), app)
    menu = QMenu()
    show_action = QAction("開啟 Vtuber Live Translator", menu)
    show_action.triggered.connect(activate)
    menu.addAction(show_action)
    overlay_action = QAction("顯示／隱藏 Overlay", menu)
    overlay_action.triggered.connect(controller.toggleOverlay)
    menu.addAction(overlay_action)
    session_action = QAction("開始 Session", menu)
    def toggle_session() -> None:
        if controller.audioState == "capturing":
            controller.finishSession()
        else:
            controller.startAudioCapture()
    session_action.triggered.connect(toggle_session)
    menu.addAction(session_action)
    settings_action = QAction("設定", menu)
    def open_settings() -> None:
        main_window.setProperty("page", "Settings")
        activate()
    settings_action.triggered.connect(open_settings)
    menu.addAction(settings_action)
    menu.addSeparator()
    quit_action = QAction("結束", menu)
    quit_action.triggered.connect(app.quit)
    menu.addAction(quit_action)
    tray.setContextMenu(menu)
    tray.setToolTip(f"{PRODUCT_NAME} {__version__}")
    tray.activated.connect(lambda reason: activate() if reason == QSystemTrayIcon.DoubleClick else None)
    tray.show()

    controller.audioChanged.connect(lambda: session_action.setText(
        "停止 Session" if controller.audioState == "capturing" else "開始 Session"))
    if "--startup" in sys.argv and settings.values["start_minimized"]:
        QTimer.singleShot(0, main_window.hide)
    if settings.values["update_checks"] and os.environ.get("VLT_RELEASES_API"):
        QTimer.singleShot(3000, controller.checkForUpdates)

    if "--smoke-test" in sys.argv:
        screenshot = os.environ.get("VLT_SCREENSHOT_PATH")
        overlay_screenshot = os.environ.get("VLT_OVERLAY_SCREENSHOT_PATH")
        if screenshot:
            width = int(os.environ.get("VLT_SCREENSHOT_WIDTH", main_window.width()))
            height = int(os.environ.get("VLT_SCREENSHOT_HEIGHT", main_window.height()))
            main_window.setWidth(width)
            main_window.setHeight(height)
            QTimer.singleShot(1200, lambda: _save_quick_window(main_window, screenshot))
        if overlay_screenshot:
            if not controller.overlayVisible:
                controller.toggleOverlay()
            QTimer.singleShot(1200, lambda: _save_quick_window(
                overlay_window, overlay_screenshot))
        QTimer.singleShot(1800, app.quit)
    if any(flag in sys.argv for flag in ("--audio-smoke-test", "--asr-smoke-test", "--phase7-soak-test")):
        def start_test_audio() -> None:
            chrome = next((s for s in controller.audioSources if s["label"].casefold() == "chrome.exe"), None)
            if chrome:
                controller.selectAudioSource(chrome["id"])
                controller.startAudioCapture()
        QTimer.singleShot(1800, start_test_audio)
        if "--phase7-soak-test" not in sys.argv:
            QTimer.singleShot(30000 if "--asr-smoke-test" in sys.argv else 7000, app.quit)

    try:
        return app.exec()
    finally:
        database.close()


def run_guarded() -> int:
    try:
        return main()
    except Exception as exc:
        try:
            paths = ProductPaths.discover()
            paths.ensure()
            configure_logging(paths.logs)
            logging.critical("Fatal startup error", exc_info=True)
            (paths.logs / "crash.log").write_text(traceback_module.format_exc(), encoding="utf-8")
            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, PRODUCT_NAME,
                "應用程式無法啟動。請重新安裝，或從診斷記錄查看詳細資訊。\n\n"
                f"診斷記錄：{paths.logs}")
        except Exception:
            print(f"{PRODUCT_NAME} could not start: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run_guarded())
