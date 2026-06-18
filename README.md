# FZAstro AI v2.3.0 - Imaging Production

FZAstro AI is a Windows PySide6 desktop AI workstation for astrophotography, local LLM workflows, document knowledge, persistent local memory, Python execution, web/news/market tools, hardware telemetry, LLM benchmarking, Developer Workbench coding assistance, Web Companion, and integrated astronomy planning.

Release identity: **FZAstro AI v2.3.0 (Imaging Production)**.
GitHub repository: https://github.com/Ghostaka1978/FZAstroAI

## Major production areas

- **Tabbed workspace** - Chat, LOOKUP, SEEING, SUN NOW, N.I.N.A., TARGETS, Help/About, and system panels open as main-window tabs with a shared style.
- **Astro Tools Suite** - SITE, IMAGING, LOOKUP, SUN NOW, SEEING, TARGETS, and SOLAR MAP.
- **FZASTRO IMAGING / N.I.N.A. bridge** - safe Advanced Sequencer JSON export, bundled FZAstro Imaging launcher, N.I.N.A. API handoff, explicit ARM + START VIA API control, and session reports.
- **LLM Benchmark Dashboard** - LLM BENCH opens a polished control layout with Dashboard, History, Compare, and benchmark controls.
- **Developer Workbench** - project scanning, context building, patch creation, compile/pytest checks, error analysis, and code-building workflows.
- **Document knowledge** - import/search local documents with SQLite-backed storage.
- **Web Companion** - local browser/LAN companion for iPad/mobile workflows.

## Astro Tools Suite

The Astro Tools Suite includes **SITE, IMAGING, LOOKUP, SUN NOW, SEEING, TARGETS, and SOLAR MAP**. SEEING and TARGETS use structured backend data for cloud-aware planning, night scoring, Bortle context, and target selection rather than scraping rendered UI text.

Bortle-aware visual hints are preserved: **8–9 white/urban**, **6–7 yellow**, **4–5 green**, **2–3 blue**, and **1 violet**. The night planner keeps cloud-aware score caps, moon/darkness context, and urban/white-zone helper text.

Astropy/IERS runtime handling disables unsafe live IERS downloads in the app path to avoid malformed table crashes, while provider timeouts are handled safely and logged instead of breaking astronomy workflows.

## FZASTRO IMAGING / N.I.N.A. workflow

FZASTRO IMAGING CONTROL is designed as a review-first operations cockpit:

1. **OPEN TARGETS** — choose a target from structured TARGETS/SEEING context.
2. **CONFIRM + LOAD INTO N.I.N.A.** — generate the confirmed `.nina-sequence.json`, copy a plain `.json` into the configured N.I.N.A. sequence folder, verify `/sequence/list-available`, load with `GET /sequence/load?sequenceName=...`, and verify `/sequence/state`.
3. **EQUIPMENT PREP / POWER ON** — use basic generated prep steps or load a user-provided `FZAstro_EquipmentPrepSample.json` for N.I.N.A. review only.
4. **ARM + START VIA API** — after explicit confirmation, start the loaded sequence using `GET /sequence/start`.
5. **SESSION REPORT** — write Markdown/JSON reports and show target, conditions, capture, site, API, last-image, and safety highlights in the UI.

The workflow never starts automatically after load. START remains a separate user-confirmed hardware-action request.

## LLM Benchmark Dashboard

The **LLM Benchmark Dashboard** is available from **LLM BENCH**. It includes telemetry, history, comparison views, persona/calibration checks, and quality scoring. The benchmark workflow includes **Run All Presets**, **Delete Selected**, Composite scoring, and raw-model testing with **Raw model (no persona)**.

## Distance ladder calculations

FZAstro AI includes **Distance ladder calculations** for astronomy object context. The distance-ladder path can use parallax, Gaia, NED-D, Hubble, and `hubble(z)` style fallback logic where available. Use `FZASTRO_USE_DISTANCE_LADDER` to enable or control this feature in supported workflows.

## Build and release workflow

Use a Python 3.11 virtual environment for the packaged app build and validation workflow:

```powershell
py -3.11 -m venv .venv
. .\scripts\activate_venv.ps1
.\DEPLOY.bat
```

`DEPLOY.bat` is the root-folder deploy button. It runs `scripts/deploy.ps1 -RunValidation -GitRelease`, so a successful deploy also creates the local release commit and annotated tag from `VERSION.txt` (`v2.3.0` for this release). Add `-GitPush` when you want the branch and tag pushed:

```powershell
.\DEPLOY.bat -GitPush
```

PowerShell equivalent:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1 -RunValidation -GitRelease
powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1 -RunValidation -GitRelease -GitPush
```

The scripts enforce Python 3.11 for the build even if newer interpreters such as **Python 3.14** are installed on the system. `scripts/reset_venv.ps1` recreates the venv, sets `FZASTRO_PYTHON`, and uses the sibling build folder one folder above the project root: `..\FZAstroAI_BUILD`.

`deploy.ps1` is the scripted release workflow command. It calls `scripts/clean_build.ps1`, which starts `build_exe.ps1` automatically, then validation can run `scripts/validate_release.ps1`. The cleanup/build/validation scripts use a progress bar, `VerboseOutput`, and logs under `..\FZAstroAI_BUILD\logs`.

The source handoff keeps the root folder lean: `main.py`, `DEPLOY.bat`, version/config files, README, requirements, pytest/Black config, icon/spec files used by the build, and the main `fzastro_ai/`, `docs/`, `scripts/`, and `tests/` folders. Generated caches, local virtual environments, external N.I.N.A. worktrees, bundled runtime binaries, and installer leftovers are not part of the clean source package.

Important build variables:

- `FZASTRO_PROJECT_ROOT`
- `FZASTRO_BUILD_ROOT`
- `FZASTRO_PYTHON`

## Runtime storage

Runtime data is stored under `%APPDATA%\FZAstroAI` by default. Important files include:

- `history.json`
- `memory.json`
- `calibration_profiles.json`
- `document_knowledge.sqlite3`
- `daily_news_cache.json`
- `llm_benchmark_history.json`
- `nina_integration.json`
- `logs/fzastroai.log`

Set `FZASTRO_APP_DIR` to override the runtime data folder for testing or portable runs.
