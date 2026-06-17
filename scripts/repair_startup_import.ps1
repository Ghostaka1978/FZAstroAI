param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path $ProjectRoot).Path
$InitFile = Join-Path $ProjectRoot "fzastro_ai\__init__.py"

if (-not (Test-Path $InitFile)) {
    throw "Package init file not found: $InitFile"
}

@'
"""FZAstro AI modular package."""

from .config import APP_VERSION as __version__

__all__ = ["__version__"]
'@ | Set-Content -Path $InitFile -Encoding UTF8

Write-Host "Repaired: $InitFile"
Write-Host "Now run: .\.venv\Scripts\python.exe -c \"import fzastro_ai; print(fzastro_ai.__version__)\""
