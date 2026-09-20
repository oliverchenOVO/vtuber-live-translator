"""Manual offline recovery probe against the selected existing Session (no new Session)."""
import json
import sys
import time
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from vlt.database.database import Database
from vlt.sessions.manager import SessionManager
from vlt.settings.manager import SettingsManager, data_directory
from vlt.ui.controller import StudioController


class QuietAudio:
    state = "idle"
    peak = 0.0

    async def list_sources(self):
        return []


def main():
    root = data_directory()
    app = QCoreApplication([])
    db = Database(root / "app.db")
    manager = SessionManager(root, db)
    session_id = sys.argv[1] if len(sys.argv) > 1 else manager.list_sessions()[0]["session_id"]
    session = manager.get(session_id)
    assert session
    before = len(manager.pending_translations(session_id))
    if session["status"] == "interrupted":
        manager.resume(session_id)
    controller = StudioController(manager, SettingsManager(root), lambda: None, audio=QuietAudio())
    controller.selectSession(session_id)
    start = time.monotonic()
    while manager.pending_translations(session_id) and time.monotonic() - start < 60:
        app.processEvents()
        time.sleep(0.05)
    app.processEvents()
    after = len(manager.pending_translations(session_id))
    report = {"session_id": session_id, "same_folder": manager.get(session_id)["folder_path"] == session["folder_path"],
              "pending_before": before, "pending_after": after,
              "session_count": len(manager.list_sessions()), "seconds": round(time.monotonic() - start, 2)}
    print(json.dumps(report, ensure_ascii=False))
    controller.shutdown()
    db.close()
    return int(after != 0)


if __name__ == "__main__":
    raise SystemExit(main())
