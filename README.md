# FZAstro AI v2.1.0

FZAstro AI v2.1.0 is a Windows PySide6 desktop AI workstation for astrophotography, local LLM workflows, document research, web/news/market tools, local Python execution, hardware telemetry, LLM benchmarking, and integrated astronomy planning.

Version 2.1 is the Imaging Production release: it keeps the cleaned Version 2 production tree and adds the first safe Astro → FZAstro Imaging/N.I.N.A. planning bridge, real Advanced Sequencer JSON export, auto-launch/open handoff, and a polished imaging control panel.

The **FZ** square in the app header opens the project GitHub repository: `https://github.com/Ghostaka1978/FZAstroAI`.

## Version 2.1 focus

- Clean source layout: application code lives under `fzastro_ai/`; root keeps launch, build, validation, version, and top-level docs only.
- `overlay/` has been removed as a separate folder. The useful Developer Workbench pieces are now integrated under `fzastro_ai/dev_agent`, `fzastro_ai/ui/dev_workbench_dialog.py`, and `fzastro_ai/actions/dev_actions.py`.
- Stale bundle/patch readmes were removed or consolidated into `docs/`.
- The app identity is now `FZAstro AI v2.1.0 (Imaging Production)`.
- Build hygiene removes `__pycache__`, `.pyc`, `.bak`, and old overlay artifacts from the source package.
- The standalone PyInstaller spec was cleaned so Web Companion static files are included safely.

## What FZAstro AI does

FZAstro AI provides one local workstation for:

- Local/Ollama or OpenAI-compatible chat
- Document Knowledge Library for PDFs, text, source code, and Excel documents
- Exact PDF page text retrieval and visual page/image rendering when needed
- Optional OCR for scanned document pages
- Web search, webpage reading, webpage screenshots, Daily News, market quotes, gold, and crude-oil actions
- Local Python execution from chat/code workflows
- Persistent memory with review/search tools
- Source tags: LLM, Docs, Web, News, Market, Files, Vision, Python, Memory, and App
- Hardware telemetry for GPU/VRAM, CPU, RAM, and best-effort temperatures
- LLM Benchmark Dashboard with dashboard/history/compare views, telemetry, persona/calibration options, `Run All Presets`, `Delete Selected`, and the legacy `LLM BENCH` wording for release validation
- Web Companion browser interface for LAN/iPad/mobile access to the Windows host
- Integrated Astro Tools Suite
- AI Developer Workbench for coding context, planning, compile checks, pytest checks, and safe patch workflows
- FZAstro Imaging / N.I.N.A. bundle launcher with safe update-check/download workflow
- Safe predefined imaging commands that create review-only N.I.N.A. Advanced Sequencer plans from SITE, IMAGING, SEEING, and TARGETS context
- Real `.nina-sequence.json` export, plus Markdown, XML, CSV, and review metadata files under `Documents\FZAstroAI\Imaging Plans`
- Optional launch/open handoff that opens FZAstro Imaging and attempts to load the generated sequence without starting hardware actions

## Astro Tools Suite

Use **Skills → Astro** or the Astro toolbar for the production astronomy tools:

`SITE, IMAGING, LOOKUP, SUN NOW, SEEING, TARGETS, and SOLAR MAP`

Highlights:

- **SITE** stores observing coordinates, elevation, timezone, SQM, Bortle, and source notes.
- **IMAGING** stores camera preset, focal length, field of view, image size, and rotation.
- **LOOKUP** searches catalog objects and can show distance-ladder calculations using parallax, Gaia proxy, NED-D, and Hubble-style estimates where available. Optional visibility: `FZASTRO_USE_DISTANCE_LADDER=1`.

Distance ladder calculations are documented for LOOKUP so release checks can verify parallax, Gaia, NED-D, Hubble, and `FZASTRO_USE_DISTANCE_LADDER` coverage.

- **SUN NOW** shows NASA/SDO solar imagery with metadata and cached fallback.
- **SEEING / Astro Night Planner** uses night-first forecast points, astronomical-dark prioritization, Moon periods, cloud-aware scoring, and Bortle-aware tinting.
- **TARGETS** ranks astrophotography targets by site/date and supports CSV export plus optional local OpenNGC import.
- **SOLAR MAP** shows a native 2D solar-system map with zoom, pan, orbit/label/grid toggles, and planet data.

Bortle tint rules remain: `8–9 white/urban`, `6–7 yellow`, `4–5 green`, `2–3 blue`, and `1 violet`.

Astropy/IERS and web provider timeouts are hardened so malformed upstream tables or provider-timeout failures are logged instead of crashing normal workflows.

See `docs/ASTRO_TOOLS_SUITE.md` for the focused astronomy guide.


## FZAstro Imaging / N.I.N.A. Bundle

Open the imaging-control bundle with the **N.I.N.A.** button in the top bar or with **ASTRO → FZASTRO IMAGING CONTROL**. This integration keeps the N.I.N.A.-based app as a side-by-side executable instead of merging C# source into the Python package.

Current scope:

- Build, select, or auto-detect the bundled `FZAstroImaging.exe`
- Preserve the internal N.I.N.A. WPF assembly names: `NINA.exe` and `NINA.dll` remain in the bundle
- Launch the imaging app from FZAstro AI
- Store local integration settings in `%APPDATA%\FZAstroAI\nina_integration.json`
- Configure localhost API host/port for the later control bridge
- Check a configured update manifest or GitHub latest-release API URL
- Download update packages for review without replacing a running equipment-control app
- Quietly build the imaging bundle from N.I.N.A. source with progress/logs through `deploy.ps1 -BuildImagingBundle`

## Safe Astro → Imaging planning

FZAstro AI v2.1 adds a review-first planning bridge between the Astro Tools Suite and FZAstro Imaging/N.I.N.A.

Supported text commands include:

```text
/nina-plan next
/nina-plan next 60s gain 200
/nina-plan target M13 60s gain 200
/imaging-plan target NGC 7000 exposure 120s gain 100 frames 80
```

The ASTRO menu and FZAstro Imaging Control panel also expose uppercase production actions:

```text
PLAN NEXT TARGET
PLAN SPECIFIC TARGET
OPEN LATEST PLAN IN IMAGING
OPEN PLANS FOLDER
FZASTRO IMAGING CONTROL
```

Generated plans are stored in a readable per-plan folder:

```text
Documents\FZAstroAI\Imaging Plans\<plan_id>\
```

Each plan creates:

- `<plan>.nina-sequence.json` — real N.I.N.A. Advanced Sequencer JSON filled from the saved OSC template
- `<plan>.nina-plan.xml` — review/helper XML
- `<plan>.nina-target.csv` — target/sequence review helper
- `<plan>.nina-review.json` — FZAstro review metadata
- `<plan>.json` — FZAstro internal metadata
- `<plan>.md` — readable summary

FZAstro can launch the bundled imaging app and attempt to open the generated `.nina-sequence.json` for review. The safety boundary remains strict: FZAstro does **not** slew, center, start guiding, run autofocus, start capture, start a sequence, or schedule hardware execution automatically.

See `docs/NINA_BUNDLE_INTEGRATION.md` for the bundle/update/planning workflow.

## AI Developer Workbench

Open the new Developer Workbench with the **DEV** button in the quick actions bar.

Current scope:

- Project scanner that ignores generated caches, backups, build output, and runtime data
- Task classifier for patch/test/release/ask requests
- Relevant-file context builder
- Visible implementation-plan generator
- Failure-output analyzer for pytest/traceback output
- Compile and pytest runner helpers
- Safe patch snapshot primitives
- Review-first UI; it prepares context and validation rather than silently editing files

See `docs/AI_DEVELOPER_WORKBENCH.md` for details.

## Web Companion

The Web Companion lets the Windows desktop app expose a local browser interface for the same PC, iPad, phone, Mac, or another LAN device.

Typical LAN command:

```powershell
.\scripts\run_web_companion.ps1 -Lan -Port 7860 -Token "fzastro"
```

Open from another device:

```text
http://YOUR-PC-LAN-IP:7860/
```

Set `FZASTRO_WEB_TOKEN` for LAN mode and do not expose this directly to the public internet.

See `docs/WEB_COMPANION.md` for the full LAN/mobile workflow.

## Project structure

```text
fzastro_ai/                 Application package
fzastro_ai/actions/         Main-window action mixins
fzastro_ai/astro_tools/     Astronomy engines, migrated FZASTRO tools, planners
fzastro_ai/dev_agent/       AI Developer Workbench backend
fzastro_ai/ui/              PySide6 dialogs/widgets/windows
fzastro_ai/web_companion/   Local browser companion server and static UI
fzastro_ai/workers/         Background worker classes
tests/                      Automated tests
docs/                       Consolidated detailed documentation
scripts/                    PowerShell build, validation, setup, and utility scripts
main.py                     Desktop/Web Companion entry point
VERSION.txt                 Release version
```

## Development setup

Use Python 3.11 on Windows for release builds. Do not use Python 3.14 for release builds; the scripts enforce Python 3.11 so dependency and PyInstaller behavior stay predictable.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\reset_venv.ps1 -Force
. .\scripts\activate_venv.ps1
python -m pytest
```

Launch from source:

```powershell
python main.py
```

## Build and validation

Recommended one-command workflow:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1
```

`scripts/deploy.ps1` calls `scripts/clean_build.ps1`; `scripts/clean_build.ps1` starts `build_exe.ps1` automatically. The workflow uses a progress bar for cleanup, build, and validation stages, logs noisy subprocess output under `..\FZAstroAI_BUILD\logs`, and supports `-VerboseOutput` when full live command output is needed.

The default build folder is one folder above the project root:

```text
..\FZAstroAI_BUILD
```

`scripts/activate_venv.ps1` sets `FZASTRO_PROJECT_ROOT`, `FZASTRO_BUILD_ROOT`, and `FZASTRO_PYTHON` for child commands.

After a successful build, the script can show a validation prompt to run `scripts/validate_release.ps1`.

## Release validation hygiene notes

Release validation checks development/repair artifacts such as `.bak`, `.patch`, and `repair_*.ps1` files so they do not leak into the release package. It checks the release manifest, PyInstaller resource configuration, isolated `smoke_appdata`, and GUI smoke / GUI startup behavior.

## Detailed docs

- `docs/RELEASE_VALIDATION.md` — production build/validation checklist
- `docs/PROJECT_OVERVIEW.md` — concise architecture summary
- `docs/ASTRO_TOOLS_SUITE.md` — astronomy tools guide
- `docs/AI_DEVELOPER_WORKBENCH.md` — Developer Workbench guide
- `docs/WEB_COMPANION.md` — LAN/iPad/browser workflow
- `docs/OFFLINE_VOICE_COMMANDS.md` — optional local Vosk voice commands
- `docs/SCRIPTS.md` — PowerShell script folder layout and common commands
- `docs/archive/RC3_FINAL_PRODUCTION_NOTES.md` — historical RC3 notes
