# FZAstro AI v1.0.0 RC 3 Final Production

FZAstro AI v1.0.0 RC 3 Final Production is a Windows desktop AI workstation for astrophotography, document research, web research, local Python execution, LLM benchmarking, and the integrated **Astro Tools Suite**.

It combines a local/OpenAI-compatible chat interface with a PySide6 desktop application, a document knowledge library, persistent memory, web tools, market/news actions, benchmark telemetry, and production-ready migrated FZASTRO astrophotography utilities. The **FZ** square in the app header opens `https://github.com/Ghostaka1978/FZAstroAI` in the external browser.

## RC 3 Final Production highlights

RC 3 is the final production release-candidate baseline for Version 1. The release focus is stability, clean packaging, and the new **Astro Tools Suite** as a first-class workstation area rather than a collection of helper scripts.

Highlights:

* Clean package structure: application modules live under `fzastro_ai/`; the root keeps only launch, build, validation, and documentation files.
* Production About and Help text updated for `FZAstro AI v1.0.0 (Version 1 RC 3 Final Production)`.
* Astro Tools Suite emphasized across README, Help, About, and release validation.
* SEEING/Astro Night Planner polish: current local day/time context, current/tonight night-window wording, night-first forecast points, cloud-aware scoring, astronomical-dark prioritization, moon-period display, and Bortle-aware sky-quality styling.
* Bortle top-bar tint: Bortle 8–9 white/urban, 6–7 yellow, 4–5 green, 2–3 blue, and 1 violet.
* Standalone Astro tools open as centered, normal desktop windows with minimize/maximize/close controls.
* Astropy/IERS live-download hardening prevents malformed IERS table crashes during astronomy workflows.
* Web search hardening keeps DDGS/Yandex timeouts from crashing the app; failed providers are logged and the app can continue with fallback behavior.

## What FZAstro AI does

FZAstro AI provides a local workstation for:

* Chatting with local Ollama or OpenAI-compatible models
* Researching imported PDFs, text files, code files, and Excel documents
* Searching document knowledge and retrieving exact PDF page text
* Rendering real PDF pages/images when visual document inspection is needed
* Using optional OCR for scanned documents
* Searching the web, reading webpages, summarizing URLs, and capturing webpage screenshots
* Getting daily news, market quotes, gold prices, and crude-oil prices
* Running local Python code from chat or composer actions
* Saving and searching persistent memory
* Tracking answer sources with source tags such as LLM, Docs, Web, Files, Python, Memory, and App
* Monitoring hardware telemetry such as GPU/VRAM, CPU, RAM, and best-effort temperatures
* Benchmarking local/Ollama/OpenAI-compatible LLM models with latency, throughput, history, and comparison metrics

## LLM Benchmark Dashboard

FZAstro AI includes an integrated LLM Benchmark Dashboard for testing any model on the configured local or OpenAI-compatible endpoint without leaving the desktop app. Open it from **Skills → Model Lab → LLM Benchmark**; the legacy **LLM BENCH** label remains documented for release validation. The dashboard has its own model selector and refresh control, auto-refreshes the available model list on open, mirrors live GPU/VRAM and CPU/RAM telemetry from the main window, lets benchmark runs target a different model than the main chat selector when needed, and can run either as a raw model or with a selected app persona/calibration profile.

The benchmark dashboard can:

* Select and refresh models directly inside the benchmark window without changing the main chat model
* Select **Raw model**, **Active app persona**, or a specific calibration profile so persona effects are measured explicitly
* Run built-in benchmark presets for quick Q&A, math reasoning, code generation, creative writing, logical reasoning, data analysis, translation, summarization, and instruction following
* Run every built-in preset in one pass with **Run All Presets**
* Run a custom prompt with user-selected temperature and max-token settings from the top control panel
* Measure tokens per second, time to first token, total runtime, generation time, estimated input tokens, system-prompt tokens, and estimated completion tokens
* Score **accuracy**, **instruction following**, and **trust** with deterministic graders, prompt/response hashes, and a retained heuristic quality sense-check
* Show live telemetry and record a telemetry snapshot with each completed benchmark sample
* Save local benchmark history in `llm_benchmark_history.json` under the app data directory
* Compare tested models by model + persona, preset coverage, accuracy, speed, trust, instruction following, composite score, throughput, latency, and stability
* Use **Delete Selected**, Delete, or right-click to remove individual benchmark history records, or clear the full local history
* Export benchmark history to JSON for external review or sharing

Recommended quick check:

```text
Open LLM BENCH -> choose or refresh a model -> select Quick Q&A (short) -> Run Selected
```

For cleaner model comparisons, use **Run All Presets** on each model with the same endpoint, persona/calibration selection, temperature, repeat count, and background GPU load. Selected single-preset runs use the visible max-token setting; full-suite runs use each preset's default max-token budget. Use **Raw model** for pure speed baselines and a named persona/profile when you want to measure app-style behavior.

## Astro Tools Suite

FZAstro AI includes an integrated **Astro Tools Suite** for astronomy, imaging setup, observing-site context, night planning, solar monitoring, solar-system visualization, and target selection:

* **SITE** — save observing latitude, longitude, elevation, timezone, and optional SQM/Bortle sky-quality values used by SEEING and TARGETS
* **IMAGING** — configure camera presets, focal length, field of view, image size, and rotation
* **LOOKUP** — open a compact lookup window for objects such as M31, NGC objects, planets, comets, stars, spacecraft, nebulae, and galaxies; results and sky preview render inside the same window
* **SUN NOW** — display latest NASA/SDO solar images with Helioviewer metadata, channel/size selection, and cached fallback
* **SEEING** — open the Astro Night Planner with daily forecast cards, 7Timer ASTRO seeing/transparency, cloud gauges, Moon periods, astronomical-dark periods, night-first forecast points, cloud-aware scoring, and SQM/Bortle support
* **TARGETS** — open a native target-planner window with altitude/date/type filters, CSV export, and an optional local OpenNGC catalog import for a larger deep-sky object source
* **SOLAR MAP** — open a native interactive 2D solar-system map with zoom, pan, Full/Inner/Outer modes, orbit/label/grid toggles, and planet data

Example commands include:

```text
/astro M31
/astro NGC 7000
/astro IC 5146
/see
/targets
/solar-map
```

The Astro Tools Suite runs as dedicated dark-theme windows where appropriate. LOOKUP displays object details and the sky preview inside the lookup dialog, SUN NOW loads current solar imagery with cached fallback, SOLAR MAP uses a native zoomable 2D Qt map, TARGETS runs in a native planner window, and SEEING uses daily planner cards that prioritize astronomical darkness and useful night/imaging forecast points over daytime rows.

SEEING can display site sky quality as SQM/Bortle. The app supports manual values from SITE and an automatic best-effort LightPollutionMap.app lookup when available; values are labelled as estimated unless entered from a measured SQM source. The SEEING top bar tints itself by Bortle class: 8–9 white/urban, 6–7 yellow, 4–5 green, 2–3 blue, and 1 violet.

## Version 1 RC 3 Final Production scope

Version 1 RC 3 Final Production is the final production release-candidate baseline for Windows release testing, packaging, and validation. It includes:

* Local AI workstation built around Ollama/OpenAI-compatible chat
* Modular PySide6 desktop interface
* Document Knowledge Library
* PDF text retrieval and PDF page/image rendering
* Optional OCR support
* Web search and webpage extraction tools
* Skills bar grouping Research, Knowledge, Code Lab, Astro, Markets, Model Lab, and Workspace actions
* Daily News, market, gold, and crude-oil actions
* Integrated Astro Tools Suite: SITE, IMAGING, LOOKUP, SUN NOW, SEEING, TARGETS, and SOLAR MAP
* Persistent memory with review/search tools
* Calibration profiles and model/profile controls
* Composer Add, Skills, Knowledge, Code Lab, and Model Lab menus
* Local Python code-block execution
* LLM Benchmark Dashboard for local/Ollama/OpenAI-compatible model speed tests, direct model selection, and full-suite preset runs
* Repeatable Windows EXE build tooling
* Starter automated test suite for routing, memory, documentation, release workflow, and version checks

## Runtime notes

Ollama or another OpenAI-compatible endpoint must be available for local chat and LLM benchmarking.

Tesseract OCR is optional and only required for OCR/scanned-page workflows.

Playwright browser files are optional and only required for browser-backed web capture.

The Windows release build output is written one folder above the project root under:

```text
..\FZAstroAI_BUILD
```

FZAstro AI is packaged through the repository PowerShell release workflow.

## Release build workflow

Use the single release workflow command from the project root:

```powershell
. .\activate_venv.ps1
powershell -ExecutionPolicy Bypass -File .\deploy.ps1
```

`deploy.ps1` calls `clean_build.ps1`, and `clean_build.ps1` starts `build_exe.ps1` automatically after cleaning previous build/cache output. At the end of a successful build, the build script displays a validation prompt asking whether to run `validate_release.ps1` immediately.

Release build output is written one folder above the project root under `..\FZAstroAI_BUILD`. The scripts use `FZASTRO_PROJECT_ROOT`, `FZASTRO_BUILD_ROOT`, and `FZASTRO_PYTHON` to keep the build, validation, and packaged EXE launch deterministic.

The deploy/build/validation scripts use a quiet progress display by default. They show a progress bar and the current cleanup, build, and validation stage while sending noisy pip, pytest, Black, and PyInstaller output to `..\FZAstroAI_BUILD\logs`. Use `-VerboseOutput` when full live command output is needed.

The packaged release folder includes:

```text
FZAstroAI.exe
README.md
RELEASE_VALIDATION.md
requirements.txt
VERSION.txt
release_manifest.txt
```

The `release_manifest.txt` contains the EXE path, size, and SHA256 hash. `validate_release.ps1` verifies the release manifest, PyInstaller resource configuration, release artifact hygiene, and EXE smoke launch with isolated `smoke_appdata` through `FZASTRO_APP_DIR`. The pytest suite also includes optional GUI startup smoke coverage when PySide6 is installed.

## Python version policy

Release builds must use Python 3.11. Do not use Python 3.14 or any other non-3.11 interpreter for release builds.

The release scripts enforce this with the shared helpers `Get-PythonVersionInfo` and `Assert-Python311`. The scripts also look for `python3.11` where appropriate.

If `.venv` was created with the wrong interpreter, recreate it with:

```powershell
.\reset_venv.ps1
```

Manual equivalent:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Release validation

Before tagging or pushing a release candidate, run:

```powershell
python -m pytest
powershell -ExecutionPolicy Bypass -File .\validate_release.ps1 -PythonExe ".\.venv\Scripts\python.exe" -ExePath "..\FZAstroAI_BUILD\release\FZAstroAI.exe" -KeepRunning
```

Manual validation must include the LLM Benchmark Dashboard: open **LLM BENCH**, confirm the polished control layout is not clipped, confirm the telemetry row mirrors the main GPU/VRAM and CPU/RAM labels, confirm only Dashboard, History, and Compare tabs are shown, refresh/select a different model inside the dialog without changing the main chat selector, select Raw model and at least one persona/calibration profile, run Quick Q&A with **Run Selected**, run the full suite with **Run All Presets**, confirm metrics, accuracy, trust, quality scores, and grader evidence are populated, verify History persists, use **Delete Selected** to delete one selected history row, verify Compare groups by model + persona with composite/stability scores, export JSON, clear history, and stop a running benchmark.

## Git-ready handoff checklist

Before committing:

```powershell
python -m pytest
powershell -ExecutionPolicy Bypass -File .\format_code.ps1 -PythonExe ".\.venv\Scripts\python.exe" -Check
git status --short
git add README.md RELEASE_VALIDATION.md build_exe.ps1 validate_release.ps1 fzastro_ai tests
git commit -m "Prepare RC 3 final production docs"
git push
```

Do not commit `.venv`, `__pycache__`, `.pytest_cache`, local benchmark history, build output, repair patches, or temporary logs.

## Release artifact hygiene

Release validation checks that development/repair artifacts are not included in the release package.

Development/repair artifacts include `.bak`, `.patch`, `repair_*.ps1`, pytest cache data, Python cache directories, temporary debug files, local investigation notes, and other non-runtime files produced while repairing or validating the application.

The packaged release should contain only the application runtime files and required bundled resources.

### Distance ladder calculations

FZAstro AI includes distance-ladder calculation helpers for astronomy workflows. These expose the calculation path behind distance estimates, including standard relations such as parallax distance, distance modulus, luminosity-based estimates, and redshift/Hubble-law style calculations where applicable.

These tools are intended as practical astronomy aids and educational calculation helpers, not as replacements for professional catalogue data or peer-reviewed measurement pipelines.

Runtime note: optional distance-ladder helpers can be enabled with `FZASTRO_USE_DISTANCE_LADDER=1` when you want the astronomy tools to expose the distance calculation path.
