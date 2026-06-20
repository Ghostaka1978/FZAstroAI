# FZAstro AI Scripts

FZAstro AI v2.3 keeps PowerShell workflow scripts in the `scripts/` folder instead of the project root. The root folder keeps one easy deploy launcher, `DEPLOY.bat`, for normal release work.

## Common commands

```powershell
.\DEPLOY.bat
.\DEPLOY.bat -GitPush
powershell -ExecutionPolicy Bypass -File .\scripts\reset_venv.ps1 -Force
. .\scripts\activate_venv.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\format_code.ps1 -PythonExe ".\.venv\Scripts\python.exe"
powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1 -SetupOpenClaudeCompanion -InstallOpenClaudeIfMissing -InstallEmbeddedTerminalBackend -RunValidation -GitRelease
powershell -ExecutionPolicy Bypass -File .\scripts\setup_openclaude_companion.ps1 -InstallOpenClaudeIfMissing -InstallEmbeddedTerminalBackend
powershell -ExecutionPolicy Bypass -File .\scripts\run_openclaude.ps1 -ProjectRoot . -Model "qwen3:32b"
powershell -ExecutionPolicy Bypass -File .\scripts\validate_release.ps1 -PythonExe ".\.venv\Scripts\python.exe" -SkipLaunch
```

## Script roles

| Script | Purpose |
|---|---|
| `activate_venv.ps1` | Activates `.venv` and sets FZAstro build/runtime environment variables. |
| `reset_venv.ps1` | Recreates the Python 3.11 virtual environment. |
| `format_code.ps1` | Runs Black formatting or formatting checks. |
| `deploy.ps1` | Scripted release workflow; supports `-SetupOpenClaudeCompanion`, `-InstallOpenClaudeIfMissing`, `-InstallNodeWithWinget`, `-InstallEmbeddedTerminalBackend`, `-GitRelease`, `-GitTag`, `-GitCommitMessage`, `-GitPush`, `-GitRemote`, and `-GitBranch`. |
| `setup_openclaude_companion.ps1` | Best-effort deploy/setup helper for Node.js/npm/OpenClaude and optional pywinpty embedded-terminal backend. It accepts `-PythonExe` so deploy/build can install/check pywinpty in the same Python environment used for FZAstro, can install OpenClaude with npm, and writes status under AppData. |
| `run_openclaude.ps1` | Source/release helper that launches OpenClaude with FZAstro-compatible Ollama/OpenAI environment variables. |
| `clean_build.ps1` | Cleans generated build/cache output, then starts `build_exe.ps1`. |
| `build_exe.ps1` | Builds the Windows EXE and prepares the release folder. |
| `validate_release.ps1` | Runs release validation checks. |
| `run_web_companion.ps1` | Starts the Web Companion manually. |
| `install_offline_voice.ps1` | Installs/configures the offline Vosk voice model. |
| `repair_startup_import.ps1` | Repair utility for startup import/version metadata issues. |

All scripts default their project root to the parent folder of `scripts/`, so they can be launched from the repository root with `-File .\scripts\name.ps1`. For day-to-day release work, use `DEPLOY.bat`; it calls `scripts/deploy.ps1 -SetupOpenClaudeCompanion -InstallOpenClaudeIfMissing -InstallEmbeddedTerminalBackend -RunValidation -GitRelease` and accepts extra deploy flags such as `-GitPush`. During deploy, the resolved project Python is passed into OpenClaude setup so `pywinpty` is installed into the build/runtime environment instead of an unrelated global Python. OpenClaude setup is best-effort by default: if Node.js/npm or pywinpty are missing it writes a clear status file and continues unless you run `setup_openclaude_companion.ps1 -RequireReady`.
