# The Windows bench

The sandbox where agents work cannot run Windows code. The **bench** is a small watcher
(`bench/watcher.py`) that the user starts on their Windows PC (`bench\start_watcher.bat`). It runs a
**fixed list of whitelisted tasks** on job folders and nothing else. Agents upload a job with the device tools,
wait for `status.json`, and fetch the results. This is how real OCR / real translation / real Qt rendering /
the real mouse hook get verified.

Safety: the watcher executes only tasks named in `ALLOWED` (watcher.py); job files cannot add commands; it only
touches `bench\jobs\`. It does run the candidate Python code under `src/` (that is the point: it is the app).

## Tasks
| task | what it does | main outputs in `out/` |
|------|--------------|------------------------|
| `echo` | smoke test: lists uploaded files + md5 | `echo.json` |
| `selftest` | candidate `selftest.run()` (OCR, translation, hook, capture, Qt measuring) | `selftest.txt` |
| `tests` | candidate `tests/run_all.py` on Windows Python with real PyQt5 | `tests_output.txt` |
| `ocr` | OCR only on `inputs/*` | `<stem>.ocr.json`, `summary.json` |
| `pipeline` | OCR -> layout -> real Google translation -> fit -> **real Qt render** over the screenshot | `<stem>.result.json`, `<stem>.overlay.png`, `summary.json` |
| `render` | `preview.render_states(out_dir)` -> PNG of every UI state | `render/*.png`, `render.json` |
| `hook` | installs the real hook, injects middle clicks (must be swallowed, debounced) | `hook.json` |
| `build` | PyInstaller one-file exe of candidate `src/` | `OCR2Heb.exe`, `build.json` |
| `script` | (bench v2) runs ONE python file you upload in `scripts/` (`submit.py --task script --script path.py`). Env: `OUT_DIR` (write results there), `PYTHONPATH=<job>/src`, inputs in `<job>/inputs`. Use for translation benchmarks (real endpoints, no screenshots needed), capture-exclusion and scroll experiments, CPU/latency measurements | whatever the script writes to `OUT_DIR` + stdout/stderr |
`submit.py` packages `src/` and `tests/` recursively (`.py .json .txt .tsv .csv`); pass corpora/images with `--inputs`.
Every job also gets `status.json` (`state`: running|done|failed|timeout|error|interrupted), `out/stdout.txt`, `out/stderr.txt`.
`job.json` field `"translate": false` makes `pipeline` skip the network.

## Protocol (agents)
1. **Heartbeat**: `device_bash`: `cat $HOME/mnt/OCRTranslator/bench/heartbeat.json; date +%s` -> `epoch` must be < 15 s old.
   If stale, wait up to 3 min (`sleep 30` loops), then see the stop rules in the DoD.
2. **Package**: `python3 bench/submit.py --worktree <your worktree> --task pipeline --name <ws>-<n> --inputs <images>`
   Job names are **unique forever** (`gui-001`, `gui-002`, ...). It prints the commit batches.
3. **Upload** each `commit_batch_N.json` in order with `mcp__remote-devices__device_commit_files`
   (`files` = the JSON array, as-is). Then **verify**: `device_bash`:
   `cd $HOME/mnt/OCRTranslator/bench/jobs/<name> && md5sum -c md5sums.txt` - every line must say `OK`.
   (A stale-copy bug was seen once: a commit shipped an older version of a file. If any line fails, run `sync; sleep 3`
   in the sandbox and commit that batch again.) Only then commit `commit_batch_ready.json` - the watcher starts the job.
4. **Wait**: poll `device_bash` `cat $HOME/mnt/OCRTranslator/bench/jobs/<name>/status.json` every ~20 s
   (`state` leaves `running`). Typical: echo 5 s, selftest 40 s, pipeline 30-90 s, tests 30 s, build 2-4 min.
5. **Fetch**: `device_list_dir` on `C:\Users\TLP-001\Desktop\OCRTranslator\bench\jobs\<name>\out`, then
   `device_stage_files` for the files you need -> they appear under
   `/mnt/user-data/uploads/OCRTranslator/bench/jobs/<name>/out/...`. Read PNGs with the Read tool - **look at them**.
6. Record job names + key numbers in your report.

Several agents share one bench; jobs run one at a time in upload order. Do not flood it: batch many fixtures in one job.
If `state` is `error`/`failed`, read `out/stderr.txt`, `out/error.txt` first; fix, resubmit under a new name.
Never edit anything under `bench/` in your branch except by agreement with the coordinator (the watcher/runner on the PC
is fixed; changing the repo copy does not change it).

## Contract your candidate must keep (the runner imports these)
* `selftest.run() -> int`, `pipeline.run(img, ocr, translator, measure)`, `pipeline.Result.to_json()`,
  `ocr.OcrService().recognize(img)`, `translate.Translator().translate(list)`,
  `overlay.Overlay().render_to_file(path, size, items, hint, banner)`, `overlay.qt_measure`,
  `preview.render_states(out_dir)`, `mousehook.MouseHook(on_middle=..., debounce=...)`, `config.T`.
Add to them freely; do not rename or remove without coordinating.
