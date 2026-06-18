# FZAstro AI Scripts

FZAstro AI v2.3 keeps PowerShell workflow scripts in the `scripts/` folder instead of the project root. The root folder keeps one easy deploy launcher, `DEPLOY.bat`, for normal release work.

## Common commands

```powershell
.\DEPLOY.bat
.\DEPLOY.bat -GitPush
powershell -ExecutionPolicy Bypass -File .\scripts\reset_venv.ps1 -Force
. .\scripts\activate_venv.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\format_code.ps1 -PythonExe ".\.venv\Scripts\python.exe"
powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1 -RunValidation -GitRelease
powershell -ExecutionPolicy Bypass -File .\scripts\validate_release.ps1 -PythonExe ".\.venv\Scripts\python.exe" -SkipLaunch
```

## Script roles

| Script | Purpose |
|---|---|
| `activate_venv.ps1` | Activates `.venv` and sets FZAstro build/runtime environment variables. |
| `reset_venv.ps1` | Recreates the Python 3.11 virtual environment. |
| `format_code.ps1` | Runs Black formatting or formatting checks. |
| `deploy.ps1` | Scripted release workflow; supports `-GitRelease`, `-GitTag`, `-GitCommitMessage`, `-GitPush`, `-GitRemote`, and `-GitBranch`. |
| `clean_build.ps1` | Cleans generated build/cache output, then starts `build_exe.ps1`. |
| `build_exe.ps1` | Builds the Windows EXE and prepares the release folder. |
| `validate_release.ps1` | Runs release validation checks. |
| `run_web_companion.ps1` | Starts the Web Companion manually. |
| `install_offline_voice.ps1` | Installs/configures the offline Vosk voice model. |
| `repair_startup_import.ps1` | Repair utility for startup import/version metadata issues. |

All scripts default their project root to the parent folder of `scripts/`, so they can be launched from the repository root with `-File .\scripts\name.ps1`. For day-to-day release work, use `DEPLOY.bat`; it calls `scripts/deploy.ps1 -RunValidation -GitRelease` and accepts extra deploy flags such as `-GitPush`.
