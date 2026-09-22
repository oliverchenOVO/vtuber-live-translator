from __future__ import annotations

import platform


MINIMUM_WINDOWS_BUILD = 20348


def windows_build() -> int:
    try:
        return int(platform.version().split(".")[-1])
    except (TypeError, ValueError):
        return 0


def supports_process_loopback(build: int | None = None) -> bool:
    return (windows_build() if build is None else build) >= MINIMUM_WINDOWS_BUILD
