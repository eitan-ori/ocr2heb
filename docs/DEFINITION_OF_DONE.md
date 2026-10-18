# Definition of Done (DoD)

A workstream is **done** only when *every* criterion of its section AND every global gate is ✅
**with evidence** (a command that was run, a bench job name, a number). "I believe it works" is
not evidence. A criterion that cannot be met must be marked ❌ with the exact blocker; the
workstream is then *not done* and says so. Overseers re-run the proofs; they do not trust reports.

Product goal (never lose sight of it): a 97-year-old Hebrew speaker who does not read English
wheel-clicks the mouse anywhere on Windows, and sees the English on screen replaced in place by
Hebrew, in a large calm readable style. If anything fails he must NOT see an error, a traceback,
English text, or a frozen screen - he sees one short Hebrew sentence and clicks again.

## What the owner reported (these drive the five workstreams)
1. "It translates almost everything" - good; paths/commands are (correctly) left untranslated -> **F**.
2. "When you scroll at the same time it looks weird" -> **S**.
3. "When the display gets updated it looks weird" -> **S**.
4. "The translation model isn't so good" -> **T**.
5. "I want the GUI to look the best possible and be the most intuitive" -> **U**.
6. "I don't want errors" -> **R**.
7. "Test its functionality" -> **F**.

Five workstreams, each on its own branch `ws/<name>` in its own git worktree `/home/claude/wt/<name>`:
`functionality` (F), `gui` (U), `robustness` (R), `screen-changes` (S), `translation` (T).

## Environment facts every agent must know
* Agents run in a Linux sandbox: **no Windows, no PyQt5, no winrt, no OCR engine, no PyPI, and almost no
  outbound network** (translation endpoints are NOT reachable from the sandbox; they are reachable from the bench).
  Only Python 3.13 + Pillow + requests are available. Do not try to route around the network policy.
* Windows truth comes from the **bench** on the user's PC (see `docs/BENCH.md`): real OCR, real
  Google translation, real Qt rendering, real mouse hook. Use it. Never guess a Qt/winrt API:
  **any PyQt5/winrt/ctypes call not already proven on the bench must be exercised by a bench job
  before you rely on it** (a previous release crashed on `Qt.TextForceRightToLeft`, an attribute this
  PyQt5 build does not have).
* Code must stay Python 3.9-3.13 compatible and must not add third-party dependencies.
* Private screenshots live in `tests/fixtures/private/` (git-ignored, symlinked). Never commit them,
  never paste their text into commits/docs beyond what a test needs.

## File ownership (to keep five parallel branches mergeable)
| Workstream | Owns (free to restructure) | May touch only surgically / additively |
|---|---|---|
| F functionality | `tests/` fixtures + ground truth, `tools/gen_fixtures.py`, `tools/score_fixture.py`, `layout.py` skip rules, `pipeline.py` analysis, `ocr.py` preprocessing | everything else: fix bugs found, minimal diff |
| U gui | `overlay.py` painting, `fit.py` box styling, `preview.py`, new `design.py`, new welcome/tray UI modules, `docs/DESIGN.md`, `docs/WALKTHROUGH.md` | `app.py` only to wire the welcome window / tray states |
| R robustness | `tests/test_robustness*.py`, `tools/lint.py`, `tools/check_compat.py`, new `safety.py` (crash handler / supervisor) | defensive edits anywhere: smallest possible diff, one commit per fix |
| S screen-changes | `app.py` state machine, `mousehook.py`, `capture.py`, new `live.py` (+ tests), `docs/LIVE_MODE.md` | `overlay.py`: ADD methods only (e.g. capture exclusion, atomic swap); painting belongs to U |
| T translation | `translate.py`, new `providers/`, `glossary.py`, `textfix.py`, `tests/test_translation*.py`, `tests/fixtures/translation_corpus.tsv`, `tools/eval_translation.py`, `docs/TRANSLATION.md` | `pipeline.py` call sites only; keep `Translator.translate(list)->list` unchanged |
New Hebrew strings: append to `config.T` inside a block delimited by `# --- <workstream> ---` (merge-friendly).
Commit early and often; rebase onto `main` is NOT needed - the merge agent integrates. Never force-push `main`.

## Global gates (all workstreams, all branches)
| ID | Gate | Proof |
|----|------|-------|
| G1 | `python3 tests/run_all.py` exits 0 on the branch; no test skipped without a written reason | paste last lines of output |
| G2 | Bench task `tests` is `done` on the branch (real Windows Python + real Qt) | job name + `status.json` |
| G3 | Bench task `selftest` ends `SELFTEST PASSED` | job name + `out/selftest.txt` |
| G4 | No uncaught exception anywhere: tests install counting hooks for `sys.excepthook` and `threading.excepthook`; count must be 0 | test name |
| G5 | No new third-party dependency (`requirements*.txt` unchanged unless reviewed + justified in the report) | `git diff` |
| G6 | Every user-visible string is Hebrew and lives in `config.T`; no English, no technical word, no stack trace is ever shown to the user | grep + test |
| G7 | No secrets / private screenshots / personal data committed | `git ls-files` check |
| G8 | Commits are small, messages explain why, and end with the attribution trailer given by the coordinator | `git log` |
| G9 | `docs/reports/<workstream>.md` exists: one row per criterion (✅/❌), proof, and a "what I could not verify" section | file |

## Shared measurement tools (the functionality workstream creates them; others reuse)
* `tests/fixtures/ground_truth/<fixture>.json`: hand-written truth for a fixture image:
  `{"translate": ["exact English line", ...], "keep": [{"text": "...", "bbox": [x,y,w,h], "why": "hebrew|technical|ui-chrome"}]}`.
* `tools/score_fixture.py <result.json> <ground_truth.json>` prints and returns
  **line recall** = fraction of `translate` lines (that the OCR actually read) covered by a drawn
  item, and **false-positive rate** = fraction of drawn items overlapping a `keep` region by >30% of the item's area
  or whose source text is a `keep` text. Also prints **OCR recall** = fraction of `translate` lines the OCR engine read at all.

---
## Workstream F - Functionality ("it must translate what it should and leave the rest alone")
Root causes found in the first demo (must be fixed and covered by tests): (1) on a Hebrew screen the
English OCR engine hallucinated Latin "words" from Hebrew glyphs and the app drew junk boxes over
perfectly good Hebrew; (2) paths, commands, CamelCase identifiers (`OCRTranslator`, `--demo`) were translated;
(3) the old demo toggled itself off (already fixed in `app.run_demo`; keep it fixed).

| ID | Criterion | Threshold / proof |
|----|-----------|-------------------|
| F1 | Fixture suite: the 2 real screenshots + **>= 12 synthetic** screens made by `tools/gen_fixtures.py` (light/dark article, dialog, form, table, menu, code editor, tiny 9-11 px text, big headings, buttons, low-contrast grey, Hebrew UI with a few English words, mixed Hebrew+English paragraph), each with ground truth | files exist, bench `pipeline` job over all of them |
| F2 | **Hebrew is never covered**: on every fixture, false-positive rate over `keep` regions of kind `hebrew` | **= 0 boxes** on `real_demo_before_hebrew_explorer` over Hebrew text; overall FP rate <= 2 % |
| F3 | **Technical tokens are never translated**: file paths, URLs, e-mails, `--flags`, CamelCase/snake_case identifiers, file names + extensions, version numbers, hex, shell prompts, code | unit tests with >= 40 labelled strings, 0 wrong decisions; and 0 on fixtures |
| F4 | **English is translated**: line recall of lines the OCR read | >= 95 % on every synthetic fixture and >= 90 % on `real_demo_after_english_chat` |
| F5 | **OCR recall** (what the engine reads at all) improved by preprocessing where useful (scale choice, inverted pass for dark themes, contrast) and measured | >= 90 % on clean synthetic fixtures, >= 80 % on the real English screen; report before/after |
| F6 | Translation integrity: results always aligned with their blocks; quotes, numbers, brand names, newline merging, empty/huge input, cache and parallelism covered by tests with a fake HTTP session | tests |
| F7 | Mixed-direction text reads correctly (English brand/number inside a Hebrew sentence) in the rendered PNG | visual check recorded in report |
| F8 | Speed on bench `pipeline`, 1920x1080, ~40 blocks, warm | median <= 3.5 s, p95 <= 6 s total (ocr+translate+plan) |
| F9 | `--demo` is trustworthy: waits for the result, keeps the overlay, saves meaningful before/after | test + bench evidence |

## Workstream U - GUI / UX ("a 97-year-old understands it without being told")
Design target: very large, very calm, very high contrast, Hebrew, zero jargon, one action at a time.
| ID | Criterion | Threshold / proof |
|----|-----------|-------------------|
| U1 | `docs/DESIGN.md`: principles, type scale, colour tokens, spacing, tone-of-voice rules for the Hebrew copy | file |
| U2 | **Translation boxes** look clean and trustworthy: consistent padding, subtle border/shadow distinguishing translation from original, line-height >= 1.3, no clipped text, never smaller than the original text nor than 18 px | bench `pipeline` PNGs reviewed + automated check: for every item, measured text height <= box height |
| U3 | **Contrast** WCAG >= 7:1 (AAA) for every text/background pair actually drawn (boxes, pills, welcome window); computed in a test over bench `result.json` and the design tokens | test |
| U4 | **Status / error / hint / ready messages**: large (>= 32 px), animated "working" indicator, auto-dismiss times sensible, never covering the text being translated if avoidable | `render` PNGs |
| U5 | **First-run welcome** window (shown once, remembered in appdata): huge Hebrew text, a drawn mouse-wheel illustration, a single big button; closes itself or on one click; never shown again; skippable | `render` PNG + test of the "show once" logic |
| U6 | Tray icon: clear states (ready / working / problem) and a tooltip in Hebrew; a "how to use" entry re-opens the welcome | `render`/bench evidence |
| U7 | **Walkthrough** `docs/WALKTHROUGH.md`: step-by-step cognitive walkthrough for Grandpa (first launch, first use, close, error, no internet, first English page, accidental click, scroll while translated) - every step <= 1 action, every failure has a recovery that needs zero reading | file + each step mapped to a rendered PNG |
| U8 | Visual QA loop: >= 3 render-review-fix iterations; before/after PNGs saved under `docs/design/`; the report lists what each iteration changed | files |
| U9 | Hebrew copy reviewed: natural, polite, masculine singular consistent, no English; list of all strings + rationale in `docs/DESIGN.md` | file |
| U10 | All new Qt calls exercised on the bench (G3/render) - zero unverified API | job names |

## Workstream R - Robustness ("I don't want errors")
| ID | Criterion | Threshold / proof |
|----|-----------|-------------------|
| R1 | **Fault-injection matrix** (tests with fakes): OCR missing / throws / hangs; translation 4xx / 5xx / 429 / timeout / garbage JSON / empty / huge / DNS failure; capture failure; Qt paint exception; hook callback exception; unwritable log dir / disk full; autostart failure; mutex failure. For **each**: no uncaught exception (G4), state returns to IDLE within the timeout, user sees a Hebrew message or nothing, never English/traceback | one test per cell, listed in report |
| R2 | **Fuzz / property tests** (seeded, >= 5,000 cases, seed printed): random OCR output (empty, 10 k words, overlapping/negative/NaN/inf/huge/zero-size boxes, zalgo, RTL marks, 1 k-char words) through `pipeline`/`layout`/`fit`: never raises, items inside the screen, box always covers the whole original block | tests |
| R3 | **Concurrency**: click storms (100 clicks / 2 s), click during startup, during error banner, during working, scroll/dismiss storms, cancel then late result; state-machine invariants hold (property test), no deadlock (every test has a hard timeout) | tests |
| R4 | **Resources**: 500 simulated jobs -> bounded memory (cache capped), no leftover temp files (`cap_*.bmp`), log rotation works, threads do not accumulate | test |
| R5 | **Windows reality** on the bench: bench `hook` job passes (installed, single click = 1 event, burst of 5 = debounced), hook re-install works, single-instance mutex works, `selftest` passes, no console window flashes, `--demo` works end to end | job names |
| R6 | **No silent failure**: no bare `except:` / `except Exception: pass` without a log line (checked by `tools/lint.py`, an AST checker you write); every thread entry point wrapped; a global crash handler logs, shows one Hebrew sentence and keeps the process alive; supervisor/watchdog behaviour documented and tested | lint output |
| R7 | **Startup scenarios**: no internet, missing English OCR pack, unreadable/corrupt appdata, read-only log dir, two instances, started before the desktop is ready: app still starts or exits cleanly with a Hebrew explanation | tests + bench |
| R8 | **Compatibility checker** `tools/check_compat.py` (AST): rejects syntax/APIs newer than Python 3.9 (match, except*, PEP 604 at runtime, removed/new stdlib names) and flags PyQt5 attributes not on a bench-verified allow-list `docs/qt_verified.txt` | script + output |

## Workstream S - Screen changes ("the translation must stay correct while the screen moves")
Owner's complaints: scrolling while a translation is shown (or being made) looks weird, and so does any screen
update (page loads, window moves, video, menus opening, typing). Today the overlay is one frozen picture; the app
dismisses it on scroll/click, which feels abrupt, and any change leaves Hebrew boxes hanging over content that moved.
Target behaviour: a calm **live mode** - wheel click turns translation ON, wheel click turns it OFF; while ON the
Hebrew follows the screen: stale boxes disappear instantly, then the new Hebrew fades in once the screen is stable.
The design below is the recommended one; the owner may choose a better design **if justified with measurements**.

| ID | Criterion | Threshold / proof |
|----|-----------|-------------------|
| S1 | `docs/LIVE_MODE.md`: state machine (OFF / WORKING / SHOWING / STALE-REFRESHING), every transition, timings, behaviour for scroll, click, typing, window move/resize, video/animation, menus, screen lock, monitor change; CPU/memory budget | file |
| S2 | **Overlay is invisible to capture**: `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE=0x11)` (Windows 10 2004+) so re-capturing needs no hide/show flicker; verified on the bench with a real capture while the overlay is up (overlay region pixel-identical to the screen without overlay, tolerance 2/255); a tested fallback (hide-capture-show, <= 80 ms) when unsupported | bench `script` job + unit test of fallback |
| S3 | **No stale boxes**: when the content under a box changes, that box stops being drawn within **150 ms** of the change (change detection on a downscaled frame diff); never a box over content it no longer describes for longer than that | bench script that scrolls/changes a real window and samples overlay state; numbers in report |
| S4 | **Refresh after settle**: after the last change (scroll stops, page finished loading) the new Hebrew is visible within **1.2 s warm / 3.5 s cold** (1080p, ~40 blocks); settle window 250-400 ms; unchanged text is served from the translation cache | bench numbers |
| S5 | **Atomic swap, no flicker**: new boxes replace old ones in one repaint; no intermediate blank frame while the screen is unchanged; fade durations <= 150 ms and respect a `config` flag to disable animation | test with a fake clock + bench render |
| S6 | **Cost**: idle-with-overlay <= 8 % of one core, while content changes <= 25 %; memory bounded; turning OFF stops every timer/thread (verified by thread count before/after) | measurement script |
| S7 | **Animated content is harmless**: blinking caret, clock, small spinners, video, GIFs do not cause a refresh storm: ignore changes below an area threshold; global rate limit (<= 1 refresh / 1.5 s); a continuously changing screen degrades to "translation hidden + calm hint" rather than thrashing | synthetic frame tests (>= 10 scenarios) |
| S8 | **Input semantics**: wheel click toggles; scroll / left / right click / typing no longer dismiss in live mode (they just trigger a refresh); debounce preserved; `config.LIVE_MODE=False` restores the old one-shot behaviour; the R3 state-machine invariants hold for both modes | tests |
| S9 | **Mouse hook stays cheap**: scroll/click callbacks only enqueue a coalesced signal; measured callback time <= 1 ms; the hook never blocks even if the GUI thread is busy | bench `hook`/script measurement |
| S10 | **Multi-monitor / DPI**: the monitor under the cursor is used; if the translated window moves to another monitor the overlay follows or clears; verified with fakes + bench at the real DPI | tests + bench |
| S11 | Visual proof: PNG sequence (before scroll / during / after) rendered on the bench showing no half-state; owner's two complaints each mapped to the evidence that fixes them | `docs/design/live_*.png` + report |

## Workstream T - Translation quality ("the translation model isn't so good")
Constraint: **free and keyless** (no paid API, no secret in the repo). Evidence must come from the bench (the sandbox
cannot reach translation services). Ground truth is a hand-written Hebrew reference corpus; metric chrF++ (implement
it in `tools/eval_translation.py`, no dependencies) plus category exact-match on glossary items.

| ID | Criterion | Threshold / proof |
|----|-----------|-------------------|
| T1 | **Corpus**: `tests/fixtures/translation_corpus.tsv` (`id<TAB>category<TAB>english<TAB>hebrew_reference`) with >= 250 items: >= 100 UI labels/menus/buttons (Windows, Office, browser, chat apps), >= 50 short system/error messages, >= 50 prose sentences/paragraphs, >= 50 mixed (numbers, units, brand names, quotes, punctuation, ALL CAPS, OCR-noisy variants) | file + counts |
| T2 | **Provider study** on the bench (`script` task): >= 4 keyless providers incl. the current Google endpoint as baseline (candidates: other Google client variants, Microsoft/Edge translator, Bing, MyMemory, Lingva, public LibreTranslate; anything else free); per provider: chrF++ per category, p50/p95 latency, failure rate, rate-limit behaviour, ToS/privacy note | `docs/TRANSLATION.md` table + job names |
| T3 | **Chosen design**: best primary + ordered fallbacks behind the unchanged `Translator.translate(list)->list` contract; per-provider circuit breaker; automatic fail-over; offline detection <= 3 s -> `NoInternet` | tests with fake sessions |
| T4 | **Measured quality gain**: chrF++ over the whole corpus **>= +6 points absolute vs the baseline pipeline** (provider + pre/post-processing), no category worse than baseline - or, if the baseline provider is already best, the gain must come from T5-T8 and still reach the threshold; if unreachable, report the measured ceiling (⚠) | bench before/after |
| T5 | **Context-aware handling**: classify blocks (UI label / heading / sentence / message) and adapt: ALL CAPS and Title Case labels normalised before translation, trailing punctuation rules, very short labels translated with a UI-biased variant or the glossary; each trick's effect measured separately and kept only if it helps | ablation table |
| T6 | **OCR-noise repair** before translation (conservative): `l`/`I`/`1`/`|`, `0`/`O`, `rn`/`m`, broken hyphenation, missing spaces, stray quotes; never touches technical tokens (F3) | >= 30 labelled cases + effect on the noisy corpus items |
| T7 | **Terminology**: `glossary` of >= 300 UI terms in standard Windows/Microsoft Hebrew UI wording (File=קובץ, Edit=עריכה, View=תצוגה, Settings=הגדרות, ...), applied to whole-label matches (case-insensitive) and used to protect brand/product names (Google, Chrome, Windows, Word, Excel, Teams, ...) | tests: terms used, sentences not corrupted |
| T8 | **Hebrew post-processing**: bidi-safe mixing of English/numbers inside Hebrew, punctuation at the correct (right) end, mirrored quotes/brackets, units/percent signs, double spaces, no Latin leftovers from provider markup | >= 40 tests + visual check in a rendered PNG |
| T9 | **Long text**: sentence-aware splitting of long blocks, order preserved, never a dropped or duplicated sentence (provider that drops/merges lines is simulated) | tests |
| T10 | **Persistent cache**: on disk under appdata, size cap + TTL, corrupt-file tolerant, clearable; repeat translations served locally (measure) | tests + numbers |
| T11 | **Provider robustness**: timeouts, jittered backoff, 429/5xx, malformed JSON, empty reply, captcha/HTML page instead of JSON -> handled, logged, next provider; no exception other than `NoInternet`/`TranslateError` ever escapes | fault matrix tests |
| T12 | **Privacy / terms note** in `docs/TRANSLATION.md`: exactly what text is sent to whom; keyless only; how to switch the provider off; no personal data stored beyond the capped cache | file |
| T13 | **Speed does not regress**: F8 budget holds with the new chain (cold and warm) | bench numbers |


## Overseers
**Succession agent** (continuity / hand-off): for each workstream, re-runs the proofs listed in its report
(Linux tests + fresh bench jobs), recomputes the metrics, checks the DoD row by row, and checks the *baton*:
(a) each branch's reports are reproducible from a clean checkout, (b) shared contracts (`pipeline.py` API,
`config.T`, `Item`, `Overlay`, `Translator`, bench tasks) are not broken by another branch (dry-run merges of all five in a scratch
worktree: conflicts and test results), (c) nothing one workstream guarantees is undone by another.
Verdict per criterion + overall `READY_TO_MERGE` or `REWORK` with a numbered remediation list. -> `docs/reports/succession.md`.

**Code-review agent**: reads every diff (`git diff main...ws/<name>`) with a checklist: correctness; thread-safety and
"Qt only on the main thread"; ctypes 64-bit signatures; resource and handle leaks; exception handling; Python 3.9
compatibility; unverified Qt/winrt API use; PyInstaller hidden-import impact; security (temp files, subprocess,
no shell injection); Hebrew typos; dead code; test quality (do tests really fail when the code is wrong? try mutating).
Findings ranked blocker / major / minor with file:line and a concrete fix. -> `docs/reports/code-review.md`.
Blockers and majors must be fixed by the owning workstream (max 2 rework rounds).

**Merge agent**: merges the five branches (order: functionality, robustness, translation, screen-changes, gui) in a fresh worktree, resolves
conflicts keeping every branch's tests, re-runs G1-G3 and *all* F/U/R proofs on the merged tree (bench `tests`,
`selftest`, `pipeline` over every fixture, `render`, `hook`), compares metrics to the per-branch numbers (no
regression), fixes integration breakage, pushes, fast-forwards `main`, tags `v1.1.0`, writes `docs/reports/merge.md`.
Finally requests a bench `build` job and verifies the exe was produced.

## Stop rules (so "iterate until done" terminates)
* A workstream agent may spend at most **8 bench jobs** per criterion group (translation benchmarks: batch the whole corpus in one job) and **2 rework rounds** after review.
* If the bench is down (no fresh heartbeat): do all Linux-verifiable work FIRST (the owner may start the watcher
  while you work), re-check the heartbeat before every bench step and once more before finishing; only if it is still
  stale then report `BLOCKED: bench` precisely, listing exactly which criteria lack Windows evidence. Do not fake evidence.
* If a threshold is physically unreachable (e.g. the OCR engine cannot read 9 px grey text), do not move the goalpost
  silently: document the measurement, propose a new threshold with justification, mark the criterion ⚠ - the coordinator decides.
