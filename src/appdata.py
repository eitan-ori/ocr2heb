"""Per-user data folders and logging setup.

Everything the app writes lives under %LOCALAPPDATA%\\OCR2Heb so it never
depends on where the .exe was copied to, and so logs can be read remotely
(AnyDesk) when something goes wrong.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler


def data_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    path = os.path.join(base, "OCR2Heb")
    os.makedirs(path, exist_ok=True)
    return path


def log_dir() -> str:
    path = os.path.join(data_dir(), "logs")
    os.makedirs(path, exist_ok=True)
    return path


def tmp_dir() -> str:
    path = os.path.join(data_dir(), "tmp")
    os.makedirs(path, exist_ok=True)
    return path


def setup_logging(debug: bool = False) -> logging.Logger:
    """Configure the 'ocr2heb' logger. Safe to call more than once."""
    # A windowed (no-console) PyInstaller exe has sys.stdout/stderr == None;
    # any stray print() would raise. Point them at the null device.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

    logger = logging.getLogger("ocr2heb")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s")

    try:
        fh = RotatingFileHandler(os.path.join(log_dir(), "ocr2heb.log"),
                                 maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:  # never let logging problems stop the app
        pass

    try:
        if sys.stderr.isatty():
            sh = logging.StreamHandler()
            sh.setFormatter(fmt)
            logger.addHandler(sh)
    except Exception:
        pass

    def _excepthook(exc_type, exc, tb):
        logger.critical("Unhandled exception", exc_info=(exc_type, exc, tb))

    def _thread_hook(args):
        logger.critical("Unhandled exception in thread %s", args.thread,
                        exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = _excepthook
    threading.excepthook = _thread_hook
    return logger
