from __future__ import annotations


def normalize_geometry(saved: dict, screens: list[tuple[int, int, int, int]],
                       default: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Keep at least 80x40 pixels visible after monitor or DPI changes."""
    if not screens or not all(key in saved for key in ("x", "y", "width", "height")):
        return default
    x, y = int(saved["x"]), int(saved["y"])
    width, height = max(320, int(saved["width"])), max(72, int(saved["height"]))
    visible = any(x + width >= sx + 80 and x <= sx + sw - 80 and
                  y + height >= sy + 40 and y <= sy + sh - 40
                  for sx, sy, sw, sh in screens)
    return (x, y, width, height) if visible else default

