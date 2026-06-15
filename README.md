# FZAstro AI

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
