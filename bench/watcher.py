"""OCR2Heb Windows bench watcher.

Start with bench\\start_watcher.bat and leave the window open; close it to stop.

It watches bench\\jobs\\ for job folders (job.json + src/ + optional inputs/ tests/ and a
ready.txt marker that is uploaded LAST) and runs them through run_task.py, which only
knows a fixed list of whitelisted tasks (ALLOWED below). Nothing else is executed:
no shell commands from job files, nothing outside bench\\jobs\\ is touched.

Heartbeat: bench\\heartbeat.json is refreshed every few seconds so agents can tell
whether the bench is alive.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
JOBS = os.path.join(ROOT, "jobs")
RUNNER = os.path.join(ROOT, "run_task.py")
HEARTBEAT = os.path.join(ROOT, "heartbeat.json")
VERSION = 2

# task name -> timeout in seconds
ALLOWED = {
    "echo": 60,          # smoke test: lists what was uploaded
    "selftest": 240,     # candidate src: OCR / translation / hook / capture / Qt measuring
    "tests": 600,        # candidate tests/run_all.py with the real Windows Python + Qt
    "ocr": 600,          # OCR only on inputs/*.png -> <stem>.ocr.json
    "pipeline": 900,     # real OCR + real translation + real Qt render on inputs/*.png
    "render": 240,       # preview.render_states() -> PNGs of every UI state
    "hook": 120,         # real mouse hook: injected middle clicks are swallowed + debounced
    "build": 900,        # PyInstaller one-file exe of candidate src -> out/OCR2Heb.exe
    "script": 900,       # one named python script from the job's scripts/ folder (benchmarks, Windows-only experiments)
}
KEEP_HOURS = 12


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def write_json(path: str, data) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def say(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def pending() -> list:
    found = []
    for name in os.listdir(JOBS):
        d = os.path.join(JOBS, name)
        ready = os.path.join(d, "ready.txt")
        if os.path.isdir(d) and os.path.exists(ready) and not os.path.exists(os.path.join(d, "status.json")):
            found.append((os.path.getmtime(ready), d))
    return [d for _, d in sorted(found)]


def recover_interrupted() -> None:
    for name in os.listdir(JOBS):
        sp = os.path.join(JOBS, name, "status.json")
        if os.path.exists(sp):
            try:
                with open(sp, encoding="utf-8") as fh:
                    st = json.load(fh)
                if st.get("state") == "running":
                    st.update(state="interrupted", finished=now())
                    write_json(sp, st)
            except Exception:
                pass


def prune() -> None:
    cutoff = time.time() - KEEP_HOURS * 3600
    for name in os.listdir(JOBS):
        d = os.path.join(JOBS, name)
        sp = os.path.join(d, "status.json")
        if os.path.isdir(d) and os.path.exists(sp) and os.path.getmtime(sp) < cutoff:
            shutil.rmtree(d, ignore_errors=True)


def run_job(d: str) -> None:
    name = os.path.basename(d)
    status_path = os.path.join(d, "status.json")
    status = {"job": name, "started": now()}
    t0 = time.time()
    try:
        real, jobs_real = os.path.realpath(d), os.path.realpath(JOBS)
        if not real.startswith(jobs_real + os.sep):
            raise ValueError("job folder outside bench\\jobs")
        with open(os.path.join(d, "job.json"), encoding="utf-8") as fh:
            spec = json.load(fh)
        task = spec.get("task")
        if task not in ALLOWED:
            raise ValueError(f"task {task!r} is not whitelisted")
        status.update(task=task, state="running")
        write_json(status_path, status)
        say(f"RUN   {name}  task={task}")
        out = os.path.join(d, "out")
        os.makedirs(out, exist_ok=True)
        proc = subprocess.run([sys.executable, RUNNER, d], cwd=d, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=ALLOWED[task])
        for fname, text in (("stdout.txt", proc.stdout), ("stderr.txt", proc.stderr)):
            with open(os.path.join(out, fname), "w", encoding="utf-8") as fh:
                fh.write((text or "")[-200_000:])
        status.update(state="done" if proc.returncode == 0 else "failed", returncode=proc.returncode)
    except subprocess.TimeoutExpired:
        status.update(state="timeout")
    except Exception:
        status.update(state="error", error=traceback.format_exc())
    status.update(seconds=round(time.time() - t0, 1), finished=now())
    write_json(status_path, status)
    say(f"{status['state'].upper():9} {name}  ({status['seconds']}s)")


def main() -> int:
    os.makedirs(JOBS, exist_ok=True)
    say(f"OCR2Heb bench watcher v{VERSION} started (pid {os.getpid()}).")
    say(f"Watching {JOBS}")
    say("Runs only whitelisted tasks: " + ", ".join(sorted(ALLOWED)))
    say("Leave this window open. Close it to stop.")
    recover_interrupted()
    last_prune = 0.0
    while True:
        queue = pending()
        write_json(HEARTBEAT, {"time": now(), "epoch": time.time(), "pid": os.getpid(),
                               "queue": len(queue), "version": VERSION, "tasks": sorted(ALLOWED)})
        if queue:
            run_job(queue[0])
            continue
        if time.time() - last_prune > 600:
            prune()
            last_prune = time.time()
        time.sleep(2.0)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        say("stopped")
