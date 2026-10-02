"""Capture the real Studio view of a completed Phase 10B candidate Session.

This uses the application's existing Qt smoke screenshot path.  It does not
inject transcript rows, start audio, or change the product backend selection.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from PySide6.QtCore import QTimer

from vlt.settings.manager import SettingsManager
import vlt.app as product_app


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--language", choices=("ja", "en"), required=True)
    args = parser.parse_args()
    data_root = (ROOT / "data/phase10b" / f"live-gemma-{args.language}").resolve()
    if not (data_root / "app.db").exists():
        raise FileNotFoundError("Run the real Chrome Session before capturing Studio")
    screenshot = ROOT / "data/phase10b/screenshots" / f"studio-gemma-{args.language}.png"
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    SettingsManager(data_root).set("first_run_complete", True)
    os.environ["VLT_DATA_DIR"] = str(data_root)
    os.environ["VLT_SCREENSHOT_PATH"] = str(screenshot)

    controller_class = product_app.StudioController

    def select_recorded_session(*ctor_args, **ctor_kwargs):
        controller = controller_class(*ctor_args, **ctor_kwargs)
        finished = next((row for row in controller.sessions.list_sessions()
                         if row["status"] == "completed"), None)
        if finished is None:
            raise RuntimeError("No completed real Session to show")
        QTimer.singleShot(200, lambda: controller.selectSession(finished["session_id"]))
        return controller

    product_app.StudioController = select_recorded_session
    sys.argv = [sys.argv[0], "--smoke-test"]
    result = product_app.main()
    if not screenshot.is_file():
        raise RuntimeError("Studio screenshot was not saved")
    print(screenshot, flush=True)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
