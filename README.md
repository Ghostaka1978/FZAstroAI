# FZAstro AI
# FZAstro AI

FZAstro AI is a Windows desktop AI workstation for astrophotography, document research, web research, local Python execution, and integrated astronomy tools.

It combines a local/OpenAI-compatible chat interface with a PySide6 desktop application, a document knowledge library, persistent memory, web tools, market/news actions, and migrated FZASTRO astrophotography utilities.

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

## Astrophotography tools

FZAstro AI includes integrated FZASTRO modules for astronomy and imaging workflows:

* **SITE** — save observing latitude, longitude, elevation, and timezone
* **IMAGING** — configure camera presets, focal length, field of view, image size, and rotation
* **LOOKUP** — look up objects such as M31, NGC objects, planets, comets, stars, spacecraft, nebulae, and galaxies
* **SEEING** — check clouds, Moon, humidity, wind, dew point, pressure, and imaging score
* **TARGETS** — plan tonight’s best astrophotography targets
* **SOLAR MAP** — render a current solar-system map

Example commands include:

```text
/astro M31
/astro NGC 7000
/astro IC 5146
/see
/targets
/solar-map
```

## Version 1 release-candidate scope

Version 1 is a release-candidate baseline for testing and validation. It includes:

* Local AI workstation built around Ollama/OpenAI-compatible chat
* Modular PySide6 desktop interface
* Document Knowledge Library
* PDF text retrieval and PDF page/image rendering
* Optional OCR support
* Web search and webpage extraction tools
* Daily News, market, gold, and crude-oil actions
* Integrated FZASTRO SITE, IMAGING, LOOKUP, SEEING, TARGETS, and SOLAR MAP tools
* Persistent memory with review/search tools
* Calibration profiles and model/profile controls
* Composer Actions, Context, and Persona menus
* Local Python code-block execution
* Repeatable Windows EXE build tooling
* Starter automated test suite for routing, memory, documentation, and version checks

## Runtime notes

Ollama or another OpenAI-compatible endpoint must be available for local chat.

Tesseract OCR is optional and only required for OCR/scanned-page workflows.

Playwright browser files are optional and only required for browser-backed web capture.

The Windows release build output is written one folder above the project root under:

```text
..\FZAstroAI_BUILD
```

FZAstro AI is packaged through the repository PowerShell release workflow.

## Release build workflow

Run these commands from the project root:

```powershell
.\clean_build.ps1
.\build_exe.ps1
.\validate_release.ps1
```

Release build output is written one folder above the project root under `..\FZAstroAI_BUILD`. The scripts use `FZASTRO_PROJECT_ROOT`, `FZASTRO_BUILD_ROOT`, and `FZASTRO_PYTHON` to keep the build, validation, and packaged EXE launch deterministic.

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

## Release artifact hygiene

Release validation checks that development/repair artifacts are not included in the release package.

Development/repair artifacts include `.bak`, `.patch`, `repair_*.ps1`, pytest cache data, Python cache directories, temporary debug files, local investigation notes, and other non-runtime files produced while repairing or validating the application.

The packaged release should contain only the application runtime files and required bundled resources.
