$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Target = Join-Path $ProjectRoot "fzastro_ai\shutdown_controller.py"

if (-not (Test-Path (Join-Path $ProjectRoot "fzastro_ai"))) {
    throw "Run this script from the project root, next to the fzastro_ai folder."
}

$Content = @'
"""Backward-compatible import shim for the shutdown controller mixin.

The implementation lives in :mod:`fzastro_ai.controllers.shutdown_controller`.
This module keeps older local checkouts, stale bytecode, and external imports from
breaking after the controller extraction refactor.
"""

from .controllers.shutdown_controller import ShutdownControllerMixin

__all__ = ["ShutdownControllerMixin"]
'@

Set-Content -Path $Target -Value $Content -Encoding UTF8

$Cache = Join-Path $ProjectRoot "fzastro_ai\__pycache__"
if (Test-Path $Cache) {
    Remove-Item $Cache -Recurse -Force
}

Write-Host "Repaired: $Target"
Write-Host 'Now run: .\.venv\Scripts\python.exe -m pytest tests/test_prompt_and_controller_extraction.py -q'
