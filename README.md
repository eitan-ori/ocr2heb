# OCR2Heb — wheel-click screen translator (English → Hebrew)

Click the mouse wheel anywhere → the whole screen is OCR'd and the English text is
covered by Hebrew translation, in place. Click again → it disappears.

## Build (once, on your Windows PC)
1. Install Python 3.12 from python.org (tick "Add python.exe to PATH") if you don't have 3.9–3.13.
2. Double-click **`build.bat`**. It creates a venv, installs packages, self-tests
   OCR/translation/mouse-hook, builds the exe, then self-tests the exe (accept the UAC prompt).
3. Result: **`release\OCR2Heb.exe`** (plus `uninstall.bat`, `HEBREW_NOTE.txt`).

If anything fails, copy the `FAIL` lines (or `%LOCALAPPDATA%\OCR2Heb\logs\selftest.txt`) — they say exactly which part broke.

## Deploy to Grandpa (AnyDesk)
Transfer `OCR2Heb.exe`, double-click, accept the one UAC prompt. From then on:
* it registers a **scheduled task** → starts at every logon, elevated, **no UAC prompt**, restarts itself if it crashes;
* a tray icon (blue "א") shows it is alive; a Hebrew "ready" message appears for a few seconds;
* launching it a second time shows a Hebrew "already running" box instead of starting a duplicate.

Remove: run `uninstall.bat` (or `OCR2Heb.exe --uninstall`), then delete the exe.

## Using it
| Action | Result |
|---|---|
| Wheel click | capture screen under the cursor → Hebrew overlay (small "translating…" pill meanwhile) |
| Wheel click again | overlay closes (also cancels a translation in progress) |
| Scroll / left / right click while overlay is up | overlay closes (the screen is about to change; see `config.py`) |
| Anything fails | short calm Hebrew message for 5 s; details go to the log |

The wheel click is *swallowed* by the app, so browsers don't open links in new tabs / start auto-scroll.

## Where things are
* Logs & selftest report: `%LOCALAPPDATA%\OCR2Heb\logs\` (tray menu → "פתח תיקיית לוגים")
* Remote debugging: `OCR2Heb.exe --debug` keeps `last_capture.png`; `OCR2Heb.exe --demo` translates the current screen once and saves `demo_before.png` / `demo_after.png`.
* Tunables (font size, debounce, dismiss behaviour, languages): `src/config.py` → rebuild.

## Design notes
* **OCR**: Windows' built-in engine (`Windows.Media.Ocr`) — free, offline. Needs the *English* OCR pack;
  if missing (e.g. Hebrew-only Windows) the app installs it itself (`Add-WindowsCapability`, needs internet; shows a Hebrew "preparing" message).
* **Translation**: Google's public web endpoint, no key. Blocks are batched, line-count verified (falls back per block), cached, retried; no internet → Hebrew "no internet" message.
* **Privacy**: only the *recognised text* is sent to Google, never the screenshot. Nothing else leaves the PC.
* **Layout**: lines are merged into paragraphs for better Hebrew, menus/columns stay separate; the translated box covers the whole original text, uses the sampled background colour and a readable contrast colour, min font 18 px.
* **Hook**: own ctypes `WH_MOUSE_LL` hook (no extra library), re-installed every minute in case Windows drops it.

## Known limits
* Exclusive-fullscreen games (not borderless) can hide the overlay; borderless/windowed and video players are fine.
* Text inside tiny icons, handwriting or heavily stylised fonts may not be recognised.
* Only English → Hebrew. The overlay is a still picture, not live.
* Unsigned exe: Windows SmartScreen / antivirus may warn about a mouse hook + PyInstaller. If so, allow it once (Defender → "Allow on device") or build with `--onedir` instead of `--onefile`.

## Tests (no Windows needed)
`python tests/test_pipeline.py` — layout grouping, translation batching/fallback/offline, colour & fitting logic.
