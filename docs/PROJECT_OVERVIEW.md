# FZAstro AI v2.4.0 Project Overview

FZAstro AI is a Windows desktop AI workstation focused on astrophotography, local LLM work, project-aware coding assistance, document research, web research, local Python execution, and astronomy planning.

## Main subsystems

| Area | Main files/folders | Purpose |
|---|---|---|
| Desktop shell | `fzastro_ai/app.py`, `fzastro_ai/ui/` | PySide6 main window, dialogs, message widgets, Help/About, benchmark and astro windows. |
| Actions | `fzastro_ai/actions/` | Main-window command mixins for chat lifecycle, Python, web/news, market, Astro tools, voice, and OpenClaude. |
| Workers | `fzastro_ai/workers/` | Threaded workers for chat, imports, memory extraction, model discovery, GPU telemetry, web search, and astronomy tasks. |
| Knowledge | `fzastro_ai/knowledge_library.py` | Document import/search, PDF text/page handling, OCR hooks, and local SQLite-backed knowledge. |
| Memory | `fzastro_ai/memory_store.py`, `fzastro_ai/ui/memory_dialog.py` | Persistent local memory, review, search, and extraction. |
| Runtime/model controls | `fzastro_ai/runtime.py`, `fzastro_ai/model_controls.py` | Ollama/OpenAI-compatible runtime normalization, model discovery, status handling. |
| LLM benchmark | `fzastro_ai/benchmarks/`, `fzastro_ai/ui/llm_benchmark_dialog.py` | Model latency/throughput/quality tests, telemetry, history, compare views. |
| Astro tools | `fzastro_ai/astro_tools/`, `fzastro_ai/ui/*astro*`, `fzastro_ai/ui/seeing_dialog.py`, `fzastro_ai/ui/targets_dialog.py` | SITE, IMAGING, LOOKUP, SUN NOW, SEEING, TARGETS, SOLAR MAP. |
| Web Companion | `fzastro_ai/web_companion/` | Local browser companion server and static interface for LAN/iPad/mobile workflows. |
| OpenClaude | `fzastro_ai/dev_agent/`, `fzastro_ai/ui/dev_workbench_dialog.py` | Project scanning, focused context, structured JSON tool execution, local Ollama inspect/plan/patch proposal, compile/pytest checks, failure analysis, and patch snapshot helpers. |
| FZAstro Imaging / N.I.N.A. bundle | `fzastro_ai/nina/`, `fzastro_ai/ui/nina_control_dialog.py`, `fzastro_ai/actions/nina_actions.py`, `fzastro_ai/resources/nina_templates/`, `bundled_apps/FZAstroImaging/` | Side-by-side imaging-app launcher, quiet bundle build, local settings, update feed check, safe update package download, and review-only Advanced Sequencer plan export. |
| Build/release | `DEPLOY.bat`, `scripts/build_exe.ps1`, `scripts/clean_build.ps1`, `scripts/deploy.ps1`, `scripts/validate_release.ps1` | Root deploy launcher plus repeatable Windows EXE build, validation, Git commit/tag, and optional push workflow. |

## Runtime storage

By default, local runtime data is stored under:

```text
%APPDATA%\FZAstroAI
```

Important runtime files include:

- `history.json`
- `memory.json`
- `calibration_profiles.json`
- `document_knowledge.sqlite3`
- `daily_news_cache.json`
- `llm_benchmark_history.json`
- `web_companion_settings.json`
- `nina_integration.json`
- `logs/fzastroai.log`

Set `FZASTRO_APP_DIR` to override the runtime data folder for testing or portable runs.

## Version 2.3 imaging production result

- Root documentation reduced to `README.md`; release validation lives under `docs/`.
- Detailed docs consolidated under `docs/`.
- Root folder keeps one easy deploy launcher, `DEPLOY.bat`; workflow scripts live under `scripts/`.
- Deploy can run validation and then create the local release commit/tag with `-GitRelease`; `-GitPush` pushes the branch and tag.
- Tracked installer/runtime leftovers were removed from the source root.
- Generated Python bytecode, backup files, local virtual environments, and patch leftovers are omitted from the clean source package.
- OpenClaude is now a first-class app area rather than a separate overlay bundle.
- Main astronomy tools open as tabs in the main workspace through the Apps launcher.
- Adds safe predefined `/nina-plan` and `/imaging-plan` commands for review-first imaging plans.
- Uses SITE, IMAGING, SEEING, and TARGETS context to choose practical targets and windows.
- Writes plans under `Documents\FZAstroAI\Imaging Plans\<plan_id>`.
- Generates real N.I.N.A. Advanced Sequencer JSON from `fzastro_ai/resources/nina_templates/osc_advanced_sequence_template.json`.
- Keeps Markdown, XML, CSV, review JSON, and internal JSON sidecars for traceability.
- Can launch the bundled FZAstro Imaging app and attempt to open the generated sequence for review.
- Maintains the safety boundary: no slew, center, guide, autofocus, capture, sequence start, or hardware schedule is performed automatically.
- Keeps `external/` and `bundled_apps/` out of normal source handoff packages because they are generated/vendor-heavy folders.
