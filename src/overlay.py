"""Full-monitor, transparent, click-through, always-on-top window (PyQt5).

It paints (a) opaque boxes with the Hebrew translation over the original text,
and (b) small status / error pills. Mouse and keyboard input pass straight
through it, and it never takes focus.
"""
from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes as wt
from typing import List, Optional, Sequence, Tuple

from PyQt5.QtCore import QRect, QRectF, Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter
from PyQt5.QtWidgets import QWidget

import config
from fit import Item

log = logging.getLogger("ocr2heb.overlay")

# Not every PyQt5 build exposes this flag by name; 0x40000 is its value in qnamespace.h.
# (The painter's RightToLeft layout direction already makes Hebrew paragraphs RTL.)
TEXT_RTL = int(getattr(Qt, "TextForceRightToLeft", 0x40000))


def make_font(px: int, bold: bool = False) -> QFont:
    font = QFont()
    if hasattr(font, "setFamilies"):
        font.setFamilies(list(config.FONT_FAMILIES))
    else:
        font.setFamily(config.FONT_FAMILIES[0])
    font.setPixelSize(max(6, int(px)))
    font.setBold(bold)
    return font


def qt_measure(text: str, px: int, max_width: Optional[int]) -> Tuple[int, int]:
    """Measure text as the overlay will draw it (matches fit.Measure)."""
    fm = QFontMetrics(make_font(px))
    if max_width is None:
        return fm.horizontalAdvance(text), fm.height()
    flags = int(Qt.TextWordWrap | Qt.AlignRight) | TEXT_RTL
    rect = fm.boundingRect(QRect(0, 0, max(1, int(max_width)), 100000), flags, text)
    return rect.width(), rect.height()


def _harden_window(hwnd: int) -> None:
    """Never activate, never intercept input, stay out of Alt-Tab, stay topmost."""
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetWindowLongPtrW.argtypes = (wt.HWND, ctypes.c_int)
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetWindowLongPtrW.argtypes = (wt.HWND, ctypes.c_int, ctypes.c_ssize_t)
        user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetWindowPos.argtypes = (wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, wt.UINT)
        GWL_EXSTYLE = -20
        WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x20, 0x80, 0x08000000
        style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        HWND_TOPMOST, SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = -1, 0x1, 0x2, 0x10
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
    except Exception:
        log.exception("could not harden overlay window")


class Overlay(QWidget):
    def __init__(self) -> None:
        flags = (Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                 | Qt.WindowTransparentForInput | Qt.NoDropShadowWindowHint)
        super().__init__(None, flags)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.NoFocus)

        self._items: List[Item] = []
        self._banner: Optional[Tuple[str, str]] = None     # (text, kind) kind: status|error|info|hint
        self._hint: Optional[str] = None
        self._status_base = ""
        self._dots = 0

        self._banner_timer = QTimer(self)
        self._banner_timer.setSingleShot(True)
        self._banner_timer.timeout.connect(self._clear_banner)

        self._hint_timer = QTimer(self)
        self._hint_timer.setSingleShot(True)
        self._hint_timer.timeout.connect(self._clear_hint)

        self._dots_timer = QTimer(self)
        self._dots_timer.setInterval(400)
        self._dots_timer.timeout.connect(self._tick_dots)

    # ------------------------------------------------------------- public API
    def _place(self, rect: Sequence[int]) -> None:
        left, top, width, height = rect
        self.setGeometry(left, top, width, height)
        if not self.isVisible():
            self.show()
        _harden_window(int(self.winId()))
        self.raise_()

    def show_status(self, rect, base_text: str) -> None:
        """Animated 'working' pill while OCR/translation runs."""
        self._items, self._hint = [], None
        self._status_base = base_text
        self._dots = 0
        self._banner = (base_text + ".", "status")
        self._banner_timer.stop()
        self._dots_timer.start()
        self._place(rect)
        self.update()

    def show_message(self, rect, text: str, seconds: float, kind: str = "info") -> None:
        self._items, self._hint = [], None
        self._dots_timer.stop()
        self._banner = (text, kind)
        self._banner_timer.start(int(seconds * 1000))
        self._place(rect)
        self.update()

    def show_items(self, rect, items: List[Item], hint: Optional[str], hint_seconds: float) -> None:
        self._dots_timer.stop()
        self._banner = None
        self._banner_timer.stop()
        self._items = items
        self._hint = hint
        if hint:
            self._hint_timer.start(int(hint_seconds * 1000))
        self._place(rect)
        self.update()

    def render_to_file(self, path: str, size, items=(), hint: Optional[str] = None,
                       banner: Optional[Tuple[str, str]] = None) -> None:
        """Paint exactly what would be on screen into a transparent PNG, without showing the window.

        Used by the Windows bench (real Qt rendering) and for design review.
        banner = (text, kind) with kind in status|error|info.
        """
        self._items = list(items)
        self._hint = hint
        self._banner = banner
        self.resize(int(size[0]), int(size[1]))
        self.grab().save(path, "PNG")

    def clear(self) -> None:
        for t in (self._banner_timer, self._hint_timer, self._dots_timer):
            t.stop()
        self._items, self._banner, self._hint = [], None, None
        self.hide()

    # ---------------------------------------------------------------- timers
    def _tick_dots(self) -> None:
        if self._banner and self._banner[1] == "status":
            self._dots = (self._dots + 1) % 3
            self._banner = (self._status_base + "." * (self._dots + 1), "status")
            self.update()

    def _clear_banner(self) -> None:
        self._banner = None
        if not self._items:
            self.hide()
        else:
            self.update()

    def _clear_hint(self) -> None:
        self._hint = None
        self.update()

    # -------------------------------------------------------------- painting
    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt naming)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        p.setLayoutDirection(Qt.RightToLeft)

        for it in self._items:
            rect = QRectF(it.x, it.y, it.w, it.h)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(*it.bg))
            p.drawRoundedRect(rect, 3, 3)
            p.setPen(QColor(*it.fg))
            p.setFont(make_font(it.px))
            inner = rect.adjusted(it.pad, it.pad, -it.pad, -it.pad)
            flags = int(Qt.TextWordWrap) | TEXT_RTL
            flags |= int(Qt.AlignHCenter if it.align == "center" else Qt.AlignRight)
            flags |= int(Qt.AlignVCenter if it.valign == "middle" else Qt.AlignTop)
            p.drawText(inner, flags, it.text)

        if self._hint:
            self._pill(p, self._hint, 24, top=True, bg=QColor(30, 30, 30, 215))
        if self._banner:
            text, kind = self._banner
            if kind == "error":
                self._pill(p, text, 36, top=False, bg=QColor(150, 30, 30, 240))
            elif kind == "status":
                self._pill(p, text, 34, top=False, bg=QColor(30, 30, 30, 235))
            else:
                self._pill(p, text, 32, top=False, bg=QColor(25, 80, 150, 240))
        p.end()

    def _pill(self, p: QPainter, text: str, px: int, top: bool, bg: QColor) -> None:
        font = make_font(px, bold=True)
        fm = QFontMetrics(font)
        max_w = int(self.width() * 0.8)
        text_rect = fm.boundingRect(QRect(0, 0, max_w, 10000),
                                    int(Qt.TextWordWrap | Qt.AlignHCenter) | TEXT_RTL, text)
        pad = max(14, px // 2)
        w, h = text_rect.width() + 2 * pad + 8, text_rect.height() + 2 * pad
        x = (self.width() - w) / 2
        y = max(10, self.height() * 0.04) if top else (self.height() - h) / 2
        box = QRectF(x, y, w, h)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(box, 14, 14)
        p.setPen(QColor(255, 255, 255))
        p.setFont(font)
        p.drawText(box.adjusted(pad, pad, -pad, -pad),
                   int(Qt.TextWordWrap | Qt.AlignCenter) | TEXT_RTL, text)
