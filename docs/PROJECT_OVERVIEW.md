# FZAstro AI v2.0.0 Project Overview

FZAstro AI is a Windows desktop AI workstation focused on astrophotography, local LLM work, project-aware coding assistance, document research, web research, local Python execution, and astronomy planning.

## Main subsystems

| Area | Main files/folders | Purpose |
|---|---|---|
| Desktop shell | `fzastro_ai/app.py`, `fzastro_ai/ui/` | PySide6 main window, dialogs, message widgets, Help/About, benchmark and astro windows. |
| Actions | `fzastro_ai/actions/` | Main-window command mixins for chat lifecycle, Python, web/news, market, Astro tools, voice, and Developer Workbench. |
| Workers | `fzastro_ai/workers/` | Threaded workers for chat, imports, memory extraction, model discovery, GPU telemetry, web search, and astronomy tasks. |
| Knowledge | `fzastro_ai/knowledge_library.py` | Document import/search, PDF text/page handling, OCR hooks, and local SQLite-backed knowledge. |
| Memory | `fzastro_ai/memory_store.py`, `fzastro_ai/ui/memory_dialog.py` | Persistent local memory, review, search, and extraction. |
| Runtime/model controls | `fzastro_ai/runtime.py`, `fzastro_ai/model_controls.py` | Ollama/OpenAI-compatible runtime normalization, model discovery, status handling. |
| LLM benchmark | `fzastro_ai/benchmarks/`, `fzastro_ai/ui/llm_benchmark_dialog.py` | Model latency/throughput/quality tests, telemetry, history, compare views. |
| Astro tools | `fzastro_ai/astro_tools/`, `fzastro_ai/ui/*astro*`, `fzastro_ai/ui/seeing_dialog.py`, `fzastro_ai/ui/targets_dialog.py` | SITE, IMAGING, LOOKUP, SUN NOW, SEEING, TARGETS, SOLAR MAP. |
| Web Companion | `fzastro_ai/web_companion/` | Local browser companion server and static interface for LAN/iPad/mobile workflows. |
| Developer Workbench | `fzastro_ai/dev_agent/`, `fzastro_ai/ui/dev_workbench_dialog.py` | Project scanning, context building, planning, compile/pytest checks, failure analysis, patch snapshot helpers. |
| Build/release | `scripts/build_exe.ps1`, `scripts/clean_build.ps1`, `scripts/deploy.ps1`, `scripts/validate_release.ps1` | Repeatable Windows EXE build and validation workflow. |

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
- `logs/fzastroai.log`

Set `FZASTRO_APP_DIR` to override the runtime data folder for testing or portable runs.

## Version 2 cleanup result

- Root documentation reduced to `README.md`; release validation lives under `docs/`.
- Detailed docs consolidated under `docs/`.
- Overlay bundle integrated into the main package where useful.
- Generated Python bytecode, backup files, and patch leftovers removed from the source package.
- Developer Workbench is now a first-class app area rather than a separate overlay bundle.
