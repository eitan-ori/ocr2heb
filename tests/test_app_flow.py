"""Controller flow test with a stand-in for Qt and the Windows OCR engine.

Verifies the state machine, stale-result protection, error mapping and the
integration of layout + translation + fitting without needing Windows or a GUI.
If real PyQt5 is installed it is replaced by stubs for this test anyway.

Run:  python tests/test_app_flow.py
"""
import os
import sys
import threading
import time
import types

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "src"))
sys.path.insert(0, HERE)


# ----------------------------------------------------------- Qt stand-in
class _Meta(type):
    def __getattr__(cls, name):
        return _D()


class _D:
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, name):
        return _D()

    def __call__(self, *a, **k):
        return _D()

    def __or__(self, other):
        return self

    __ror__ = __or__

    def __int__(self):
        return 0


def _fake_qt_module(name):
    mod = types.ModuleType(name)

    def getter(attr):
        if attr.startswith("Q"):
            return _Meta(attr, (_D,), {})
        return lambda *a, **k: _D()

    mod.__getattr__ = getter
    return mod


for _name in ("PyQt5", "PyQt5.QtCore", "PyQt5.QtGui", "PyQt5.QtWidgets"):
    sys.modules[_name] = _fake_qt_module(_name)

import app as app_mod  # noqa: E402
import layout  # noqa: E402
import translate  # noqa: E402
from test_pipeline import FAKE_HEBREW, fake_screen, pil_measure  # noqa: E402


# ----------------------------------------------------------------- fakes
class FakeOcr:
    def __init__(self, lines):
        self.lines = lines
        self.delay = 0.0

    def recognize(self, img):
        time.sleep(self.delay)
        return self.lines


class FakeTranslator:
    def __init__(self, mapping=None, error=None):
        self.mapping = mapping or {}
        self.error = error

    def translate(self, texts):
        if self.error:
            raise self.error
        return [self.mapping.get(t, "תרגום " + t) for t in texts]


class Recorder:
    def __init__(self):
        self.calls = []
        self.event = threading.Event()

    def emit(self, *args):
        self.calls.append(args)
        self.event.set()


def make_controller(ocr, translator, img, rect=(0, 0, 1280, 720)):
    app = types.SimpleNamespace(processEvents=lambda: None, quit=lambda: None, primaryScreen=lambda: None)
    ctl = app_mod.Controller(app)
    ctl.ocr = ocr
    ctl.translator = translator
    ctl.job_done = Recorder()
    ctl.job_failed = Recorder()
    app_mod.capture.grab_screen_under_cursor = lambda: (img, rect)
    app_mod.capture.monitor_rect_under_cursor = lambda: rect
    app_mod.qt_measure = pil_measure
    shown = []
    ctl.overlay.show_items = lambda *a, **k: shown.append(("items", a))
    ctl.overlay.show_status = lambda *a, **k: shown.append(("status", a))
    ctl.overlay.show_message = lambda *a, **k: shown.append(("message", a))
    ctl.overlay.clear = lambda: shown.append(("clear", ()))
    ctl.shown = shown
    return ctl


def wait(rec, timeout=5):
    assert rec.event.wait(timeout), "job did not finish"


# ------------------------------------------------------------------ tests
def test_full_cycle():
    img, lines = fake_screen()
    ctl = make_controller(FakeOcr(lines), FakeTranslator(FAKE_HEBREW), img)
    assert ctl.state == app_mod.IDLE

    ctl.on_middle()                                    # click 1: starts a job
    assert ctl.state == app_mod.WORKING
    assert ctl.shown[-1][0] == "status"
    wait(ctl.job_done)
    gen, payload = ctl.job_done.calls[0]
    blocks, texts, bgs, size = payload
    assert size == img.size and len(blocks) == len(texts) == len(bgs) >= 8

    ctl._on_done(gen, payload)                         # delivered on the GUI thread
    assert ctl.state == app_mod.SHOWING
    kind, args = ctl.shown[-1]
    assert kind == "items" and len(args[1]) == len(blocks)
    assert ctl.hook.overlay_active is True

    ctl.on_middle()                                    # click 2: closes
    assert ctl.state == app_mod.IDLE
    assert ctl.shown[-1][0] == "clear"
    assert ctl.hook.overlay_active is False


def test_click_while_working_cancels_and_late_result_is_dropped():
    img, lines = fake_screen()
    ocr = FakeOcr(lines)
    ocr.delay = 0.4
    ctl = make_controller(ocr, FakeTranslator(FAKE_HEBREW), img)
    ctl.on_middle()
    assert ctl.state == app_mod.WORKING
    ctl.on_middle()                                    # impatient second click
    assert ctl.state == app_mod.IDLE
    time.sleep(0.8)                                    # the first job finishes late...
    assert not ctl.job_done.calls, "cancelled job must not report a result"


def test_stale_generation_ignored_by_slots():
    img, lines = fake_screen()
    ctl = make_controller(FakeOcr(lines), FakeTranslator(FAKE_HEBREW), img)
    ctl.on_middle()
    wait(ctl.job_done)
    gen, payload = ctl.job_done.calls[0]
    ctl._cancel()
    ctl._on_done(gen, payload)
    assert ctl.state == app_mod.IDLE
    assert not any(k == "items" for k, _ in ctl.shown)


def test_error_mapping():
    img, lines = fake_screen()
    cases = [
        (FakeOcr([]), FakeTranslator(), "no_text"),
        (FakeOcr(lines), FakeTranslator(error=translate.NoInternet("x")), "internet"),
        (FakeOcr(lines), FakeTranslator(error=translate.TranslateError("x")), "translate"),
        (FakeOcr(lines), FakeTranslator(error=RuntimeError("boom")), "generic"),
    ]
    for ocr, tr, expected in cases:
        ctl = make_controller(ocr, tr, img)
        ctl.on_middle()
        wait(ctl.job_failed)
        gen, kind = ctl.job_failed.calls[0]
        assert kind == expected, (kind, expected)
        ctl._on_failed(gen, kind)
        assert ctl.state == app_mod.IDLE
        assert ctl.shown[-1][0] == "message"           # a friendly Hebrew message, never a crash


def test_all_translations_failed_vs_nothing_to_translate():
    img, lines = fake_screen()
    # service returns None for everything -> "translate"
    class AllNone:
        def translate(self, texts):
            return [None] * len(texts)
    ctl = make_controller(FakeOcr(lines), AllNone(), img)
    ctl.on_middle(); wait(ctl.job_failed)
    assert ctl.job_failed.calls[0][1] == "translate"

    # translation equals the source (brand names) -> "no_text"
    class Echo:
        def translate(self, texts):
            return list(texts)
    ctl = make_controller(FakeOcr(lines), Echo(), img)
    ctl.on_middle(); wait(ctl.job_failed)
    assert ctl.job_failed.calls[0][1] == "no_text"


def test_timeout_shows_message():
    img, lines = fake_screen()
    ctl = make_controller(FakeOcr(lines), FakeTranslator(), img)
    ctl.on_middle()
    ctl._on_timeout()
    assert ctl.state == app_mod.IDLE and ctl.shown[-1][0] == "message"


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except Exception as exc:  # noqa: BLE001
                failures += 1
                import traceback
                traceback.print_exc()
                print("FAIL", name, exc)
    sys.exit(1 if failures else 0)
