"""OCR through Windows' built-in engine (Windows.Media.Ocr).

Free, offline, no API key. All WinRT objects live on ONE dedicated thread that
owns an asyncio loop and a COM multithreaded apartment; other threads submit
work to it. That avoids the classic "works in the console, fails in a GUI app"
COM-apartment problems.

The engine needs the *English* OCR language pack. It is normally present, but
on a Hebrew-only Windows it may not be, so install_ocr_language() can add it
(needs admin + internet; the app runs as admin).
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import threading
import uuid
from types import SimpleNamespace
from typing import List

import config
import appdata
from layout import Word

log = logging.getLogger("ocr2heb.ocr")


class OcrUnavailable(Exception):
    """No usable English OCR engine on this machine."""


class OcrError(Exception):
    """OCR failed for another reason."""


def _co_init_mta() -> None:
    try:
        hr = ctypes_windll().ole32.CoInitializeEx(None, 0)   # COINIT_MULTITHREADED
        log.debug("CoInitializeEx(MTA) -> 0x%08x", hr & 0xFFFFFFFF)
    except Exception:  # pragma: no cover - non-Windows
        pass


def ctypes_windll():
    import ctypes
    return ctypes.windll


def _load_api() -> SimpleNamespace:
    """Import the WinRT projection. Written with static imports so PyInstaller sees them."""
    try:
        from winrt.windows.foundation import collections as _c1  # noqa: F401  (registers types)
        from winrt.windows.storage import streams as _c2  # noqa: F401
        from winrt.windows.globalization import Language
        from winrt.windows.graphics.imaging import BitmapDecoder
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.storage import FileAccessMode, StorageFile
        root = "winrt"
    except ImportError as first:
        log.info("winrt not available (%s); trying winsdk", first)
        try:
            from winsdk.windows.foundation import collections as _c1  # noqa: F401,F811
            from winsdk.windows.storage import streams as _c2  # noqa: F401,F811
            from winsdk.windows.globalization import Language  # noqa: F811
            from winsdk.windows.graphics.imaging import BitmapDecoder  # noqa: F811
            from winsdk.windows.media.ocr import OcrEngine  # noqa: F811
            from winsdk.windows.storage import FileAccessMode, StorageFile  # noqa: F811
            root = "winsdk"
        except ImportError as second:
            raise OcrUnavailable(f"Windows OCR Python bindings missing: {first} / {second}") from second
    return SimpleNamespace(root=root, Language=Language, BitmapDecoder=BitmapDecoder,
                           OcrEngine=OcrEngine, FileAccessMode=FileAccessMode, StorageFile=StorageFile)


def _english_candidates(available: List[str]) -> List[str]:
    lower = {t.lower(): t for t in available}
    ordered = [lower[t.lower()] for t in config.OCR_LANG_PREFERENCE if t.lower() in lower]
    ordered += [t for t in available if t.lower().startswith("en") and t not in ordered]
    return ordered


class OcrService:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._init_error: Exception | None = None
        self._api: SimpleNamespace | None = None
        self._engine = None
        self.language: str | None = None
        self.available_languages: List[str] = []
        self._max_dim = 10000
        self._start_lock = threading.Lock()

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        with self._start_lock:
            if self._thread is not None:
                return
            self._thread = threading.Thread(target=self._run_loop, name="ocr-loop", daemon=True)
            self._thread.start()

    def _run_loop(self) -> None:
        _co_init_mta()
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._api = _load_api()
            log.info("WinRT bindings loaded (%s)", self._api.root)
        except Exception as exc:
            log.exception("could not load WinRT bindings")
            self._init_error = exc
        self._ready.set()
        self._loop.run_forever()

    def _run(self, coro, timeout: float):
        self.start()
        if not self._ready.wait(30):
            raise OcrError("OCR thread did not start")
        if self._init_error is not None:
            raise OcrUnavailable(str(self._init_error))
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return fut.result(timeout)
        except TimeoutError as exc:  # concurrent.futures.TimeoutError is TimeoutError on 3.11+
            fut.cancel()
            raise OcrError("OCR timed out") from exc
        except Exception as exc:
            if exc.__class__.__name__ == "TimeoutError":
                fut.cancel()
                raise OcrError("OCR timed out") from exc
            raise

    # ----------------------------------------------------------------- engine
    async def _ensure_engine(self):
        if self._engine is not None:
            return self.language
        api = self._api
        try:
            self.available_languages = [lang.language_tag for lang in api.OcrEngine.available_recognizer_languages]
        except Exception:
            log.exception("could not list OCR languages")
            self.available_languages = []
        log.info("installed OCR languages: %s", self.available_languages)

        candidates = _english_candidates(self.available_languages) or list(config.OCR_LANG_PREFERENCE)
        for tag in candidates:
            try:
                lang = api.Language(tag)
                if api.OcrEngine.is_language_supported(lang):
                    engine = api.OcrEngine.try_create_from_language(lang)
                    if engine is not None:
                        self._engine, self.language = engine, tag
                        break
            except Exception:
                log.exception("engine for %s failed", tag)
        if self._engine is None:
            raise OcrUnavailable(f"no English OCR engine (installed: {self.available_languages})")
        try:
            self._max_dim = int(api.OcrEngine.max_image_dimension)
        except Exception:
            self._max_dim = 10000
        log.info("OCR engine ready: %s (max dimension %d)", self.language, self._max_dim)
        return self.language

    def prepare(self, timeout: float = 60.0) -> str:
        """Create the engine now (raises OcrUnavailable if English OCR is missing)."""
        return self._run(self._ensure_engine(), timeout)

    def reset(self) -> None:
        """Forget the cached engine (used after installing a language pack)."""
        self._engine = None
        self.language = None

    # -------------------------------------------------------------- recognise
    async def _recognize_file(self, path: str):
        api = self._api
        file = await api.StorageFile.get_file_from_path_async(path)
        stream = await file.open_async(api.FileAccessMode.READ)
        try:
            decoder = await api.BitmapDecoder.create_async(stream)
            bitmap = await decoder.get_software_bitmap_async()
            result = await self._engine.recognize_async(bitmap)
            lines = []
            for line in result.lines:
                words = []
                for w in line.words:
                    r = w.bounding_rect
                    words.append((w.text, float(r.x), float(r.y), float(r.width), float(r.height)))
                lines.append(words)
            return lines
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def _ocr_image(self, img, scale: float) -> List[List[Word]]:
        from PIL import Image

        src = img if scale == 1.0 else img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
        path = os.path.join(appdata.tmp_dir(), f"cap_{uuid.uuid4().hex[:8]}.bmp")
        try:
            src.convert("RGB").save(path, "BMP")
            raw = self._run(self._recognize_file(path), 60)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        return [[Word(t, x / scale, y / scale, w / scale, h / scale) for (t, x, y, w, h) in line] for line in raw]

    def recognize(self, img) -> List[List[Word]]:
        """PIL image -> list of OCR lines (each a list of Word in the image's pixel coordinates)."""
        from PIL import ImageOps

        self.prepare()
        scale = 1.0
        if img.width <= config.OCR_UPSCALE_MAX_WIDTH and max(img.size) * config.OCR_UPSCALE <= self._max_dim:
            scale = config.OCR_UPSCALE
        lines = self._ocr_image(img, scale)
        words = sum(len(line) for line in lines)
        if words < 3:                       # maybe light text on a dark theme: try inverted
            log.info("few words (%d); retrying inverted", words)
            inverted = ImageOps.invert(img.convert("RGB"))
            lines2 = self._ocr_image(inverted, scale)
            if sum(len(line) for line in lines2) > words:
                lines = lines2
        log.info("OCR found %d lines / %d words", len(lines), sum(len(line) for line in lines))
        return lines


def install_ocr_language(timeout: int = 1500) -> bool:
    """Install the English OCR Windows capability (admin + internet required)."""
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
           f"Add-WindowsCapability -Online -Name '{config.OCR_CAPABILITY}'"]
    log.info("installing OCR language pack: %s", config.OCR_CAPABILITY)
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = (proc.stdout or b"").decode("utf-8", "replace") + (proc.stderr or b"").decode("utf-8", "replace")
        log.info("install exit=%s output=%s", proc.returncode, out.strip()[:500])
        return proc.returncode == 0
    except Exception:
        log.exception("OCR language install failed")
        return False
