"""Global low-level mouse hook (ctypes, no third-party dependency).

* Middle-button (wheel click) is SWALLOWED: browsers would otherwise start
  auto-scroll or open links in new tabs.
* Scroll / left / right clicks are passed through untouched but reported, so the
  overlay can disappear when the screen content is about to change.
* Callbacks run inside the hook, which Windows silently removes if it is slow,
  so they must only set a flag or emit a Qt signal.
* The hook is re-installed every minute as insurance against silent removal.
"""
from __future__ import annotations

import ctypes
import logging
import threading
import time
from ctypes import wintypes as wt
from types import SimpleNamespace
from typing import Callable, Optional

log = logging.getLogger("ocr2heb.hook")

WH_MOUSE_LL = 14
HC_ACTION = 0
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MOUSEWHEEL = 0x020A
WM_MOUSEHWHEEL = 0x020E
WM_TIMER = 0x0113
WM_APP_STOP = 0x8001
REINSTALL_MS = 60_000

_api: Optional[SimpleNamespace] = None


def _win() -> SimpleNamespace:
    global _api
    if _api is not None:
        return _api
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    LRESULT = ctypes.c_ssize_t
    HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wt.WPARAM, wt.LPARAM)

    user32.SetWindowsHookExW.argtypes = (ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD)
    user32.SetWindowsHookExW.restype = wt.HHOOK
    user32.UnhookWindowsHookEx.argtypes = (wt.HHOOK,)
    user32.UnhookWindowsHookEx.restype = wt.BOOL
    user32.CallNextHookEx.argtypes = (wt.HHOOK, ctypes.c_int, wt.WPARAM, wt.LPARAM)
    user32.CallNextHookEx.restype = LRESULT
    user32.GetMessageW.argtypes = (ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT)
    user32.GetMessageW.restype = ctypes.c_int
    user32.TranslateMessage.argtypes = (ctypes.POINTER(wt.MSG),)
    user32.DispatchMessageW.argtypes = (ctypes.POINTER(wt.MSG),)
    user32.DispatchMessageW.restype = LRESULT
    user32.SetTimer.argtypes = (wt.HWND, ctypes.c_size_t, wt.UINT, ctypes.c_void_p)
    user32.SetTimer.restype = ctypes.c_size_t
    user32.PostThreadMessageW.argtypes = (wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM)
    user32.PostThreadMessageW.restype = wt.BOOL
    kernel32.GetModuleHandleW.argtypes = (wt.LPCWSTR,)
    kernel32.GetModuleHandleW.restype = wt.HMODULE
    kernel32.GetCurrentThreadId.restype = wt.DWORD

    _api = SimpleNamespace(user32=user32, kernel32=kernel32, HOOKPROC=HOOKPROC)
    return _api


class MouseHook:
    def __init__(self,
                 on_middle: Callable[[], None],
                 on_dismiss: Optional[Callable[[], None]] = None,
                 debounce: float = 0.45,
                 dismiss_on_scroll: bool = True,
                 dismiss_on_click: bool = True) -> None:
        self.on_middle = on_middle
        self.on_dismiss = on_dismiss
        self.debounce = debounce
        self.dismiss_on_scroll = dismiss_on_scroll
        self.dismiss_on_click = dismiss_on_click
        self.overlay_active = False          # set by the controller; avoids needless callbacks
        self.installed = False
        self._thread: Optional[threading.Thread] = None
        self._tid = 0
        self._hhook = None
        self._callback = None
        self._ready = threading.Event()
        self._last_middle = 0.0

    # -------------------------------------------------------------- lifecycle
    def start(self, wait: float = 3.0) -> bool:
        self._thread = threading.Thread(target=self._run, name="mouse-hook", daemon=True)
        self._thread.start()
        self._ready.wait(wait)
        return self.installed

    def stop(self) -> None:
        if self._tid:
            _win().user32.PostThreadMessageW(self._tid, WM_APP_STOP, 0, 0)
        if self._thread:
            self._thread.join(2.0)

    # ------------------------------------------------------------------ hook
    def _install(self) -> bool:
        api = _win()
        self._hhook = api.user32.SetWindowsHookExW(WH_MOUSE_LL, self._callback,
                                                   api.kernel32.GetModuleHandleW(None), 0)
        self.installed = bool(self._hhook)
        if not self.installed:
            log.error("SetWindowsHookEx failed, error=%s", ctypes.get_last_error())
        return self.installed

    def _uninstall(self) -> None:
        if self._hhook:
            _win().user32.UnhookWindowsHookEx(self._hhook)
            self._hhook = None
        self.installed = False

    def _reinstall(self) -> None:
        old = self._hhook
        if self._install() and old:
            _win().user32.UnhookWindowsHookEx(old)
            log.debug("hook re-installed")

    def _safe(self, fn: Optional[Callable[[], None]]) -> None:
        if fn is None:
            return
        try:
            fn()
        except Exception:
            log.exception("hook callback failed")

    def _proc(self, n_code, w_param, l_param):
        try:
            if n_code == HC_ACTION:
                if w_param == WM_MBUTTONDOWN:
                    now = time.monotonic()
                    if now - self._last_middle >= self.debounce:
                        self._last_middle = now
                        self._safe(self.on_middle)
                    return 1                                    # swallow: app never sees it
                if w_param == WM_MBUTTONUP:
                    return 1
                if self.overlay_active:
                    if self.dismiss_on_click and w_param in (WM_LBUTTONDOWN, WM_RBUTTONDOWN):
                        self._safe(self.on_dismiss)
                    elif self.dismiss_on_scroll and w_param in (WM_MOUSEWHEEL, WM_MOUSEHWHEEL):
                        self._safe(self.on_dismiss)
        except Exception:
            log.exception("hook proc error")
        return _win().user32.CallNextHookEx(self._hhook, n_code, w_param, l_param)

    def _run(self) -> None:
        api = _win()
        self._tid = api.kernel32.GetCurrentThreadId()
        self._callback = api.HOOKPROC(self._proc)             # keep a reference: no GC
        self._install()
        self._ready.set()
        api.user32.SetTimer(None, 1, REINSTALL_MS, None)
        msg = wt.MSG()
        while True:
            ret = api.user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret <= 0:
                break
            if msg.message == WM_APP_STOP:
                break
            if msg.message == WM_TIMER:
                self._reinstall()
                continue
            api.user32.TranslateMessage(ctypes.byref(msg))
            api.user32.DispatchMessageW(ctypes.byref(msg))
        self._uninstall()
