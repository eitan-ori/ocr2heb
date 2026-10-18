"""Screen capture of the monitor the mouse cursor is on (physical pixels)."""
from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes
from typing import Tuple

log = logging.getLogger("ocr2heb.capture")

Rect = Tuple[int, int, int, int]  # left, top, width, height


def cursor_pos() -> Tuple[int, int]:
    pt = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def _pick_monitor(monitors, point):
    px, py = point
    for m in monitors:
        if m["left"] <= px < m["left"] + m["width"] and m["top"] <= py < m["top"] + m["height"]:
            return m
    return monitors[0]


def monitor_rect_under_cursor() -> Rect:
    import mss
    with mss.mss() as sct:
        mons = list(sct.monitors[1:]) or [sct.monitors[0]]
        m = _pick_monitor(mons, cursor_pos())
        return m["left"], m["top"], m["width"], m["height"]


def grab_screen_under_cursor():
    """Return (PIL.Image RGB, (left, top, width, height)) for the cursor's monitor."""
    import mss
    from PIL import Image

    with mss.mss() as sct:
        mons = list(sct.monitors[1:]) or [sct.monitors[0]]
        m = _pick_monitor(mons, cursor_pos())
        shot = sct.grab(m)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    rect = (m["left"], m["top"], m["width"], m["height"])
    log.info("captured %dx%d at (%d,%d)", img.width, img.height, rect[0], rect[1])
    return img, rect
