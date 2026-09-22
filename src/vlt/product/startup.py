from __future__ import annotations

import sys
from pathlib import Path


def set_start_with_windows(enabled: bool, executable: Path | None = None) -> None:
    if sys.platform != "win32":
        return
    import winreg
    path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            value = f'"{executable or Path(sys.executable)}" --startup'
            winreg.SetValueEx(key, "VtuberLiveTranslator", 0, winreg.REG_SZ, value)
        else:
            try:
                winreg.DeleteValue(key, "VtuberLiveTranslator")
            except FileNotFoundError:
                pass

