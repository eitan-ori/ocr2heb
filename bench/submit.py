#!/usr/bin/env python3
"""Package a bench job from a git worktree (container side) and print the upload plan.

    python3 bench/submit.py --worktree /home/claude/wt/gui --task pipeline --name gui-003 \
        --inputs tests/fixtures/private/real_demo_after_english_chat.png tests/fixtures/synth/a.png \
        [--no-translate] [--with-tests]

Creates /mnt/user-data/outputs/bench_jobs/<name>/ with job.json, src/, inputs/, (tests/),
md5sums.txt, and commit batches (JSON arrays for the device_commit_files tool). Job names
must be unique (that folder cannot be cleaned up). See docs/BENCH.md for the full protocol.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime

STAGE_ROOT = "/mnt/user-data/outputs/bench_jobs"
DEVICE_ROOT = r"C:\Users\TLP-001\Desktop\OCRTranslator\bench\jobs"
BATCH = 40
DATA_EXT = (".py", ".json", ".txt", ".tsv", ".csv")


def md5(path):
    with open(path, "rb") as fh:
        return hashlib.md5(fh.read()).hexdigest()


def git(worktree, *args):
    try:
        return subprocess.run(["git", "-C", worktree, *args], capture_output=True, text=True).stdout.strip()
    except Exception:
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--worktree", required=True)
    ap.add_argument("--task", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--inputs", nargs="*", default=[])
    ap.add_argument("--no-translate", action="store_true")
    ap.add_argument("--with-tests", action="store_true")
    ap.add_argument("--script", help="path (relative to the worktree) of a .py to run with --task script")
    a = ap.parse_args()

    job = os.path.join(STAGE_ROOT, a.name)
    if os.path.exists(job):
        sys.exit(f"job {a.name} already exists - use a new unique name")
    os.makedirs(job)

    for sub in ("src", "tests"):
        if sub == "tests" and not (a.with_tests or a.task == "tests"):
            continue
        src_dir = os.path.join(a.worktree, sub)
        os.makedirs(os.path.join(job, sub), exist_ok=True)
        for base, dirs, files in os.walk(src_dir):
            dirs[:] = sorted(d for d in dirs if d not in ("__pycache__", "private", "bench_out", "synth")
                             and not d.startswith("."))
            for name in sorted(files):
                if name.endswith(DATA_EXT):
                    dest = os.path.join(job, sub, os.path.relpath(base, src_dir))
                    os.makedirs(dest, exist_ok=True)
                    shutil.copy2(os.path.join(base, name), os.path.join(dest, name))
    names = []
    for path in a.inputs:
        full = path if os.path.isabs(path) else os.path.join(a.worktree, path)
        os.makedirs(os.path.join(job, "inputs"), exist_ok=True)
        shutil.copy2(full, os.path.join(job, "inputs", os.path.basename(full)))
        names.append(os.path.basename(full))

    script_name = None
    if a.script:
        script_full = a.script if os.path.isabs(a.script) else os.path.join(a.worktree, a.script)
        script_name = os.path.basename(script_full)
        os.makedirs(os.path.join(job, "scripts"), exist_ok=True)
        shutil.copy2(script_full, os.path.join(job, "scripts", script_name))
    if a.task == "script" and not script_name:
        sys.exit("--task script needs --script <file.py>")

    spec = {"task": a.task, "name": a.name, "inputs": names, "translate": not a.no_translate,
            "script": script_name,
            "created": datetime.now().isoformat(timespec="seconds"),
            "branch": git(a.worktree, "rev-parse", "--abbrev-ref", "HEAD"),
            "commit": git(a.worktree, "rev-parse", "--short", "HEAD")}
    with open(os.path.join(job, "job.json"), "w", encoding="utf-8") as fh:
        json.dump(spec, fh, indent=1)

    rels = []
    for base, _d, files in os.walk(job):
        for f in files:
            rels.append(os.path.relpath(os.path.join(base, f), job))
    rels = sorted(r for r in rels if not r.startswith("commit_batch") and r not in ("md5sums.txt", "ready.txt"))
    with open(os.path.join(job, "md5sums.txt"), "w", encoding="utf-8", newline="\n") as fh:
        for r in rels:
            fh.write(f"{md5(os.path.join(job, r))}  {r.replace(os.sep, '/')}\n")
    with open(os.path.join(job, "ready.txt"), "w") as fh:
        fh.write("ready\n")

    def entry(rel):
        return {"stagedPath": f"{STAGE_ROOT}/{a.name}/{rel.replace(os.sep, '/')}",
                "devicePath": DEVICE_ROOT + "\\" + a.name + "\\" + rel.replace("/", "\\").replace(os.sep, "\\")}

    upload = rels + ["md5sums.txt"]
    batches = [upload[i:i + BATCH] for i in range(0, len(upload), BATCH)]
    written = []
    for i, chunk in enumerate(batches, 1):
        path = os.path.join(job, f"commit_batch_{i}.json")
        with open(path, "w") as fh:
            json.dump([entry(r) for r in chunk], fh, indent=1)
        written.append(path)
    ready_path = os.path.join(job, "commit_batch_ready.json")
    with open(ready_path, "w") as fh:
        json.dump([entry("ready.txt")], fh, indent=1)

    print(f"job {a.name}: task={a.task} files={len(upload)} batches={len(batches)}")
    for w in written:
        print("  commit (in order):", w)
    print("  then verify on device:  cd $HOME/mnt/OCRTranslator/bench/jobs/%s && md5sum -c md5sums.txt" % a.name)
    print("  only after every line says OK, commit:", ready_path)
    os.sync()


if __name__ == "__main__":
    main()
