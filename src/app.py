"""Controller: ties the mouse hook, capture, OCR, translation and overlay together.

State machine
    IDLE     --wheel click-->  WORKING   (screen captured, "translating" pill shown)
    WORKING  --result------->  SHOWING   (Hebrew boxes drawn over the English)
    WORKING  --wheel click-->  IDLE      (cancel)
    SHOWING  --wheel click-->  IDLE      (overlay removed)
Every job carries a generation number, so a late result of a cancelled job is dropped.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time

from PyQt5.QtCore import QObject, QTimer, QUrl, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter, QPixmap
from PyQt5.QtWidgets import QAction, QApplication, QMenu, QSystemTrayIcon

import appdata
import autostart
import capture
import config
import pipeline
from config import T
from mousehook import MouseHook
from ocr import OcrService, OcrUnavailable, install_ocr_language
from overlay import Overlay, qt_measure
from translate import NoInternet, TranslateError, Translator

log = logging.getLogger("ocr2heb.app")

IDLE, WORKING, SHOWING = 0, 1, 2


def make_tray_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setBrush(QColor(25, 90, 170))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(2, 2, 60, 60, 14, 14)
    p.setPen(QColor(255, 255, 255))
    font = QFont("Segoe UI")
    font.setPixelSize(44)
    font.setBold(True)
    p.setFont(font)
    p.drawText(pm.rect(), Qt.AlignCenter, "א")
    p.end()
    return QIcon(pm)


class Controller(QObject):
    middle_clicked = pyqtSignal()
    dismiss_requested = pyqtSignal()
    job_done = pyqtSignal(int, object)
    job_failed = pyqtSignal(int, str)
    banner_requested = pyqtSignal(str, float, str)

    def __init__(self, app: QApplication, debug: bool = False, autostart_enabled: bool = True) -> None:
        super().__init__()
        self.app = app
        self.debug = debug
        self.autostart_enabled = autostart_enabled
        self.state = IDLE
        self.gen = 0
        self.rect = (0, 0, 0, 0)

        self.overlay = Overlay()
        self.ocr = OcrService()
        self.translator = Translator()

        self.hook = MouseHook(
            on_middle=self.middle_clicked.emit,
            on_dismiss=self.dismiss_requested.emit,
            debounce=config.MIDDLE_CLICK_DEBOUNCE_SEC,
            dismiss_on_scroll=config.DISMISS_ON_SCROLL,
            dismiss_on_click=config.DISMISS_ON_LEFT_RIGHT_CLICK,
        )

        self.middle_clicked.connect(self.on_middle)
        self.dismiss_requested.connect(self.on_dismiss)
        self.job_done.connect(self._on_done)
        self.job_failed.connect(self._on_failed)
        self.banner_requested.connect(self._on_banner)

        self.timeout_timer = QTimer(self)
        self.timeout_timer.setSingleShot(True)
        self.timeout_timer.timeout.connect(self._on_timeout)

        self._build_tray()

    # ----------------------------------------------------------------- tray
    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(make_tray_icon(), self)
        self.tray.setToolTip(T.TRAY_TOOLTIP)
        menu = QMenu()
        status = QAction(T.TRAY_STATUS, menu)
        status.setEnabled(False)
        menu.addAction(status)
        menu.addSeparator()
        logs = QAction(T.TRAY_LOGS, menu)
        logs.triggered.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(appdata.log_dir())))
        menu.addAction(logs)
        quit_action = QAction(T.TRAY_EXIT, menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)
        menu.setLayoutDirection(Qt.RightToLeft)
        self.tray.setContextMenu(menu)
        self._menu = menu
        self.tray.show()

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if not self.hook.start():
            log.error("mouse hook could not be installed")
        self.ocr.start()
        threading.Thread(target=self._warmup, name="warmup", daemon=True).start()
        if self.autostart_enabled and getattr(sys, "frozen", False):
            threading.Thread(target=autostart.ensure_autostart, args=(sys.executable,),
                             name="autostart", daemon=True).start()

    def quit(self) -> None:
        log.info("quitting")
        self.hook.stop()
        self.overlay.clear()
        self.tray.hide()
        self.app.quit()

    def _warmup(self) -> None:
        """Create the OCR engine early; install the English pack if it is missing."""
        try:
            lang = self.ocr.prepare()
            log.info("ready (OCR language %s)", lang)
            self.banner_requested.emit(T.READY, config.READY_BANNER_SEC, "info")
        except OcrUnavailable as exc:
            log.warning("OCR unavailable: %s", exc)
            self.banner_requested.emit(T.OCR_INSTALLING, 20.0, "info")
            if install_ocr_language():
                self.ocr.reset()
                try:
                    self.ocr.prepare()
                    self.banner_requested.emit(T.READY, config.READY_BANNER_SEC, "info")
                    return
                except Exception:
                    log.exception("OCR still unavailable after install")
            self.banner_requested.emit(T.OCR_BROKEN, 15.0, "error")
        except Exception:
            log.exception("warm-up failed")
            self.banner_requested.emit(T.GENERIC, config.ERROR_BANNER_SEC, "error")

    # ---------------------------------------------------------------- events
    def _set_state(self, state: int) -> None:
        self.state = state
        self.hook.overlay_active = state != IDLE

    def on_middle(self) -> None:
        if self.state == IDLE:
            self._start_job()
        else:
            log.info("wheel click while %s -> cancel/close", "working" if self.state == WORKING else "showing")
            self._cancel()

    def on_dismiss(self) -> None:
        if self.state != IDLE:
            self._cancel()

    def _cancel(self) -> None:
        self.gen += 1
        self.timeout_timer.stop()
        self.overlay.clear()
        self._set_state(IDLE)

    def _on_banner(self, text: str, seconds: float, kind: str) -> None:
        if self.state != IDLE:
            return
        try:
            self.overlay.show_message(capture.monitor_rect_under_cursor(), text, seconds, kind)
        except Exception:
            log.exception("could not show banner")

    # ------------------------------------------------------------------- job
    def _start_job(self) -> None:
        if self.overlay.isVisible():                # an old banner must not end up in the screenshot
            self.overlay.clear()
            self.app.processEvents()
            time.sleep(0.08)
        try:
            img, rect = capture.grab_screen_under_cursor()
        except Exception:
            log.exception("screen capture failed")
            self._show_error(T.GENERIC)
            return
        self.gen += 1
        gen = self.gen
        self.rect = rect
        self._set_state(WORKING)
        self.overlay.show_status(rect, T.WORKING)
        self.timeout_timer.start(int(config.JOB_TIMEOUT_SEC * 1000))
        threading.Thread(target=self._work, args=(gen, img), name=f"job-{gen}", daemon=True).start()

    def _work(self, gen: int, img) -> None:
        t0 = time.monotonic()
        try:
            if self.debug:
                img.save(os.path.join(appdata.log_dir(), "last_capture.png"))
            ocr_lines = self.ocr.recognize(img)
            blocks, skipped = pipeline.analyze_blocks(ocr_lines)
            if gen != self.gen:
                return
            if not blocks:
                log.info("job %d: nothing to translate; skipped=%s", gen, pipeline.summarize_skipped(skipped))
                self.job_failed.emit(gen, "no_text")
                return
            kept, texts, skipped2, results = pipeline.translate_blocks(blocks, self.translator)
            if gen != self.gen:
                return
            if not kept:
                # nothing came back at all -> service problem; otherwise the text was already
                # identical in Hebrew (names, brands) -> "nothing to translate"
                self.job_failed.emit(gen, "translate" if not any(results) else "no_text")
                return
            bgs = pipeline.sample_backgrounds(img, kept)
            log.info("job %d: %d blocks translated in %.2fs; skipped=%s", gen, len(kept),
                     time.monotonic() - t0, pipeline.summarize_skipped(skipped + skipped2))
            self.job_done.emit(gen, (kept, texts, bgs, img.size))
        except OcrUnavailable:
            log.exception("OCR unavailable")
            self.job_failed.emit(gen, "ocr")
        except NoInternet:
            self.job_failed.emit(gen, "internet")
        except TranslateError:
            self.job_failed.emit(gen, "translate")
        except Exception:
            log.exception("job failed")
            self.job_failed.emit(gen, "generic")

    def _on_done(self, gen: int, payload) -> None:
        if gen != self.gen or self.state != WORKING:
            return
        self.timeout_timer.stop()
        blocks, texts, bgs, (w, h) = payload
        try:
            items = pipeline.plan(blocks, texts, bgs, (w, h), qt_measure)
            if (w, h) != (self.rect[2], self.rect[3]):
                log.warning("capture size %sx%s differs from monitor rect %s", w, h, self.rect)
            self.overlay.show_items(self.rect, items, T.HINT, config.HINT_BANNER_SEC)
            self._set_state(SHOWING)
        except Exception:
            log.exception("could not draw overlay")
            self._show_error(T.GENERIC)

    def _on_failed(self, gen: int, kind: str) -> None:
        if gen != self.gen or self.state != WORKING:
            return
        self.timeout_timer.stop()
        message = {
            "no_text": T.NO_TEXT,
            "internet": T.NO_INTERNET,
            "translate": T.TRANSLATE_FAIL,
            "ocr": T.OCR_BROKEN,
        }.get(kind, T.GENERIC)
        log.info("job %d failed: %s", gen, kind)
        self._show_error(message)

    def _on_timeout(self) -> None:
        if self.state == WORKING:
            log.warning("job %d timed out", self.gen)
            self.gen += 1
            self._show_error(T.TIMEOUT)

    def _show_error(self, text: str) -> None:
        self._set_state(IDLE)
        try:
            rect = self.rect if self.rect[2] else capture.monitor_rect_under_cursor()
            self.overlay.show_message(rect, text, config.ERROR_BANNER_SEC, "error")
        except Exception:
            log.exception("could not show error")

    # ------------------------------------------------------------------ demo
    def run_demo(self) -> None:
        """--demo: translate the screen once, keep the overlay up, save before/after pictures.

        Starts after 5 s (time to switch to an English page). A real wheel click is ignored
        during the demo so it cannot toggle the overlay off; "after" is taken only once the
        overlay (or an error message) is actually on screen.
        """
        out = appdata.log_dir()
        log.info("demo: capturing in 5s; pictures go to %s", out)
        try:
            self.middle_clicked.disconnect(self.on_middle)
        except TypeError:
            pass
        started = {"t": 0.0}
        poll_timer = QTimer(self)
        self._demo_timer = poll_timer

        def shot(name):
            try:
                self.app.primaryScreen().grabWindow(0).save(os.path.join(out, name))
            except Exception:
                log.exception("demo screenshot failed")

        def finish():
            shot("demo_after.png")
            QTimer.singleShot(1500, self.quit)

        def poll():
            timed_out = time.monotonic() - started["t"] > config.JOB_TIMEOUT_SEC + 5
            if self.state != WORKING or timed_out:
                poll_timer.stop()
                QTimer.singleShot(1500, finish)

        def begin():
            shot("demo_before.png")
            if self.state == IDLE:
                self._start_job()
            started["t"] = time.monotonic()
            poll_timer.timeout.connect(poll)
            poll_timer.start(250)

        QTimer.singleShot(5000, begin)
