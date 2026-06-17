# FZAstro AI v2.0.0 Cleanup Report

## Evaluation

The uploaded archive contained the current RC3 application plus a separate `overlay/` bundle. The overlay included useful Developer Workbench files, but its `overlay/fzastro_ai/app.py` was older than the current root `fzastro_ai/app.py`, so a blind overlay copy would have risked losing the newer Web Companion/LAN work.

## What changed

- Bumped app identity to `2.0.0` / `Version 2 Production`.
- Removed generated cache files: `__pycache__/`, `.pyc`, `.pyo`.
- Removed stale backup/repair files: `.bak`, `.broken_*`, `.blackfix`, `.futurefix`, old server backup files.
- Removed the root `overlay/` bundle.
- Integrated only the useful overlay pieces:
  - `fzastro_ai/dev_agent/`
  - `fzastro_ai/actions/dev_actions.py`
  - `fzastro_ai/ui/dev_workbench_dialog.py`
  - Developer Workbench tests
  - `docs/AI_DEVELOPER_WORKBENCH.md`
- Wired the Developer Workbench into the current app using a `DEV` quick-action button.
- Consolidated docs:
  - Root keeps `README.md`; release validation lives under `docs/`.
  - Detailed docs live under `docs/`.
  - Historical RC3 notes moved to `docs/archive/`.
  - Stale patch/bundle readmes removed.
- Updated Help and About for v2.0.
- Fixed `.gitignore`, which previously contained PowerShell wrapper text instead of normal gitignore content.
- Fixed standalone `FZAstroAI.spec` ordering so `web_companion_static_datas` is defined before use and included in `datas`.
- Updated build copy behavior so the release still receives `OFFLINE_VOICE_COMMANDS.md` from `docs/OFFLINE_VOICE_COMMANDS.md`.

## Recommended root after cleanup

```text
fzastro_ai/
tests/
docs/
main.py
README.md
docs/RELEASE_VALIDATION.md
VERSION.txt
requirements.txt
pyproject.toml
build_exe.ps1
clean_build.ps1
deploy.ps1
validate_release.ps1
run_web_companion.ps1
install_offline_voice.ps1
activate_venv.ps1
reset_venv.ps1
format_code.ps1
repair_startup_import.ps1
FZAstroAI.spec
favicon.ico
NGC.csv
.gitignore
```

## Validation run in this sandbox

Passed:

```powershell
python -m compileall -q fzastro_ai tests
python -m pytest -q tests/test_version_and_docs.py tests/test_v2_cleanup_structure.py tests/test_web_companion_foundation.py tests/test_release_workflow_scripts.py tests/test_startup_imports.py
```

Full pytest was not run here because this sandbox does not have PySide6 installed; run it on your Windows venv.

## Recommended local commands

```powershell
python -m compileall -q fzastro_ai tests
python -m pytest
powershell -ExecutionPolicy Bypass -File .\scripts\validate_release.ps1 -PythonExe ".\.venv\Scripts\python.exe" -SkipLaunch
```


## Second cleanup pass: script folder consolidation

PowerShell workflow scripts were moved from the project root into `scripts/`. Documentation, Help/About references, tests, and cross-script calls were updated so the root stays cleaner while release commands remain explicit.

Use commands such as `powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1` and `. .\scripts\activate_venv.ps1`.
