# FZAstro AI v2.0 second cleanup pass — PowerShell scripts folder

## Decision

Yes — moving the PowerShell scripts into their own folder is a good v2.0 cleanup step. It keeps the repository root focused on source, version, README, validation docs, requirements, and entry points.

## Final script layout

All PowerShell scripts now live under:

```text
scripts/
```

Moved scripts:

```text
scripts/activate_venv.ps1
scripts/build_exe.ps1
scripts/clean_build.ps1
scripts/deploy.ps1
scripts/format_code.ps1
scripts/install_offline_voice.ps1
scripts/repair_startup_import.ps1
scripts/reset_venv.ps1
scripts/run_web_companion.ps1
scripts/validate_release.ps1
```

No `.ps1` files remain in the project root.

## Important implementation details

- Script defaults now resolve `ProjectRoot` as the parent folder of `scripts/`.
- Cross-script calls now use `$ScriptsRoot` where needed.
- `deploy.ps1` calls `scripts/clean_build.ps1`.
- `clean_build.ps1` calls `scripts/build_exe.ps1`.
- `build_exe.ps1` calls `scripts/validate_release.ps1` and copies `scripts/install_offline_voice.ps1` into the release folder.
- `run_web_companion.ps1` now resolves the project root from the parent of its script folder.
- README, release validation docs, Help text, Web Companion docs, offline voice docs, and tests were updated to use `scripts/` paths.
- Added `docs/SCRIPTS.md` with common commands and script roles.

## Updated commands

```powershell
powershell -ExecutionPolicy Bypass -File .\scriptseset_venv.ps1 -Force
. .\scriptsctivate_venv.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1
powershell -ExecutionPolicy Bypass -File .\scriptsalidate_release.ps1 -PythonExe ".\.venv\Scripts\python.exe" -SkipLaunch
```

## Validation run in sandbox

```powershell
python -m compileall -q fzastro_ai tests
python -m pytest -q
```

Result:

```text
194 passed, 5 skipped
```

## Notes

Full Windows release validation should still be run on the target Windows machine because EXE building and GUI smoke validation depend on the local Windows/PySide/PyInstaller environment.
