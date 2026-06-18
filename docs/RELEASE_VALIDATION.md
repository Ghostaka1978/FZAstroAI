# FZAstro AI v2.3.1 Imaging Production Build and Validation

This file is the production release checklist for **FZAstro AI v2.3.1 - Imaging Production**.

A build can be marked production-ready only after automated tests, release validation, and manual acceptance checks pass on the target Windows machine.

GitHub repository: `https://github.com/Ghostaka1978/FZAstroAI`.

## 1. Recreate or activate the Python 3.11 environment

`scripts/reset_venv.ps1` recreates the Python 3.11 virtual environment and sets up the expected release baseline.

Release builds require Python 3.11. Do not use Python 3.14 for production release builds.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\reset_venv.ps1 -Force
. .\scripts\activate_venv.ps1
```

Manual equivalent:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`scripts/activate_venv.ps1` sets `FZASTRO_PYTHON`, `FZASTRO_PROJECT_ROOT`, and `FZASTRO_BUILD_ROOT`. By default, build output is created one folder above the project root under `..\FZAstroAI_BUILD`.

Optional browser install for Playwright-backed web features:

```powershell
python -m playwright install chromium
```

## 2. Format and test before building

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\format_code.ps1 -PythonExe ".\.venv\Scripts\python.exe"
python -m pytest
```

For CI/release verification:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\format_code.ps1 -PythonExe ".\.venv\Scripts\python.exe" -Check
```

## 3. Deploy with the one-command workflow

Recommended root deploy button:

```powershell
.\DEPLOY.bat
```

`DEPLOY.bat` runs `scripts/deploy.ps1 -RunValidation -GitRelease`. After a successful build and validation, it stages the release changes, creates a local release commit, and creates the annotated tag from `VERSION.txt` (`v2.3.1` for this release).

To also push the current branch and tag:

```powershell
.\DEPLOY.bat -GitPush
```

Script-only equivalent:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1 -RunValidation -GitRelease
powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1 -RunValidation -GitRelease -GitPush
```

`scripts/deploy.ps1` is the scripted release workflow command. It calls `scripts/clean_build.ps1`, and `scripts/clean_build.ps1` starts `build_exe.ps1` automatically after cleaning previous build/cache output. Use `-RunValidation` for non-interactive validation; otherwise the build script displays a validation prompt asking whether to run `validate_release.ps1` immediately.

The deploy/build/validation scripts use a quiet progress display by default. They show a progress bar and the current cleanup, build, and validation stage while sending noisy pip, pytest, Black, and PyInstaller output to `..\FZAstroAI_BUILD\logs`. Use `-VerboseOutput` when full live command output is needed.

Git release flags:

- `-GitRelease` stages release changes, creates a commit, and creates the tag from `VERSION.txt`.
- `-GitTag v2.3.1` overrides the default tag if needed.
- `-GitCommitMessage "Release FZAstro AI v2.3.1"` overrides the default commit message.
- `-GitPush` pushes the current branch and tag to `origin` after the local commit/tag.
- `-GitRemote` and `-GitBranch` can override the push target.

To run the build without the cleaning wrapper:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1 -PythonExe ".\.venv\Scripts\python.exe"
```

Release output should be created here:

```text
..\FZAstroAI_BUILD\release\FZAstroAI.exe
```

The release folder includes `FZAstroAI.exe`, `README.md`, `RELEASE_VALIDATION.md`, `OFFLINE_VOICE_COMMANDS.md`, `install_offline_voice.ps1`, `requirements.txt`, `VERSION.txt`, and `release_manifest.txt` with the EXE size and SHA256 hash.

## 4. Automated validation

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\validate_release.ps1 -PythonExe ".\.venv\Scripts\python.exe" -SkipLaunch
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
- Confirm the title/about identity is `FZAstro AI v2.3.1 (Imaging Production)`.
- Confirm normal chat works with the configured Ollama/OpenAI-compatible endpoint.
- Confirm source chips still appear for LLM, Docs, Web, Files, Python, Memory, News, Market, and App workflows.
- Confirm the app closes cleanly without worker shutdown errors.

### Documentation/help/about

- Help and About should describe v2.3.1, not RC3 or older v2.1 text as the current release.
- Root should contain one primary `README.md`; detailed docs should live under `docs/`.
- Root should expose one easy deploy button, `DEPLOY.bat`; PowerShell workflow logic should remain under `scripts/`.
- Root should not contain stale installer/runtime leftovers such as `Codex Installer.exe`, `Microsoft.Services.Store.winmd`, or `DELETE_THESE_FILES.txt`.
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

### FZAstro Imaging / N.I.N.A. planning

- Confirm `bundled_apps/FZAstroImaging/FZAstroImaging.exe`, `NINA.exe`, and `NINA.dll` are present on the release machine when testing the bundled imaging runtime.
- Confirm `external/` and `bundled_apps/` are intentionally omitted from normal source handoff ZIPs.
- Open **ASTRO → FZASTRO IMAGING CONTROL**.
- Confirm the Imaging Control panel uses uppercase action labels and a clear review-only safety message.
- Click **PLAN NEXT TARGET** and verify a plan folder is created under `Documents\FZAstroAI\Imaging Plans`.
- Run `/nina-plan target M13 60s gain 200` from chat.
- Confirm the generated `.nina-sequence.json` contains target name, RA/Dec, exposure, gain, and frame count.
- Confirm FZAstro launches/opens FZAstro Imaging for review when possible.
- Confirm FZAstro does not slew, center, guide, autofocus, capture, start a sequence, or schedule hardware execution automatically.

### Web Companion

- Start local mode:

```powershell
.\scripts\run_web_companion.ps1 -Port 7860
```

- Start LAN/iPad mode:

```powershell
.\scripts\run_web_companion.ps1 -Lan -Port 7860 -Token "fzastro"
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
.\DEPLOY.bat
.\DEPLOY.bat -GitPush
```

Manual fallback if needed:

```powershell
git status --short
git add -A -- .
git commit -m "Release FZAstro AI v2.3.1"
git tag -a v2.3.1 -m "FZAstro AI v2.3.1"
git push origin main
git push origin v2.3.1
```


See also: `docs/SCRIPTS.md` for the consolidated PowerShell script folder layout.
