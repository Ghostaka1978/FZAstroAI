# FZAstro AI v2.0.0 Production Build and Validation

This file is the production release checklist for **FZAstro AI v2.0.0 — Version 2 Production**.

A build can be marked production-ready only after automated tests, release validation, and manual acceptance checks pass on the target Windows machine.

GitHub repository: `https://github.com/Ghostaka1978/FZAstroAI`.

## 1. Recreate or activate the Python 3.11 environment

`reset_venv.ps1` recreates the Python 3.11 virtual environment and sets up the expected release baseline.

Release builds require Python 3.11. Do not use Python 3.14 for production release builds.

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

`activate_venv.ps1` sets `FZASTRO_PYTHON`, `FZASTRO_PROJECT_ROOT`, and `FZASTRO_BUILD_ROOT`. By default, build output is created one folder above the project root under `..\FZAstroAI_BUILD`.

Optional browser install for Playwright-backed web features:

```powershell
python -m playwright install chromium
```

## 2. Format and test before building

```powershell
powershell -ExecutionPolicy Bypass -File .\format_code.ps1 -PythonExe ".\.venv\Scripts\python.exe"
python -m pytest
```

For CI/release verification:

```powershell
powershell -ExecutionPolicy Bypass -File .\format_code.ps1 -PythonExe ".\.venv\Scripts\python.exe" -Check
```

## 3. Deploy with the one-command workflow

Recommended command:

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy.ps1
```

`deploy.ps1` is the single release workflow command. It calls `clean_build.ps1`, and `clean_build.ps1` starts `build_exe.ps1` automatically after cleaning previous build/cache output. At the end of a successful build, the build script displays a validation prompt asking whether to run `validate_release.ps1` immediately.

The deploy/build/validation scripts use a quiet progress display by default. They show a progress bar and the current cleanup, build, and validation stage while sending noisy pip, pytest, Black, and PyInstaller output to `..\FZAstroAI_BUILD\logs`. Use `-VerboseOutput` when full live command output is needed.

To run the build without the cleaning wrapper:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1 -PythonExe ".\.venv\Scripts\python.exe"
```

Release output should be created here:

```text
..\FZAstroAI_BUILD\release\FZAstroAI.exe
```

The release folder includes `FZAstroAI.exe`, `README.md`, `RELEASE_VALIDATION.md`, `OFFLINE_VOICE_COMMANDS.md`, `install_offline_voice.ps1`, `requirements.txt`, `VERSION.txt`, and `release_manifest.txt` with the EXE size and SHA256 hash.

## 4. Automated validation

```powershell
powershell -ExecutionPolicy Bypass -File .\validate_release.ps1 -PythonExe ".\.venv\Scripts\python.exe" -SkipLaunch
```

Validation should check:

- Release manifest and required release files
- EXE existence, size, and hash
- Source tree hygiene: no `overlay/`, no `__pycache__`, no `.pyc`, no stale `.bak` patch files in the source package
- Release artifact hygiene: no development/repair artifacts such as `.bak`, `.patch`, or `repair_*.ps1` files in the final release folder
- Version constants: `VERSION.txt`, `fzastro_ai.__version__`, and `APP_VERSION`
- Required Web Companion files and static UI packaging
- PyInstaller resource configuration for packaged static/assets/data files
- Isolated `smoke_appdata` launch state for GUI smoke checks
- Optional GUI smoke launch test when `-SkipLaunch` is not used

## 5. Manual acceptance checklist

### Desktop app

- Launch `FZAstroAI.exe`.
- Confirm the title/about identity is `FZAstro AI v2.0.0 (Version 2 Production)`.
- Confirm normal chat works with the configured Ollama/OpenAI-compatible endpoint.
- Confirm source chips still appear for LLM, Docs, Web, Files, Python, Memory, News, Market, and App workflows.
- Confirm the app closes cleanly without worker shutdown errors.

### Documentation/help/about

- Help and About should describe v2.0.0, not RC3 as the current release.
- Root should contain one primary `README.md`; detailed docs should live under `docs/`.
- The separate `overlay/` folder should not exist.
- Stale bundle readmes should not exist in the root.

### LLM Benchmark checks

- Open **Skills → Model Lab → LLM Benchmark**.
- Confirm the polished control layout shows Dashboard, History, and Compare areas.
- Confirm telemetry appears in the benchmark dashboard.
- Confirm model selection can target a different model than the main chat when needed.
- Run a small benchmark.
- Confirm `Run All Presets`, `Delete Selected`, persona/calibration options, Composite scoring, and history/compare behavior work.
- The legacy `LLM BENCH` wording may remain in docs only for validation continuity.

### Astro Tools Suite

Confirm **SITE, IMAGING, LOOKUP, SUN NOW, SEEING, TARGETS, and SOLAR MAP** work as production windows.

- SITE stores observing site, elevation, timezone, SQM, Bortle, and source notes.
- IMAGING stores camera preset, focal length, FOV, image size, and rotation.
- LOOKUP opens object details and distance-ladder details for parallax, Gaia proxy, NED-D, and Hubble estimates where available.
- `FZASTRO_USE_DISTANCE_LADDER=1` exposes optional distance-ladder calculation visibility.
- SUN NOW displays NASA/SDO imagery with metadata/cached fallback.
- SEEING uses current/tonight context, astronomical-dark prioritization, Moon periods, cloud-aware scoring, and Bortle tint.
- Bortle tint rules: `8–9 white/urban`, `6–7 yellow`, `4–5 green`, `2–3 blue`, and `1 violet`.
- TARGETS ranks targets, exports CSV, and can use local OpenNGC import.
- SOLAR MAP zoom/pan/orbit/label/grid controls work.
- Astropy/IERS and provider timeouts should log warnings rather than crash workflows.

### Web Companion

- Start local mode:

```powershell
.\run_web_companion.ps1 -Port 7860
```

- Start LAN/iPad mode:

```powershell
.\run_web_companion.ps1 -Lan -Port 7860 -Token "fzastro"
```

- Confirm `FZASTRO_WEB_TOKEN` is required in LAN mode.
- Confirm the desktop exposes Web Companion controls, `Start Local Web Server`, `Start LAN / iPad Mode`, `Copy LAN/iPad URL`, and `Auto-start local server with desktop`.
- Confirm the web UI shows the control-panel, hidden advanced runtime area, Daily News Brief, and Astro Tools toolbar.
- Confirm `with_image: true`, `/api/news/daily`, `/api/assets/file`, and image asset serving work.

### AI Developer Workbench

- Click **DEV** in the quick actions bar.
- Scan the project root.
- Enter a coding request and build context + plan.
- Confirm selected files and plan are relevant.
- Run compile check.
- Run pytest or a targeted test group.
- Confirm failures are summarized rather than silently ignored.
- Confirm patch work remains review-first and backed up.

## 6. Git release commands

```powershell
git status --short
git add .
git commit -m "Prepare FZAstro AI v2.0.0 production cleanup"
git tag -a v2.0.0 -m "FZAstro AI v2.0.0"
git push origin main
git push origin v2.0.0
```
