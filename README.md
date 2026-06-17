# FZAstro AI v2.0.0

FZAstro AI v2.0.0 is a Windows PySide6 desktop AI workstation for astrophotography, local LLM workflows, document research, web/news/market tools, local Python execution, hardware telemetry, LLM benchmarking, and integrated astronomy planning.

Version 2 keeps the mature RC3 astronomy and Web Companion foundation, then cleans the project into a simpler production tree and adds the first integrated **AI Developer Workbench** for code-focused workflows.

The **FZ** square in the app header opens the project GitHub repository: `https://github.com/Ghostaka1978/FZAstroAI`.

## Version 2 focus

- Clean source layout: application code lives under `fzastro_ai/`; root keeps launch, build, validation, version, and top-level docs only.
- `overlay/` has been removed as a separate folder. The useful Developer Workbench pieces are now integrated under `fzastro_ai/dev_agent`, `fzastro_ai/ui/dev_workbench_dialog.py`, and `fzastro_ai/actions/dev_actions.py`.
- Stale bundle/patch readmes were removed or consolidated into `docs/`.
- The app identity is now `FZAstro AI v2.0.0 (Version 2 Production)`.
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
.\run_web_companion.ps1 -Lan -Port 7860 -Token "fzastro"
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
main.py                     Desktop/Web Companion entry point
build_exe.ps1               Windows EXE build workflow
clean_build.ps1             Cleans build output and starts `build_exe.ps1` automatically
deploy.ps1                  Single release workflow command
validate_release.ps1        Release validation workflow
VERSION.txt                 Release version
```

## Development setup

Use Python 3.11 on Windows for release builds. Do not use Python 3.14 for release builds; the scripts enforce Python 3.11 so dependency and PyInstaller behavior stay predictable.

```powershell
powershell -ExecutionPolicy Bypass -File .\reset_venv.ps1 -Force
. .\activate_venv.ps1
python -m pytest
```

Launch from source:

```powershell
python main.py
```

## Build and validation

Recommended one-command workflow:

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy.ps1
```

`deploy.ps1` calls `clean_build.ps1`; `clean_build.ps1` starts `build_exe.ps1` automatically. The workflow uses a progress bar for cleanup, build, and validation stages, logs noisy subprocess output under `..\FZAstroAI_BUILD\logs`, and supports `-VerboseOutput` when full live command output is needed.

The default build folder is one folder above the project root:

```text
..\FZAstroAI_BUILD
```

`activate_venv.ps1` sets `FZASTRO_PROJECT_ROOT`, `FZASTRO_BUILD_ROOT`, and `FZASTRO_PYTHON` for child commands.

After a successful build, the script can show a validation prompt to run `validate_release.ps1`.

## Release validation hygiene notes

Release validation checks development/repair artifacts such as `.bak`, `.patch`, and `repair_*.ps1` files so they do not leak into the release package. It checks the release manifest, PyInstaller resource configuration, isolated `smoke_appdata`, and GUI smoke / GUI startup behavior.

## Detailed docs

- `RELEASE_VALIDATION.md` — production build/validation checklist
- `docs/PROJECT_OVERVIEW.md` — concise architecture summary
- `docs/ASTRO_TOOLS_SUITE.md` — astronomy tools guide
- `docs/AI_DEVELOPER_WORKBENCH.md` — Developer Workbench guide
- `docs/WEB_COMPANION.md` — LAN/iPad/browser workflow
- `docs/OFFLINE_VOICE_COMMANDS.md` — optional local Vosk voice commands
- `docs/archive/RC3_FINAL_PRODUCTION_NOTES.md` — historical RC3 notes
