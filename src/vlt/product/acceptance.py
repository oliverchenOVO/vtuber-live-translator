"""Explicit, opt-in packaged RC probes. Never run during ordinary application use."""
from __future__ import annotations

import json
import time
from pathlib import Path

import psutil
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtQuick import QQuickWindow
from shiboken6 import getCppPointer, wrapInstance


def install_probe(app, controller, main_window, overlay, root: Path, save_window, *, cycles=False,
                  resume=False, finish_after_s=0):
    process = psutil.Process()
    started = time.monotonic()
    output = root / "acceptance.jsonl"
    state = {"stage": "choose", "cycle": 0, "at": started, "session": "", "exercise": -1}
    def record(event, **values):
        mem = process.memory_info()
        data = {"event": event, "elapsed_s": time.monotonic() - started,
                "cycle": state["cycle"], "session_id": controller._selected_id,
                "rss_mb": mem.rss / 1024**2, "private_mb": mem.private / 1024**2,
                "threads": process.num_threads(), "handles": process.num_handles(), **values}
        with output.open("a", encoding="utf8") as target:
            target.write(json.dumps(data, ensure_ascii=False) + "\n")
    def fail(message):
        record("failed", message=message)
        timer.stop()
        app.exit(2)
    def tick():
        now = time.monotonic()
        if state["stage"] == "choose":
            chrome = next((s for s in controller.audioSources if s["label"].lower() == "chrome.exe"), None)
            if not chrome:
                if now - state["at"] > 30:
                    fail("Chrome audio source not available")
                return
            if resume and controller.interruptedSession:
                controller.continueInterruptedSession(controller.interruptedSession["session_id"])
            controller.selectAudioSource(chrome["id"])
            controller.startAudioCapture()
            state.update(stage="starting", at=now)
        elif state["stage"] == "starting":
            if controller.asrState == "live" and getattr(controller._diarization, "status", None) == "live":
                if state["session"] and state["session"] != controller._selected_id:
                    fail("Start/Stop unexpectedly changed Session identity"); return
                state["session"] = controller._selected_id
                record("ready", start_seconds=now - state["at"], stages=controller.startupStages)
                state.update(stage="listening", at=now)
            elif now - state["at"] > 90:
                fail("Audio/ASR/Speaker startup timeout")
        elif state["stage"] == "listening":
            if finish_after_s and now - started >= finish_after_s:
                controller.finishSession()
                state.update(stage="finishing", at=now)
                record("finalizing")
            elif cycles and now - state["at"] > 5:
                controller.stopAudioCapture()
                state.update(stage="stopping", at=now)
            elif not cycles:
                # Exercise Studio hide/restore, History and Overlay modes at 15-minute intervals.
                interval = int((now - started) // 900)
                if interval != state["exercise"]:
                    state["exercise"] = interval
                    main_window.hide()
                    QTimer.singleShot(150, main_window.show)
                    QTimer.singleShot(200, lambda: main_window.setProperty("page", "History"))
                    QTimer.singleShot(1000, lambda: main_window.setProperty("page", "LIVE"))
                    controller.setPreference("overlay_mode", ("gaming", "watching", "minimal")[interval % 3])
                    if not controller.overlayVisible:
                        controller.toggleOverlay()
                    QTimer.singleShot(1800, lambda: save_window(main_window, str(root / f"studio-{interval:02d}.png")))
                    QTimer.singleShot(1800, lambda: save_window(overlay, str(root / f"overlay-{interval:02d}.png")))
                    record("ui_exercise", mode=controller.preferences["overlay_mode"],
                           history_count=len(controller.history), live_rows=len(controller.transcriptSegments))
        elif state["stage"] == "finishing":
            if controller.selectedSession.get("status") == "completed":
                record("completed", live=bool(controller.liveSegment))
                timer.stop(); app.quit()
            elif now - state["at"] > 90:
                fail("Session finalization timeout")
        elif state["stage"] == "stopping":
            if not controller.audioBusy and not controller._asr_pipeline and controller.audioState != "capturing":
                if controller.liveSegment:
                    fail("LIVE transcript remained after Stop"); return
                if len(controller.sessions.list_sessions()) != 1:
                    fail("Repeated listening created duplicate Sessions"); return
                record("stopped", stop_seconds=now - state["at"], live=False,
                       diarization_released=controller._diarization is None)
                state["cycle"] += 1
                if state["cycle"] >= 20:
                    record("passed", cycles=20)
                    timer.stop(); app.quit()
                else:
                    controller.startAudioCapture()
                    state.update(stage="starting", at=now)
            elif now - state["at"] > 60:
                fail("Stop timeout")
    timer = QTimer(app)
    timer.setInterval(250)
    timer.timeout.connect(tick)
    timer.start()
    record("started", kind="cycles" if cycles else "soak")


def install_ui_probe(app, controller, main_window, overlay, root: Path, save_window):
    """Render the real QML and send Qt key events; this is not a physical mouse audit."""
    quick = wrapInstance(getCppPointer(main_window)[0], QQuickWindow)
    main_window.setWidth(1380); main_window.setHeight(830)
    main_window.show(); main_window.requestActivate()
    rows = controller.sessions.list_sessions()
    if rows:
        controller.selectSession(rows[0]["session_id"])
    result = []
    def check(name, passed):
        result.append({"check": name, "passed": bool(passed)})
    def keys():
        QTest.keyClick(quick, Qt.Key_H, Qt.ControlModifier)
        check("Ctrl+H History", main_window.property("page") == "History")
        QTest.keyClick(quick, Qt.Key_L, Qt.ControlModifier)
        check("Ctrl+L LIVE", main_window.property("page") == "LIVE")
        before = controller.overlayVisible
        QTest.keyClick(quick, Qt.Key_O, Qt.ControlModifier)
        check("Ctrl+O Overlay", controller.overlayVisible != before)
        main_window.setProperty("trayPromptVisible", True)
        QTest.keyClick(quick, Qt.Key_Escape)
        check("Escape dialog", not main_window.property("trayPromptVisible"))
        QTest.keyClick(quick, Qt.Key_Tab)
        check("Tab focus", quick.activeFocusItem() is not None)
        nav = quick.activeFocusItem()
        if nav:
            QTest.keyClick(quick, Qt.Key_Return)
            check("Enter navigation", main_window.property("page") in ("LIVE", "History", "Speakers", "Dictionary", "Exports", "Settings"))
        controller.setPreference("overlay_locked", False)
        QTimer.singleShot(100, edit_overlay)
    def edit_overlay():
        check("overlay edit flags", not bool(overlay.property("flags") & Qt.WindowTransparentForInput))
        overlay.setX(120); overlay.setY(120); overlay.setWidth(720); overlay.setHeight(160)
        controller.setPreference("overlay_opacity", .65)
        controller.setPreference("overlay_mode", "watching")
        controller.setPreference("overlay_locked", True)
        QTimer.singleShot(100, lock_overlay)
    def lock_overlay():
        check("overlay passthrough flags", bool(overlay.property("flags") & Qt.WindowTransparentForInput))
        if not controller.overlayVisible:
            controller.toggleOverlay()
        for index, page in enumerate(("LIVE", "Speakers", "History", "Settings", "Exports")):
            QTimer.singleShot(index * 1000, lambda value=page: main_window.setProperty("page", value))
            QTimer.singleShot(index * 1000 + 650, lambda value=page: save_window(main_window, str(root / f"ui-{value}.png")))
        QTimer.singleShot(4700, lambda: save_window(overlay, str(root / "ui-overlay.png")))
        QTimer.singleShot(5200, complete)
    def complete():
        check("geometry persisted", controller.settings.values["overlay_geometry"].get("width") == 720)
        (root / "ui-results.json").write_text(json.dumps(result, indent=2), encoding="utf8")
        app.exit(0 if all(r["passed"] for r in result) else 2)
    QTimer.singleShot(1200, keys)
