"""Renders every UI state with the REAL Qt painter into PNG files (no window is shown).

Contract used by the Windows bench task `render`:
    render_states(out_dir) -> list of written PNG paths
Add new states here when new UI is added (welcome window, tray icon, ...).
"""
from __future__ import annotations

import os
from typing import List

import config
from config import T


def _app():
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication
    QApplication.setAttribute(Qt.AA_DisableHighDpiScaling, True)
    return QApplication.instance() or QApplication([])


def composite(png_path: str, background, out_path: str) -> None:
    """Alpha-composite a transparent overlay PNG over a PIL background image."""
    from PIL import Image
    over = Image.open(png_path).convert("RGBA")
    base = background.convert("RGBA").resize(over.size)
    Image.alpha_composite(base, over).convert("RGB").save(out_path)


def render_states(out_dir: str) -> List[str]:
    from PIL import Image
    from overlay import Overlay

    _app()
    os.makedirs(out_dir, exist_ok=True)
    size = (1280, 720)
    backdrop = Image.new("RGB", size, (236, 238, 242))
    states = {
        "state_status": dict(banner=(T.WORKING + "...", "status")),
        "state_error_no_internet": dict(banner=(T.NO_INTERNET, "error")),
        "state_error_no_text": dict(banner=(T.NO_TEXT, "error")),
        "state_ready": dict(banner=(T.READY, "info")),
        "state_hint": dict(hint=T.HINT),
    }
    written = []
    overlay = Overlay()
    for name, kwargs in states.items():
        raw = os.path.join(out_dir, name + ".overlay.png")
        overlay.render_to_file(raw, size, **kwargs)
        final = os.path.join(out_dir, name + ".png")
        composite(raw, backdrop, final)
        os.remove(raw)
        written.append(final)
    return written
