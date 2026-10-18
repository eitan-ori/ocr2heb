"""Executed by watcher.py:  python run_task.py <job_dir>

Runs ONE whitelisted task against the candidate code in <job_dir>/src and writes
everything into <job_dir>/out/. Exit code 0 = task succeeded.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import traceback

JOB = os.path.abspath(sys.argv[1])
with open(os.path.join(JOB, "job.json"), encoding="utf-8") as _fh:
    SPEC = json.load(_fh)
SRC = os.path.join(JOB, "src")
OUT = os.path.join(JOB, "out")
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # ...\OCRTranslator
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, SRC)
os.environ["OCR2HEB_BENCH"] = "1"
try:                                                   # same DPI mode as the real app
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass


def dump(name: str, obj) -> str:
    path = os.path.join(OUT, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1, ensure_ascii=False)
    return path


def qt_app():
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication
    QApplication.setAttribute(Qt.AA_DisableHighDpiScaling, True)
    return QApplication.instance() or QApplication([])


def composite(overlay_png: str, background, out_png: str) -> None:
    from PIL import Image
    over = Image.open(overlay_png).convert("RGBA")
    base = background.convert("RGBA").resize(over.size)
    Image.alpha_composite(base, over).convert("RGB").save(out_png)


def md5(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()


# --------------------------------------------------------------------- tasks
def task_echo() -> int:
    files = {}
    for base, _dirs, names in os.walk(JOB):
        if os.path.relpath(base, JOB).split(os.sep)[0] == "out":
            continue
        for n in names:
            p = os.path.join(base, n)
            files[os.path.relpath(p, JOB).replace("\\", "/")] = {"bytes": os.path.getsize(p), "md5": md5(p)}
    dump("echo.json", {"python": sys.version, "platform": platform.platform(), "spec": SPEC, "files": files})
    return 0


def task_selftest() -> int:
    import appdata
    import selftest
    rc = selftest.run()
    report = os.path.join(appdata.log_dir(), "selftest.txt")
    if os.path.exists(report):
        shutil.copy(report, os.path.join(OUT, "selftest.txt"))
    return rc


def task_tests() -> int:
    env = dict(os.environ, PYTHONPATH=SRC, PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.run([sys.executable, os.path.join(JOB, "tests", "run_all.py")], cwd=JOB, env=env,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    with open(os.path.join(OUT, "tests_output.txt"), "w", encoding="utf-8") as fh:
        fh.write(proc.stdout + "\n--- stderr ---\n" + proc.stderr)
    return proc.returncode


def _inputs():
    return [os.path.join(JOB, "inputs", n) for n in SPEC.get("inputs", [])]


def task_ocr() -> int:
    from PIL import Image
    import ocr as ocr_mod
    svc = ocr_mod.OcrService()
    summary = []
    for path in _inputs():
        stem = os.path.splitext(os.path.basename(path))[0]
        entry = {"input": os.path.basename(path)}
        try:
            img = Image.open(path).convert("RGB")
            t0 = time.monotonic()
            lines = svc.recognize(img)
            entry.update(ok=True, seconds=round(time.monotonic() - t0, 3), lines=len(lines))
            dump(stem + ".ocr.json", {"size": list(img.size), "lines": [
                [{"text": w.text, "x": w.x, "y": w.y, "w": w.w, "h": w.h} for w in line] for line in lines]})
        except Exception:
            entry.update(ok=False, error=traceback.format_exc())
        summary.append(entry)
    dump("summary.json", summary)
    return 0 if all(e["ok"] for e in summary) else 1


def task_pipeline() -> int:
    from PIL import Image
    import ocr as ocr_mod
    import overlay
    import pipeline
    import translate as tr_mod
    from config import T

    qt_app()
    svc = ocr_mod.OcrService()
    translator = tr_mod.Translator() if SPEC.get("translate", True) else None
    summary = []
    for path in _inputs():
        stem = os.path.splitext(os.path.basename(path))[0]
        entry = {"input": os.path.basename(path)}
        try:
            img = Image.open(path).convert("RGB")
            res = pipeline.run(img, svc, translator, measure=overlay.qt_measure)
            data = res.to_json()
            dump(stem + ".result.json", data)
            if res.items:
                ov = overlay.Overlay()
                raw = os.path.join(OUT, stem + ".raw.png")
                ov.render_to_file(raw, img.size, items=res.items, hint=T.HINT)
                composite(raw, img, os.path.join(OUT, stem + ".overlay.png"))
                os.remove(raw)
            entry.update(ok=True, blocks=len(res.blocks), items=len(res.items),
                         skipped=pipeline.summarize_skipped(res.skipped), timings=data["timings"])
        except Exception:
            entry.update(ok=False, error=traceback.format_exc())
        summary.append(entry)
    dump("summary.json", summary)
    return 0 if all(e["ok"] for e in summary) else 1


def task_render() -> int:
    import preview
    qt_app()
    paths = preview.render_states(os.path.join(OUT, "render"))
    dump("render.json", [os.path.relpath(p, OUT).replace("\\", "/") for p in paths])
    return 0


def task_hook() -> int:
    """Install the real hook and inject middle clicks (they must be swallowed and debounced)."""
    from mousehook import MouseHook
    events = []
    hook = MouseHook(on_middle=lambda: events.append(time.monotonic()), debounce=0.45)
    report = {"installed": hook.start()}
    rc = 1
    if report["installed"]:
        user32 = ctypes.windll.user32

        def click():
            user32.mouse_event(0x0020, 0, 0, 0, 0)      # MIDDLEDOWN
            user32.mouse_event(0x0040, 0, 0, 0, 0)      # MIDDLEUP

        click()
        time.sleep(0.6)
        report["after_single_click"] = len(events)
        for _ in range(5):                               # a shaky hand: 5 clicks in 0.25 s
            click()
            time.sleep(0.05)
        time.sleep(0.6)
        report["after_burst"] = len(events)
        hook.stop()
        rc = 0 if (report["after_single_click"] == 1 and report["after_burst"] == 2) else 1
    dump("hook.json", report)
    return rc


def task_build() -> int:
    icon = os.path.join(PROJECT, "assets", "app.ico")
    work = os.path.join(JOB, "work")
    hidden = []
    for mod in ("foundation", "foundation.collections", "storage", "storage.streams", "globalization",
                "graphics.imaging", "media.ocr"):
        hidden += ["--hidden-import", "winrt.windows." + mod]
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--noconsole",
           "--uac-admin", "--name", "OCR2Heb", "--paths", SRC, "--distpath", OUT, "--workpath", work,
           "--specpath", work, "--exclude-module", "tkinter", "--exclude-module", "matplotlib",
           "--exclude-module", "numpy"] + hidden
    if os.path.exists(icon):
        cmd += ["--icon", icon]
    cmd.append(os.path.join(SRC, "main.py"))
    proc = subprocess.run(cmd, cwd=JOB, capture_output=True, text=True, encoding="utf-8", errors="replace")
    with open(os.path.join(OUT, "build_output.txt"), "w", encoding="utf-8") as fh:
        fh.write(proc.stdout[-100_000:] + "\n--- stderr ---\n" + proc.stderr[-100_000:])
    exe = os.path.join(OUT, "OCR2Heb.exe")
    if proc.returncode == 0 and os.path.exists(exe):
        dump("build.json", {"exe": "OCR2Heb.exe", "bytes": os.path.getsize(exe), "md5": md5(exe)})
        return 0
    return 1


def task_script() -> int:
    """Run ONE script that was uploaded in <job>/scripts/ (name given by job.json["script"]).

    The script sees: env OUT_DIR (write results there), PYTHONPATH=<job>/src, OCR2HEB_BENCH=1,
    and inputs in <job>/inputs. Used for translation benchmarks and Windows-only experiments
    (e.g. capture exclusion) that are not an image pipeline.
    """
    import re
    name = str(SPEC.get("script", ""))
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*\.py", name):
        print(f"bad script name {name!r}")
        return 2
    path = os.path.join(JOB, "scripts", name)
    if not os.path.isfile(path):
        print(f"script not found: {path}")
        return 2
    env = dict(os.environ, OUT_DIR=OUT, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""),
               OCR2HEB_BENCH="1", PYTHONIOENCODING="utf-8")
    proc = subprocess.run([sys.executable, path], cwd=JOB, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    sys.stdout.write(proc.stdout or "")
    sys.stderr.write(proc.stderr or "")
    return proc.returncode


TASKS = {"echo": task_echo, "selftest": task_selftest, "tests": task_tests, "ocr": task_ocr,
         "pipeline": task_pipeline, "render": task_render, "hook": task_hook, "build": task_build,
         "script": task_script}


def main() -> int:
    task = SPEC.get("task")
    if task not in TASKS:
        print(f"unknown task {task!r}")
        return 2
    try:
        return int(TASKS[task]() or 0)
    except SystemExit as exc:
        return int(exc.code or 0)
    except Exception:
        text = traceback.format_exc()
        print(text)
        with open(os.path.join(OUT, "error.txt"), "w", encoding="utf-8") as fh:
            fh.write(text)
        return 1


if __name__ == "__main__":
    sys.exit(main())
