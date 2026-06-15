# FZAstro AI v1.0.0 Version 1 Release Candidate Build and Validation

This file is the Windows build and validation checklist for **FZAstro AI v1.0.0 — Version 1 Release Candidate**.

Do not call a build production until the automated tests, validation script, and manual acceptance checklist pass on the target machine.

## 1. Recreate/activate the Python 3.11 environment

The release workflow requires Python 3.11. Recreate `.venv` before release builds if there is any chance it was made with Python 3.14 or another version:

```powershell
powershell -ExecutionPolicy Bypass -File .\reset_venv.ps1 -Force

Important: run `reset_venv.ps1` from a normal PowerShell session, not while `(.venv)` is active. If the prompt already shows `(.venv)`, run `deactivate`, close the terminal, open a fresh PowerShell in the project folder, then run the reset command. This avoids Windows locking `.venv\Scripts\python.exe` during deletion.

. .\activate_venv.ps1
```

The scripts enforce Python 3.11 and stop with a clear error if another interpreter is selected.

## 2. Open PowerShell in the project folder

```powershell
cd <project-root>
```

## 2. Install dependencies and activate the venv

```powershell
python -m venv .venv
. .\activate_venv.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`activate_venv.ps1` activates `.venv` in the current shell and sets `FZASTRO_PYTHON` to `.venv\Scripts\python.exe`, sets `FZASTRO_BUILD_ROOT` to the sibling `..\FZAstroAI_BUILD` folder, and updates the current shell environment for the build/validation tools.

Optional browser install for Playwright-backed web features:

```powershell
python -m playwright install chromium
```

Release builds install the browser package-locally through `build_exe.ps1` so
PyInstaller can bundle it. If that bundled browser is unavailable at runtime,
the app falls back to installed Microsoft Edge or Google Chrome.

## 3. Format source code

Run Black before testing and building:

```powershell
powershell -ExecutionPolicy Bypass -File .\format_code.ps1 -PythonExe ".\.venv\Scripts\python.exe"
```

For CI/release verification, use check mode:

```powershell
powershell -ExecutionPolicy Bypass -File .\format_code.ps1 -PythonExe ".\.venv\Scripts\python.exe" -Check
```

The build script also runs Black before compiling and testing unless `-SkipFormat` is passed.

## 4. Run automated tests

```powershell
python -m pytest
```

The release candidate should not proceed if these tests fail.

## 5. Deploy with the one-command workflow

Recommended command for the current development machine:

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy.ps1
```

`deploy.ps1` is the single release workflow command. It calls `clean_build.ps1`, which removes previous build/cache output, then starts `build_exe.ps1` automatically. At the end of a successful build, the build script displays a validation prompt asking whether to run `validate_release.ps1` immediately.

By default, build output is created one folder above the project root in `..\FZAstroAI_BUILD`. The scripts also set `FZASTRO_PROJECT_ROOT`, `FZASTRO_BUILD_ROOT`, `FZASTRO_PYTHON`, and, when using `.venv`, `VIRTUAL_ENV`/`PATH` for child build and validation commands.

The deploy/build/validation scripts use a quiet progress display by default. They show a progress bar and the current cleanup/build/validation stage while sending noisy pip, pytest, Black, and PyInstaller output to `..\FZAstroAI_BUILD\logs\`. Use `-VerboseOutput` on `deploy.ps1`, `build_exe.ps1`, or `validate_release.ps1` when you want full live command output.

The scripts create the log folder automatically before writing log files.

To run the build without the cleaning wrapper:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1 -PythonExe ".\.venv\Scripts\python.exe"
```

The build output should be created here:

```text
..\FZAstroAI_BUILD\release\FZAstroAI.exe
```

The release folder also includes a `release_manifest.txt` with the EXE size and SHA256 hash. Validation requires this release manifest and checks that the release folder contains the expected EXE, `README.md`, `requirements.txt`, and `VERSION.txt` files.

## 6. Validate the EXE

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\validate_release.ps1 -PythonExe ".\.venv\Scripts\python.exe" -ExePath "..\FZAstroAI_BUILD\release\FZAstroAI.exe" -KeepRunning
```

This checks:

- EXE exists
- SHA256 hash can be calculated
- `VERSION.txt` reports the Version 1 release version
- Black formatting check passes
- Source code compiles
- Automated tests pass
- Critical Python imports work
- Ollama availability, including clear unavailable status when local Ollama cannot be reached
- Ollama auto-start behavior for an installed but stopped local server
- Optional owned Ollama stop-on-exit behavior through `FZASTRO_STOP_OLLAMA_ON_EXIT=1`
- Tesseract availability
- Playwright Chromium availability or installed Edge/Chrome fallback
- PyInstaller resource configuration markers for bundled icons, astronomy tools, Astropy/SAMP data, Astroquery data, and Skyfield data
- Release manifest and required release files, including `release_manifest.txt`, `README.md`, `requirements.txt`, and `VERSION.txt`
- Release folder artifact hygiene, including `.bak`, `.patch`, and `repair_*.ps1` files
- EXE smoke-launch stability using an isolated `..\FZAstroAI_BUILD\smoke_appdata` directory through `FZASTRO_APP_DIR`
- Optional GUI startup smoke coverage in pytest when PySide6 is installed
- Hardware telemetry row remains compact when GPU, CPU, RAM, and available temperatures are displayed

## 7. Manual release-candidate acceptance test

With the EXE open, confirm:

Ollama-specific checks:

1. With Ollama installed but stopped, launch the app and confirm the model selector refreshes into the installed Ollama model list.
2. With Ollama unavailable or auto-start disabled through `FZASTRO_AUTO_START_OLLAMA=0`, launch the app and confirm the model selector shows an `Ollama unavailable` status item without a long traceback.
3. Confirm the app remains usable and refresh can be retried after starting Ollama manually.
4. With Ollama already running before launch, set `FZASTRO_STOP_OLLAMA_ON_EXIT=1`, close the app, and confirm Ollama remains running.
5. With Ollama stopped before launch, set `FZASTRO_STOP_OLLAMA_ON_EXIT=1`, let the app auto-start Ollama, close the app, and confirm only that app-started Ollama process exits.

1. About window shows `FZAstro AI v1.0.0 (Version 1 Release Candidate)`.
2. Open App Data works.
3. Open Log works.
4. Model list refresh works.
5. A normal local chat response works.
6. Document import works.
7. Re-importing the same document reports a duplicate/update instead of creating duplicate library entries.
8. Clear Library removes indexed rows, clears document assets, and compacts `document_knowledge.sqlite3` plus WAL/SHM storage.
9. Document Q&A works.
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
22. Astro toolbar shows `ASTRO TOOLS   SITE   IMAGING   LOOKUP   SEEING   TARGETS   SOLAR MAP`.
23. SITE opens the observing-site picker and saves latitude, longitude, elevation, and timezone.
24. IMAGING opens camera/FOV setup and updates the toolbar summary.
25. LOOKUP opens the migrated object dropdown catalogs and can query at least `M31`, `M82`, and `M101` without Gaia timeout.
26. SEEING returns night meteorology/seeing output without huge blank space at the bottom.
27. TARGETS returns the best-target planner output without huge blank space at the bottom.
28. SOLAR MAP renders the solar-system map and the button label is not clipped.
29. While the main chat is scrolled upward, LOOKUP, SEEING, TARGETS, and SOLAR MAP finish without forcing the main chat to auto-scroll to the bottom.
30. ASTRO LOOKUP/SEEING/TARGETS/SOLAR MAP do not log `Astropy runtime data fallback missing` from the PyInstaller `_MEI` runtime folder.


## Document knowledge library verification

The document knowledge implementation is maintained in `fzastro_ai/knowledge_library.py`, not inline in `fzastro_ai/app.py`. Before release, run the focused regression tests:

```powershell
python -m pytest tests/test_knowledge_library.py -q
```

These tests cover text import/search/context behavior and duplicate import handling. Manual EXE validation must still cover PDF visual rendering, OCR availability messaging, and XLSX extraction because those depend on optional runtime packages and external tools.

## 8. Expected external dependencies

The EXE bundles the Python app through PyInstaller, but these tools are external system/runtime dependencies:

- Ollama and downloaded models. The app may auto-start an installed local Ollama server for `http://localhost:11434/v1`, but it does not install Ollama or pull models.
- Bundled Playwright Chromium, or installed Edge/Chrome fallback for browser-backed web capture
- Tesseract OCR, if OCR is needed
- A real local Python interpreter, if EXE Python execution is needed

For Python execution inside the EXE, set:

```powershell
$env:FZASTRO_PYTHON=".\.venv\Scripts\python.exe"
```

For portable/test runtime data, set:

```powershell
$env:FZASTRO_APP_DIR=".\.fzastro_appdata"
```

## 9. Release verdict rule

The release candidate can be marked complete when:

- Black formatting check completes without failures
- `python -m pytest` completes without failures
- `build_exe.ps1` completes without errors
- `validate_release.ps1` completes without fatal errors
- The EXE remains open during the smoke test
- The manual acceptance checklist passes
- The About window shows the correct Version 1 version and milestone

## ASTRO EXE packaging/runtime validation

For the packaged EXE, the migrated ASTRO tools require two things:

1. The folder `fzastro_ai/astro_tools/fzastro` must be bundled by PyInstaller.
2. The EXE must be able to find a real Python environment with `astropy`, `astroquery`, `numpy`, `matplotlib`, and `skyfield` installed.

The build script packages the full FZASTRO tools folder. The validation script sets `FZASTRO_PYTHON` before launching the EXE so LOOKUP, SEEING, TARGETS, and SOLAR MAP use the selected working Python environment.

Recommended validation command:

```powershell
powershell -ExecutionPolicy Bypass -File .\validate_release.ps1 -PythonExe ".\.venv\Scripts\python.exe" -ExePath "..\FZAstroAI_BUILD\release\FZAstroAI.exe" -KeepRunning
```

Manual ASTRO checks after launch:

- LOOKUP: `M18`
- SEEING: default site forecast
- TARGETS: default site target planner
- SOLAR MAP: image render
- Main chat scroll preservation: scroll upward first, then run LOOKUP, SEEING, TARGETS, and SOLAR MAP. Results must not force the main chat to the bottom.
- Astropy runtime data: check the app log after LOOKUP. There should be no `_MEI.../fzastro_ai/resources/astropy_icon.png` fallback-missing warning.


### Quiet native command logging

Native command output is captured through Start-Process redirect files instead of PowerShell stream redirection. This prevents successful tools such as Black from appearing as `NativeCommandError` messages when they print status text. Use `-VerboseOutput` only when you want the captured output echoed to the console.


Build environment note: the scripts set the project root on `PYTHONPATH`, use the resolved `.venv` interpreter, and set `FZASTRO_PYTHON` before tests, build, validation, and EXE launch.

## GUI startup smoke test

The pytest suite contains a GUI startup smoke test that is skipped when PySide6 is not installed. On the Windows release environment it sets `FZASTRO_DISABLE_STARTUP_GPU_MONITOR=1`, constructs the main window, confirms the editable prompt is populated, closes the window, and processes pending Qt events. This keeps the test focused on startup/shutdown safety rather than GPU telemetry.

## Python 3.11 release environment

Release validation requires Python 3.11. Do not use Python 3.14 or another non-3.11 interpreter for release builds.

The release scripts enforce this requirement with `Get-PythonVersionInfo` and `Assert-Python311`. If `.venv` was created with the wrong interpreter, run:

```powershell
.\reset_venv.ps1
```

Manual equivalent:

```powershell
py -3.11 -m venv .venv
```

The workflow may also look for `python3.11`, and the selected interpreter is exposed through `FZASTRO_PYTHON` during tests, build, validation, and EXE launch.

## Release artifact hygiene check

Release validation checks that development/repair artifacts are not present in the packaged release output.

Development/repair artifacts include `.bak`, `.patch`, `repair_*.ps1`, pytest cache data, Python cache directories, debug files, and temporary repair files. These files may be useful while fixing the application, but they must not ship in release bundles.
