"""Offscreen production-QML allocation probe, without capture or model inference."""
import argparse
import gc
import json
import os
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QUICK_BACKEND"] = "software"
os.environ["QT_QUICK_CONTROLS_STYLE"] = "Material"
os.environ["QT_QUICK_CONTROLS_MATERIAL_THEME"] = "Dark"

import psutil
from PySide6.QtCore import QTimer
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication
from vlt.audio.windows_process_loopback import WindowsProcessLoopback
from vlt.database.database import Database
from vlt.sessions.manager import SessionManager
from vlt.settings.manager import SettingsManager
from vlt.subtitles.live import TranscriptCoordinator
from vlt.ui.controller import StudioController


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    root = parser.parse_args().root
    root.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    db = Database(root / "app.db")
    sessions = SessionManager(root, db)
    session = sessions.create("Synthetic QML memory probe")
    sid = session["session_id"]
    for index in range(3):
        sessions.add_speaker(sid, index * 1000)
    for index in range(120):
        sessions.append_final(sid, {"id": str(index), "type": "speech", "asr_state": "final",
                                   "start_ms": index * 2000, "end_ms": index * 2000 + 1500,
                                   "speaker_id": "unknown", "language": "ja",
                                   "translation_state": "final", "translation_status": "final",
                                   "original": "今日はみんなとゲームをやっていきます。",
                                   "translation": {"text": "今天要和大家一起玩遊戲。", "target": "zh-TW"}})
    settings = SettingsManager(root)
    settings.set("first_run_complete", True)
    controller = StudioController(sessions, settings, lambda: None,
                                  audio=WindowsProcessLoopback(source_provider=lambda: []),
                                  translation_backend_factory=lambda: None)
    controller._translation_pipeline.stop()
    for timer in (controller._audio_timer, controller._source_timer, controller._pending_timer):
        timer.stop()
    controller.selectSession(sid)
    controller._transcript = TranscriptCoordinator(sessions, sid, initial_limit=120)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("studio", controller)
    engine.load(Path("src/vlt/ui/qml/Main.qml").resolve())
    assert engine.rootObjects()
    process, rows = psutil.Process(), []
    count = 0
    def record(label):
        gc.collect()
        row = {"stage": label, "private_mib": process.memory_info().private / 1024**2,
               "rss_mib": process.memory_info().rss / 1024**2, "handles": process.num_handles()}
        rows.append(row)
        print(json.dumps(row), flush=True)
    def tick():
        nonlocal count
        if count % 50 == 0:
            record(f"updates_{count}")
        if count == 300:
            timer.stop()
            engine.collectGarbage()
            QTimer.singleShot(1000, finish)
            return
        controller._transcript.finals[-1]["original"] = f"今日はみんなとゲームをやっていきます。 {count}"
        controller.transcriptChanged.emit()
        count += 1
    def finish():
        record("after_qml_gc")
        (root / "result.json").write_text(json.dumps(rows, indent=2), encoding="utf8")
        controller.shutdown()
        app.quit()
    timer = QTimer(app)
    timer.setInterval(50)
    timer.timeout.connect(tick)
    QTimer.singleShot(1500, timer.start)
    app.exec()
    db.close()


if __name__ == "__main__":
    main()
