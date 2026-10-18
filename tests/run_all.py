"""Run every tests/test_*.py (each is a plain script with test_* functions). Exit 1 on any failure.

    python3 tests/run_all.py            # from the repo or from a bench job folder
"""
import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> int:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    failed = []
    for path in sorted(glob.glob(os.path.join(HERE, "test_*.py"))):
        name = os.path.basename(path)
        proc = subprocess.run([sys.executable, path], capture_output=True, text=True, env=env)
        passed = sum(1 for line in proc.stdout.splitlines() if line.startswith("PASS"))
        bad = sum(1 for line in proc.stdout.splitlines() if line.startswith("FAIL"))
        print(f"{'OK  ' if proc.returncode == 0 else 'FAIL'} {name}: {passed} passed, {bad} failed")
        if proc.returncode != 0:
            failed.append(name)
            print(proc.stdout[-3000:])
            print(proc.stderr[-3000:])
    print("ALL TESTS PASSED" if not failed else "FAILED: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
