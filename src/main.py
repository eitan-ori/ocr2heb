"""OCR2Heb entry point.

    OCR2Heb.exe              run (tray icon, wheel-click translates the screen)
    OCR2Heb.exe --selftest   check OCR / translation / hook on this machine
    OCR2Heb.exe --demo       translate the current screen once, save before/after pictures
    OCR2Heb.exe --uninstall  remove the start-at-logon task and stop running copies
    OCR2Heb.exe --no-autostart   run without (re)creating the start-at-logon task
    OCR2Heb.exe --debug      verbose log + keep the last capture in the log folder
"""
from __future__ import annotations

import argparse
import ctypes
import os
import subprocess
import sys

# Qt must see these BEFORE it is imported: we want 1 Qt pixel == 1 physical pixel,
# because the screenshot, the OCR boxes and the overlay are all in physical pixels.
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "0")
os.environ.setdefault("QT_SCALE_FACTOR", "1")
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

_SRC = os.path.dirname(os.path.abspath(__file__))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import appdata  # noqa: E402
import config  # noqa: E402
from config import T  # noqa: E402


def _dpi_aware() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)      # per-monitor
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _message_box(text: str) -> None:
    # MB_ICONINFORMATION | MB_SETFOREGROUND | MB_TOPMOST | MB_RIGHT | MB_RTLREADING
    ctypes.windll.user32.MessageBoxW(0, text, config.APP_NAME, 0x40 | 0x10000 | 0x40000 | 0x80000 | 0x100000)


def _single_instance():
    """Return a handle that must stay alive for the process lifetime, or None if already running."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
    kernel32.CreateMutexW.restype = ctypes.c_void_p      # 64-bit handle, not truncated
    handle = kernel32.CreateMutexW(None, False, config.MUTEX_NAME)
    if ctypes.get_last_error() == 183:                   # ERROR_ALREADY_EXISTS
        return None
    return handle or True


def _uninstall() -> int:
    import autostart
    removed = autostart.remove_autostart()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.run(["taskkill", "/F", "/IM", f"{config.APP_NAME}.exe", "/FI", f"PID ne {os.getpid()}"],
                   capture_output=True, creationflags=flags)
    print("autostart task removed" if removed else "autostart task was not present / could not be removed")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="OCR2Heb - translate the screen to Hebrew with the mouse wheel")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--no-autostart", action="store_true")
    parser.add_argument("--debug", action="store_true")
    args, _unknown = parser.parse_known_args(argv)

    if sys.platform != "win32":
        print("OCR2Heb only runs on Windows.")
        return 2

    _dpi_aware()
    log = appdata.setup_logging(debug=args.debug or args.selftest or args.demo)

    if args.uninstall:
        return _uninstall()
    if args.selftest:
        import selftest
        return selftest.run()

    mutex = None
    if not args.demo:
        mutex = _single_instance()
        if mutex is None:
            _message_box(T.ALREADY_RUNNING)
            return 0

    try:
        if not ctypes.windll.shell32.IsUserAnAdmin():
            log.warning("not running as Administrator: wheel-click will not work over elevated windows")
    except Exception:
        pass

    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication
    QApplication.setAttribute(Qt.AA_DisableHighDpiScaling, True)
    qt_app = QApplication(sys.argv[:1])
    qt_app.setQuitOnLastWindowClosed(False)

    from app import Controller
    controller = Controller(qt_app, debug=args.debug, autostart_enabled=not args.no_autostart and not args.demo)
    controller.start()
    if args.demo:
        controller.run_demo()
    log.info("%s %s started (pid %d)", config.APP_NAME, config.APP_VERSION, os.getpid())
    code = qt_app.exec_()
    del mutex
    return code


if __name__ == "__main__":
    sys.exit(main())
