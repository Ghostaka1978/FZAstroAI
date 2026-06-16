# FZAstro AI v1.0.0 Version 1 Release Candidate Build and Validation

This file is the release checklist for **FZAstro AI v1.0.0 — Version 1 Release Candidate**.

Do not call a build production until the automated tests, validation script, and manual acceptance checklist pass on the target Windows machine.

## 1. Recreate or activate the Python 3.11 environment

The release workflow requires Python 3.11. Do not use Python 3.14 or another non-3.11 interpreter for release builds. The release scripts enforce this with `Get-PythonVersionInfo` and `Assert-Python311`.

Use a fresh PowerShell window from the project root. If the prompt already shows `(.venv)`, run `deactivate` and open a fresh shell before resetting the environment.

```powershell
powershell -ExecutionPolicy Bypass -File .\reset_venv.ps1 -Force
. .\activate_venv.ps1
```

Manual equivalent:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`activate_venv.ps1` sets `FZASTRO_PYTHON`, `FZASTRO_PROJECT_ROOT`, and `FZASTRO_BUILD_ROOT` for child build and validation commands. By default, build output is created one folder above the project root under `..\FZAstroAI_BUILD`.

Optional browser install for Playwright-backed web features:

```powershell
python -m playwright install chromium
```

Release builds install Chromium package-locally through `build_exe.ps1` so PyInstaller can bundle it. If the bundled browser is unavailable at runtime, the app falls back to installed Microsoft Edge or Google Chrome.

## 2. Format and test before building

Run Black before testing and building:

```powershell
powershell -ExecutionPolicy Bypass -File .\format_code.ps1 -PythonExe ".\.venv\Scripts\python.exe"
python -m pytest
```

For CI/release verification, use check mode:

```powershell
powershell -ExecutionPolicy Bypass -File .\format_code.ps1 -PythonExe ".\.venv\Scripts\python.exe" -Check
```

The build script also runs Black before compiling and testing unless `-SkipFormat` is passed.

## 3. Deploy with the one-command workflow

Recommended command:

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy.ps1
```

`deploy.ps1` is the single release workflow command. It calls `clean_build.ps1`, and `clean_build.ps1` starts `build_exe.ps1` automatically after cleaning previous build/cache output. At the end of a successful build, the build script displays a validation prompt asking whether to run `validate_release.ps1` immediately.

The deploy/build/validation scripts use a quiet progress display by default. They show a progress bar and the current cleanup/build/validation stage while sending noisy pip, pytest, Black, and PyInstaller output to `..\FZAstroAI_BUILD\logs`. Use `-VerboseOutput` on `deploy.ps1`, `build_exe.ps1`, or `validate_release.ps1` when full live command output is needed.

To run the build without the cleaning wrapper:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1 -PythonExe ".\.venv\Scripts\python.exe"
```

Release output should be created here:

```text
..\FZAstroAI_BUILD\release\FZAstroAI.exe
```

The release folder includes `FZAstroAI.exe`, `README.md`, `RELEASE_VALIDATION.md`, `requirements.txt`, `VERSION.txt`, and a `release_manifest.txt` with the EXE size and SHA256 hash. Validation requires the release manifest and these required release files.

## 4. Validate the EXE

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\validate_release.ps1 -PythonExe ".\.venv\Scripts\python.exe" -ExePath "..\FZAstroAI_BUILD\release\FZAstroAI.exe" -KeepRunning
```

This checks:

- EXE exists and SHA256 hash can be calculated.
- `VERSION.txt` reports the Version 1 release version.
- Black formatting check passes.
- Source code compiles.
- Automated tests pass.
- Critical Python imports work, including `fzastro_ai.ui.llm_benchmark_dialog`.
- Ollama availability, local auto-start behavior, and clear unavailable status when local Ollama cannot be reached.
- Tesseract availability.
- Playwright Chromium availability or installed Edge/Chrome fallback.
- PyInstaller resource configuration markers for bundled icons, astronomy tools, Astropy/SAMP data, Astroquery data, Skyfield data, and Playwright data.
- Release manifest and required release files, including `release_manifest.txt`, `README.md`, `RELEASE_VALIDATION.md`, `requirements.txt`, and `VERSION.txt`.
- Release folder artifact hygiene, including `.bak`, `.patch`, `repair_*.ps1`, pytest cache, Python cache, and temporary repair files.
- EXE smoke-launch stability using an isolated `..\FZAstroAI_BUILD\smoke_appdata` directory through `FZASTRO_APP_DIR`.
- Optional GUI startup smoke coverage in pytest when PySide6 is installed.
- Hardware telemetry row remains compact when GPU, CPU, RAM, and available temperatures are displayed.
- LLM Benchmark Dashboard source imports and release resources remain available in the packaged app.

## 5. Manual release-candidate acceptance test

With the EXE open, confirm these items.

Ollama-specific checks:

1. With Ollama installed but stopped, launch the app and confirm the model selector refreshes into the installed Ollama model list.
2. With Ollama unavailable or auto-start disabled through `FZASTRO_AUTO_START_OLLAMA=0`, launch the app and confirm the model selector shows an `Ollama unavailable` status item without a long traceback.
3. Confirm the app remains usable and refresh can be retried after starting Ollama manually.
4. With Ollama already running before launch, set `FZASTRO_STOP_OLLAMA_ON_EXIT=1`, close the app, and confirm Ollama remains running.
5. With Ollama stopped before launch, set `FZASTRO_STOP_OLLAMA_ON_EXIT=1`, let the app auto-start Ollama, close the app, and confirm only that app-started Ollama process exits.

Main app checks:

1. About window shows `FZAstro AI v1.0.0 (Version 1 Release Candidate)`.
2. Clicking the **FZ** square in the header opens `https://github.com/Ghostaka1978/FZAstroAI` in the external browser.
3. Open App Data works.
4. Open Log works.
5. Model list refresh works.
6. A normal local chat response works.
7. Document import works.
8. Re-importing the same document reports a duplicate/update instead of creating duplicate library entries.
9. Clear Library removes indexed rows, clears document assets, and compacts `document_knowledge.sqlite3` plus WAL/SHM storage.
10. Document Q&A works.
10. Exact PDF page text retrieval works.
11. PDF page/image rendering works only when explicitly requested.
12. Daily News works.
13. Web mode works.
14. Composer toolbar Code, Paste Code, Actions, Context, Persona, and Clear controls work; prompt actions do not auto-send.
15. Python actions can insert explain/debug/refactor/test prompts; Run actions use the existing local Python execution path.
16. Smart routing sends obvious URL, document inventory/search/brief/page-image, and explicit Python-run requests to the correct app tool without a generic model answer.
17. Risky explicit Python execution asks for confirmation before running.
18. Python code-block Run button works.
19. Starting and cancelling/stopping a streamed chat response does not add `WinError 10038` traceback spam to the log.
20. Persistent memory review/search works.
21. Closing and reopening the EXE preserves history/settings.

LLM Benchmark checks:

1. **LLM BENCH** opens the LLM Benchmark Dashboard from the Quick Actions row.
2. The polished control layout fits without clipping: model, persona/calibration, benchmark preset, suite depth, repeat count, temperature, max tokens, compact custom prompt entry, and action buttons are readable.
3. The dialog model selector auto-refreshes/refreshes models from the configured endpoint, allows selecting a different benchmark model inside the dialog, and runs without changing the main chat model.
4. The persona/calibration selector includes Raw model, Active app persona, and installed calibration profiles; choosing a persona does not change the main app profile.
5. Dashboard, History, and Compare tabs use the dark app theme; the old dedicated Benchmark tab is not shown.
6. The telemetry row mirrors the main window GPU/VRAM and CPU/RAM labels while a benchmark is running or idle.
7. Benchmark preset list includes Quick Q&A, Math Reasoning, Code Generation, Creative Writing, Logical Reasoning, Data Analysis, Translation & Multilingual, Summarization, and Instruction Following.
8. **Run Selected** against Quick Q&A completes and fills tokens/sec, time to first token, total time, completion tokens, input tokens, accuracy score, trust score, quality score, deterministic grader evidence, telemetry snapshot, and model response.
9. **Run All Presets** executes the full built-in benchmark suite in one pass and records each preset separately in History.
10. Benchmark history persists after closing and reopening the dashboard.
11. Compare tab groups results by model + persona and sorts by composite score; coverage, accuracy, speed, trust, instruction following, throughput, latency, and stability are populated.
12. **Delete Selected** removes only the selected History row(s) after confirmation and updates Dashboard/Compare totals.
13. Export JSON writes `llm_benchmark_history.json` successfully, and Clear History removes all saved entries after confirmation.
14. Stop cancels an active benchmark without leaving the worker running.

Astro checks:

1. **Skills → Astro** exposes SITE, IMAGING, LOOKUP, SUN NOW, SEEING, TARGETS, and SOLAR MAP.
2. SITE opens the observing-site picker and saves latitude, longitude, elevation, timezone, and optional SQM/Bortle/source fields.
3. IMAGING opens camera/FOV setup and updates the toolbar summary.
4. LOOKUP opens its own compact dialog, keeps the migrated object dropdown catalogs available, and can query at least `M31`, `M82`, and `M101` without Gaia timeout.
5. LOOKUP renders object details, distance method, and sky preview inside the LOOKUP window instead of relying on the main chat.
6. SUN NOW opens its own window, displays at least one NASA/SDO channel, shows metadata, supports channel/size selection, and uses the cached image if the live feed is unavailable.
7. SOLAR MAP opens a native 2D interactive map window with zoom, pan, Full/Inner/Outer modes, orbit/label/grid toggles, planet labels, and a planet data table.
8. SEEING opens the Astro Night Planner in its own window and shows daily forecast cards for the available forecast period.
9. SEEING uses 7Timer ASTRO seeing/transparency, Moon periods, astronomical-dark periods, cloud/seeing/transparency gauges, and a Forecast Points table that prioritizes night/imaging rows over daytime rows.
10. SEEING can display SQM/Bortle from saved SITE values or a successful automatic LightPollutionMap.app lookup; if no reliable value exists, it should show Not set instead of a fake estimate.
11. Selecting SEEING forecast cards/rows updates the selected-hour details and dark/moon period panels without traceback errors.
12. TARGETS returns the best-target planner output without huge blank space at the bottom.
13. While the main chat is scrolled upward, LOOKUP, SEEING, TARGETS, SUN NOW, and SOLAR MAP do not force the main chat to auto-scroll to the bottom; standalone Astro tools should not post their primary UI output to main chat.
14. ASTRO LOOKUP/SEEING/TARGETS/SOLAR MAP do not log `Astropy runtime data fallback missing` from the PyInstaller `_MEI` runtime folder.

## 6. Document knowledge library verification

The document knowledge implementation is maintained in `fzastro_ai/knowledge_library.py`, not inline in `fzastro_ai/app.py`. Before release, run the focused regression tests:

```powershell
python -m pytest tests/test_knowledge_library.py -q
```

These tests cover text import/search/context behavior and duplicate import handling. Manual EXE validation must still cover PDF visual rendering, OCR availability messaging, and XLSX extraction because those depend on optional runtime packages and external tools.

## 7. Expected external dependencies

The EXE bundles the Python app through PyInstaller, but these tools are external system/runtime dependencies:

- Ollama and downloaded models. The app may auto-start an installed local Ollama server for `http://localhost:11434/v1`, but it does not install Ollama or pull models.
- Bundled Playwright Chromium, or installed Edge/Chrome fallback for browser-backed web capture.
- Tesseract OCR, if OCR is needed.
- A real local Python interpreter, if EXE Python execution or migrated ASTRO subprocess tools are needed.

For Python execution inside the EXE, set:

```powershell
$env:FZASTRO_PYTHON=".\.venv\Scripts\python.exe"
```

For portable/test runtime data, set:

```powershell
$env:FZASTRO_APP_DIR=".\.fzastro_appdata"
```

## 8. ASTRO EXE packaging/runtime validation

For the packaged EXE, the migrated ASTRO tools require two things:

1. The folder `fzastro_ai/astro_tools/fzastro` must be bundled by PyInstaller.
2. The EXE must be able to find a real Python environment with `astropy`, `astroquery`, `numpy`, `matplotlib`, and `skyfield` installed.

The build script packages the full FZASTRO tools folder. The validation script sets `FZASTRO_PYTHON` before launching the EXE so LOOKUP, SEEING, TARGETS, and SOLAR MAP use the selected working Python environment.

Manual ASTRO checks after launch:

- LOOKUP: query `M18`; verify the compact LOOKUP window displays the result text and sky preview.
- SUN NOW: open latest SDO AIA 171 or HMI Magnetogram image; verify metadata and cached fallback messaging.
- SEEING: open the default site forecast; verify daily cards, night-first Forecast Points, Moon periods, astronomical-dark periods, selected-hour details, and SQM/Bortle handling.
- SITE/SQM: save manual SQM/Bortle values, then reopen SEEING and confirm they display; if testing automatic lookup, confirm failures are shown as unavailable rather than guessed values.
- TARGETS: default site target planner.
- SOLAR MAP: native 2D map window, zoom/pan, Full/Inner/Outer modes, labels/orbits/grid toggles, planet table.
- Main chat scroll preservation: scroll upward first, then run LOOKUP, SEEING, TARGETS, SUN NOW, and SOLAR MAP. Standalone Astro windows must not force the main chat to the bottom or post their primary UI output to chat.
- Astropy runtime data: check the app log after LOOKUP. There should be no `_MEI.../fzastro_ai/resources/astropy_icon.png` fallback-missing warning.

## 9. Quiet native command logging

Native command output is captured through Start-Process redirect files instead of PowerShell stream redirection. This prevents successful tools such as Black from appearing as `NativeCommandError` messages when they print status text. Use `-VerboseOutput` only when you want the captured output echoed to the console.

Build environment note: the scripts set the project root on `PYTHONPATH`, use the resolved `.venv` interpreter, and set `FZASTRO_PYTHON` before tests, build, validation, and EXE launch.

## 10. GUI startup smoke test

The pytest suite contains a GUI startup smoke test that is skipped when PySide6 is not installed. On the Windows release environment it sets `FZASTRO_DISABLE_STARTUP_GPU_MONITOR=1`, constructs the main window, confirms the editable prompt is populated, closes the window, and processes pending Qt events. This keeps the test focused on startup/shutdown safety rather than GPU telemetry.

## 11. Release artifact hygiene check

Release validation checks that development/repair artifacts are not present in the packaged release output.

Development/repair artifacts include `.bak`, `.patch`, `repair_*.ps1`, pytest cache data, Python cache directories, debug files, and temporary repair files. These files may be useful while fixing the application, but they must not ship in release bundles.

## 12. Release verdict rule

The release candidate can be marked complete when:

- Black formatting check completes without failures.
- `python -m pytest` completes without failures.
- `build_exe.ps1` completes without errors.
- `validate_release.ps1` completes without fatal errors.
- The EXE remains open during the smoke test.
- The manual acceptance checklist passes, including the LLM Benchmark Dashboard checks and the Astro LOOKUP, SUN NOW, SOLAR MAP, and SEEING Night Planner checks.
- The About window shows the correct Version 1 version and milestone.
