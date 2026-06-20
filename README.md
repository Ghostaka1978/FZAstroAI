# FZAstro AI v2.4.0 - OpenClaude Terminal Production

FZAstro AI is a Windows PySide6 desktop AI workstation for astrophotography, local LLM workflows, document knowledge, persistent local memory, Python execution, web/news/market tools, hardware telemetry, LLM benchmarking, dedicated OpenClaude workspace terminal, Web Companion, and integrated astronomy planning.

Release identity: **FZAstro AI v2.4.0 (OpenClaude Terminal Production)**.
GitHub repository: https://github.com/Ghostaka1978/FZAstroAI

## v2.4.0 release highlight

FZAstro AI v2.4.0 is a major OpenClaude release. The old experimental Developer Workbench / legacy DEV testbed has been removed from the normal app surface. In its place, FZAstro now provides a dedicated **OpenClaude** workspace tab with a real embedded terminal, Session setup, visible workspace/git/provider context, and project rules through `AGENTS.md`. OpenClaude owns the interactive coding flow directly inside the selected workspace; FZAstro supplies the workspace, model endpoint, terminal host, telemetry, and release-safe setup/deploy support.

Release tag: `v2.4.0`.

## Screenshots

These v2.4.0 captures show the main desktop workspace, polished tool outputs, astronomy planning tabs, N.I.N.A. handoff, benchmarking, and the Web Companion.

<table>
  <tr>
    <td width="50%">
      <img src="docs/screenshots/fzastro-chat-workspace.png" alt="FZAstro AI chat workspace with Apps launcher">
      <br><sub>Main chat workspace with compact tabs, tool shortcuts, telemetry, and Apps launcher.</sub>
    </td>
    <td width="50%">
      <img src="docs/screenshots/fzastro-daily-news.png" alt="Daily News Brief with structured article cards">
      <br><sub>Daily News Brief with source counts, structured categories, article summaries, and open links.</sub>
    </td>
  </tr>
  <tr>
    <td width="50%">
      <img src="docs/screenshots/fzastro-global-market-pulse.png" alt="Global Market Pulse dashboard">
      <br><sub>Global Market Pulse with indices, regions, commodities, FX, status chips, and delayed-data notes.</sub>
    </td>
    <td width="50%">
      <img src="docs/screenshots/fzastro-lookup-m31.png" alt="LOOKUP M31 sky preview and distance details">
      <br><sub>LOOKUP tab with M31 distance details, camera framing, and sky preview.</sub>
    </td>
  </tr>
  <tr>
    <td width="50%">
      <img src="docs/screenshots/fzastro-targets-planner.png" alt="TARGETS planner with sky preview and capture controls">
      <br><sub>TARGETS planner with ranked objects, large sky preview, and capture handoff controls.</sub>
    </td>
    <td width="50%">
      <img src="docs/screenshots/fzastro-seeing-planner.png" alt="SEEING Astro Night Planner">
      <br><sub>SEEING Astro Night Planner with hourly rows, cloud, Moon, seeing, transparency, and dark periods.</sub>
    </td>
  </tr>
  <tr>
    <td width="50%">
      <img src="docs/screenshots/fzastro-sun-now.png" alt="SUN NOW solar image viewer">
      <br><sub>SUN NOW tab with NASA/SDO solar imagery and metadata.</sub>
    </td>
    <td width="50%">
      <img src="docs/screenshots/fzastro-solar-map.png" alt="Native Solar Map with live planet positions">
      <br><sub>SOLAR MAP with native 2D planet positions, orbits, labels, and AU grid.</sub>
    </td>
  </tr>
  <tr>
    <td width="50%">
      <img src="docs/screenshots/fzastro-nina-control.png" alt="FZAstro Imaging Control N.I.N.A. session cockpit">
      <br><sub>FZAstro Imaging Control for review-first N.I.N.A. session handoff.</sub>
    </td>
    <td width="50%">
      <img src="docs/screenshots/fzastro-llm-benchmark.png" alt="LLM Benchmark dashboard">
      <br><sub>LLM Benchmark dashboard with telemetry, presets, model/persona selection, and score history.</sub>
    </td>
  </tr>
  <tr>
    <td colspan="2">
      <img src="docs/screenshots/fzastro-web-companion.png" alt="FZAstro AI Web Companion mobile and LAN interface">
      <br><sub>Web Companion for LAN/mobile workflows with LOOKUP, Daily News, SEEING, TARGETS, Site Planner, and local model chat.</sub>
    </td>
  </tr>
</table>

## Major production areas

- **Tabbed workspace** - Chat, LOOKUP, SEEING, SUN NOW, N.I.N.A., TARGETS, Help/About, and system panels open as main-window tabs with a shared style.
- **Astro Tools Suite** - SITE, IMAGING, LOOKUP, SUN NOW, SEEING, TARGETS, and SOLAR MAP.
- **FZASTRO IMAGING / N.I.N.A. bridge** - safe Advanced Sequencer JSON export, bundled FZAstro Imaging launcher, N.I.N.A. API handoff, explicit ARM + START VIA API control, and session reports.
- **LLM Benchmark Dashboard** - LLM BENCH opens a polished control layout with Dashboard, History, Compare, and benchmark controls.
- **OpenClaude** - dedicated Codex-style workspace terminal backed by Windows ConPTY/pywinpty and an xterm.js frontend. The legacy Developer Workbench / DEV testbed has been removed from the normal UI; Session shows workspace/git/provider details, while all coding interaction happens directly inside the terminal.
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

`DEPLOY.bat` is the root-folder deploy button. It runs `scripts/deploy.ps1 -SetupOpenClaudeCompanion -InstallOpenClaudeIfMissing -RunValidation -GitRelease`, so a successful deploy also prepares the OpenClaude companion when Node/npm are available and creates the local release commit and annotated tag from `VERSION.txt` (`v2.4.0` for this release). Add `-GitPush` when you want the branch and tag pushed:

```powershell
.\DEPLOY.bat -GitPush
```

PowerShell equivalent:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1 -SetupOpenClaudeCompanion -InstallOpenClaudeIfMissing -RunValidation -GitRelease
powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1 -SetupOpenClaudeCompanion -InstallOpenClaudeIfMissing -RunValidation -GitRelease -GitPush
```

The scripts enforce Python 3.11 for the build even if newer interpreters such as **Python 3.14** are installed on the system. `scripts/reset_venv.ps1` recreates the venv, sets `FZASTRO_PYTHON`, and uses the sibling build folder one folder above the project root: `..\FZAstroAI_BUILD`.

`deploy.ps1` is the scripted release workflow command. It can run `scripts/setup_openclaude_companion.ps1` before the build, then calls `scripts/clean_build.ps1`, which starts `build_exe.ps1` automatically, then validation can run `scripts/validate_release.ps1`. The cleanup/build/validation scripts use a progress bar, `VerboseOutput`, and logs under `..\FZAstroAI_BUILD\logs`. Optional external checks for Ollama, Tesseract, Playwright, Node.js/npm, and OpenClaude use warnings/status output so a missing companion tool does not block deployment unless explicitly required.

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

OpenClaude update: broad analysis requests such as `analyse all Python files` now build a project-audit index of every scanned `.py` file while keeping deep-read excerpts bounded.



### Codex-style OpenClaude prerequisites

For source/developer setups on Windows, install Node.js, Git, ripgrep, and OpenClaude once. FZAstro deploy/setup scripts validate these tools and prepare the embedded ConPTY backend; the app UI does not install Python packages at runtime.

```powershell
winget install -e --id OpenJS.NodeJS.LTS
winget install -e --id Git.Git
winget install -e --id BurntSushi.ripgrep.MSVC
npm install -g @gitlawb/openclaude@latest
```

### Embedded OpenClaude

The OpenClaude workspace now uses OpenClaude as the coding-agent path with the selected FZAstro model and endpoint. Normal chat still uses the direct runtime (`FZAstro AI -> Ollama/OpenAI-compatible API`), while coding tasks use (`FZAstro OpenClaude -> embedded OpenClaude terminal -> Ollama`). On Windows, FZAstro embeds the interactive OpenClaude CLI through ConPTY/pywinpty in the Agent Workspace. Runtime package setup is kept out of the app UI: `pywinpty` is installed and packaged by requirements/setup/build/deploy, while the app only reports whether the embedded backend is ready. If the embedded backend is unavailable or unstable, the external terminal launcher remains available. FZAstro generates the runtime launcher and structured OpenClaude task prompt under `AppData\Roaming\FZAstroAI\openclaude`, so frozen EXE deployments do not depend on source-relative scripts.

### OpenClaude UX polish

- OpenClaude remembers the last valid project root and restores it on reopen.
- The OpenClaude page shows compact telemetry plus a colored running/stopped state indicator; the old progress bar is removed so the terminal keeps maximum space.
- Stop Agent uses cooperative cancellation with shorter model-read timeouts and clearer progress/status text.
- Web Companion/LAN token/security tasks are routed to launcher/server/app/test files instead of unrelated UI files.
- Invalid empty tool requests stop with actionable guidance instead of looping until timeout.


### OpenClaude single workspace

The OpenClaude workspace now uses one Agent Workspace timeline for plans, answers, patch proposals, previews, validation cards, and reports. File evidence and raw logs/context/diffs/test output live in on-demand resizable right-side drawers with their own scroll areas, keeping the main workspace stable while details are open. Runtime/model details and separate steering fields are intentionally hidden from the OpenClaude surface; the main model bar and task composer are the user-facing controls. Normal patch work no longer requires switching between Log, Chat, Patch, Validation, and Report tabs.

### OpenClaude apply hardening

Patch application now handles partially stale unified diffs more safely. If an implementation hunk was already applied but a new test-file hunk still needs to be created, OpenClaude skips only the proven already-applied section and applies the remaining valid section after creating a rollback snapshot. Apply failures now report failed paths and raw `git apply` details instead of only saying that no files changed. New-file `/dev/null` diff sections are validated and applied explicitly.

### OpenClaude polish

The OpenClaude workspace now remembers the last valid project root, shows progress and telemetry, highlights the next workflow action, keeps patch apply locked until preview, and uses generic evidence-based planning so patch-management wording does not pull in unrelated OpenClaude UI/type files.


Release validation skips `ollama list` by default so deploy checks do not depend on a running Ollama server. Use `scripts/validate_release.ps1 -DeepRuntimeChecks` only when you explicitly want a local Ollama model inventory check.

## OpenClaude

The OpenClaude workspace uses a real terminal frontend when available: Qt WebEngine + xterm.js connected to Windows ConPTY/pywinpty. Run `scripts\setup_openclaude_companion.ps1 -InstallEmbeddedTerminalBackend -InstallTerminalFrontend` before building/deploying on Windows.


### OpenClaude session cleanup

Session is setup/status only: workspace, provider/environment, git state, AGENTS.md, and terminal frontend/backend readiness. Patch/test/report controls from the old DEV testbed are not exposed in Session; normal work happens directly in the Claude Terminal. Dirty git checkouts are shown with a warning so live workspace changes are visible before using OpenClaude.
