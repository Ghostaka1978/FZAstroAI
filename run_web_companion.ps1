param(
    [int]$Port = 7860,
    [switch]$Lan,
    [string]$Token = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    throw "Virtual environment not found at $PythonExe. Run reset_venv.ps1 or create .venv first."
}

if ($Token.Trim()) {
    $env:FZASTRO_WEB_TOKEN = $Token.Trim()
}

if ($Lan) {
    if (-not $env:FZASTRO_WEB_TOKEN) {
        Write-Warning "LAN mode is enabled without FZASTRO_WEB_TOKEN. Use -Token or set the environment variable first."
    }
    & $PythonExe -m fzastro_ai.web_companion --lan --port $Port
} else {
    & $PythonExe -m fzastro_ai.web_companion --port $Port
}
