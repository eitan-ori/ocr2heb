"""--selftest: exercises every Windows-specific part and prints a PASS/FAIL report.

Run it on the machine where the app will live (build.bat does this for you).
The report is also written to %LOCALAPPDATA%\\OCR2Heb\\logs\\selftest.txt so it
can be read even when the exe has no console.
"""
from __future__ import annotations

import os
import sys
import time
import traceback

import appdata
import config

REPORT: list = []
FAILED: list = []


def say(line: str = "") -> None:
    REPORT.append(line)
    try:
        print(line)
    except Exception:
        pass


def step(name: str, fn) -> bool:
    say(f"--- {name}")
    try:
        detail = fn()
        say(f"PASS  {name}" + (f": {detail}" if detail else ""))
        return True
    except Exception as exc:  # noqa: BLE001
        FAILED.append(name)
        say(f"FAIL  {name}: {exc.__class__.__name__}: {exc}")
        say(traceback.format_exc())
        return False


def _fonts():
    from PIL import ImageFont
    for p in ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"):
        if os.path.exists(p):
            return ImageFont.truetype(p, 34), ImageFont.truetype(p, 22)
    return ImageFont.load_default(), ImageFont.load_default()


def run() -> int:
    say(f"OCR2Heb {config.APP_VERSION} self-test  ({time.strftime('%Y-%m-%d %H:%M:%S')})")
    say(f"python {sys.version.split()[0]}  frozen={getattr(sys, 'frozen', False)}  platform={sys.platform}")
    ctx: dict = {}

    def imports():
        import mss  # noqa: F401
        import requests  # noqa: F401
        from PIL import Image  # noqa: F401
        from PyQt5 import QtCore
        return f"Qt {QtCore.QT_VERSION_STR}"

    def admin():
        import ctypes
        ok = bool(ctypes.windll.shell32.IsUserAnAdmin())
        if not ok:
            say("      (not elevated - fine for this test, but the real app needs Administrator)")
        return "elevated" if ok else "NOT elevated"

    def ocr_engine():
        from ocr import OcrService
        svc = OcrService()
        ctx["ocr"] = svc
        lang = svc.prepare()
        return f"language {lang}; installed: {svc.available_languages}"

    def ocr_text():
        from PIL import Image, ImageDraw
        big, small = _fonts()
        img = Image.new("RGB", (900, 360), (255, 255, 255))
        d = ImageDraw.Draw(img)
        d.text((40, 30), "Hello world, this is a test", font=big, fill=(0, 0, 0))
        d.text((40, 110), "Please save your file before you close the window.", font=small, fill=(0, 0, 0))
        d.text((40, 150), "Click the button to continue.", font=small, fill=(0, 0, 0))
        lines = ctx["ocr"].recognize(img)
        text = " | ".join(" ".join(w.text for w in line) for line in lines)
        say(f"      OCR read: {text}")
        low = text.lower()
        if "hello" not in low or "test" not in low:
            raise AssertionError("OCR did not read the test sentence")
        ctx["lines"] = lines
        return f"{len(lines)} lines"

    def layout_step():
        import layout
        blocks = layout.build_blocks(ctx["lines"])
        ctx["blocks"] = blocks
        if not blocks:
            raise AssertionError("no blocks")
        return f"{len(blocks)} blocks: " + " | ".join(b.text for b in blocks)

    def translation():
        from translate import Translator
        out = Translator().translate([b.text for b in ctx["blocks"]])
        say("      Hebrew: " + " | ".join(o or "None" for o in out))
        if not any(o and any("\u0590" <= c <= "\u05ff" for c in o) for o in out):
            raise AssertionError("no Hebrew in translation")
        return f"{sum(1 for o in out if o)} translated"

    def hook():
        from mousehook import MouseHook
        h = MouseHook(on_middle=lambda: None)
        ok = h.start()
        time.sleep(0.3)
        h.stop()
        if not ok:
            raise AssertionError("SetWindowsHookEx failed")
        return "installed and removed"

    def capture_step():
        import capture
        img, rect = capture.grab_screen_under_cursor()
        return f"{img.width}x{img.height} at {rect[:2]}"

    def qt_step():
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication
        QApplication.setAttribute(Qt.AA_DisableHighDpiScaling, True)
        app = QApplication.instance() or QApplication(sys.argv[:1])
        from overlay import qt_measure
        w, h = qt_measure("שלום עולם, זו בדיקה", 24, None)
        w2, h2 = qt_measure("שלום עולם, זו בדיקה של גלישת שורות ארוכה מאוד", 24, 200)
        if w <= 0 or h2 <= h:
            raise AssertionError(f"measure looks wrong: {(w, h, w2, h2)}")
        del app
        return f"measure ok ({w}x{h}; wrapped height {h2})"

    ok = True
    ok &= step("imports", imports)
    step("administrator", admin)
    if ok:
        ok &= step("windows OCR engine", ocr_engine)
        if "ocr" in ctx:
            step("OCR reads a test image", ocr_text)
        if "lines" in ctx:
            step("layout grouping", layout_step)
        if "blocks" in ctx:
            step("Hebrew translation (needs internet)", translation)
        step("mouse hook install/uninstall", hook)
        step("screen capture", capture_step)
        step("Qt text measuring", qt_step)

    say("")
    say("SELFTEST " + ("PASSED" if not FAILED else "FAILED: " + ", ".join(FAILED)))
    try:
        with open(os.path.join(appdata.log_dir(), "selftest.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(REPORT))
    except Exception:
        pass
    return 0 if not FAILED else 1
