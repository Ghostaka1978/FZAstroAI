param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$Model = $env:FZASTRO_OPENCLAUDE_MODEL,
    [string]$BaseUrl = $env:FZASTRO_OPENCLAUDE_BASE_URL,
    [string]$ApiKey = $env:FZASTRO_OPENCLAUDE_API_KEY,
    [switch]$InstallIfMissing
)

$ErrorActionPreference = "Stop"

function Add-PathEntry {
    param([string]$PathEntry)
    if ($PathEntry -and (Test-Path -LiteralPath $PathEntry) -and ($env:Path -notlike "*$PathEntry*")) {
        $env:Path = $PathEntry + ";" + $env:Path
    }
}

function Resolve-RequiredCommand {
    param(
        [string]$Name,
        [string]$InstallHint
    )

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    throw "$Name was not found on PATH. $InstallHint"
}

$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
if (-not (Test-Path -LiteralPath $ProjectRoot)) {
    throw "Project root not found: $ProjectRoot"
}
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot "main.py")) -or -not (Test-Path -LiteralPath (Join-Path $ProjectRoot "fzastro_ai"))) {
    throw "Project root does not look like a FZAstro source checkout: $ProjectRoot"
}

if (-not $Model) { $Model = "qwen3:32b" }
if (-not $BaseUrl) { $BaseUrl = "http://localhost:11434/v1" }
if (-not $ApiKey) { $ApiKey = "ollama" }

Add-PathEntry "C:\Program Files\nodejs"
Add-PathEntry (Join-Path $env:APPDATA "npm")

$node = Resolve-RequiredCommand -Name "node" -InstallHint "Install Node.js LTS with: winget install OpenJS.NodeJS.LTS"
$npm = Resolve-RequiredCommand -Name "npm" -InstallHint "Close/reopen PowerShell after installing Node.js, or add C:\Program Files\nodejs to PATH."
$openclaude = Get-Command openclaude -ErrorAction SilentlyContinue

if (-not $openclaude -and $InstallIfMissing) {
    Write-Host "Installing OpenClaude CLI from npm..."
    & $npm install -g "@gitlawb/openclaude@latest"
    $openclaude = Get-Command openclaude -ErrorAction SilentlyContinue
}

if (-not $openclaude) {
    throw "OpenClaude was not found. Install it with: npm install -g @gitlawb/openclaude@latest"
}

$env:CLAUDE_CODE_USE_OPENAI = "1"
$env:OPENAI_BASE_URL = $BaseUrl
$env:OPENAI_MODEL = $Model
$env:OPENAI_API_KEY = $ApiKey
$env:FZASTRO_PROJECT_ROOT = $ProjectRoot

Set-Location -LiteralPath $ProjectRoot
Write-Host ""
Write-Host "FZAstro OpenClaude Companion"
Write-Host "Project:  $ProjectRoot"
Write-Host "Node:     $node"
Write-Host "Model:    $Model"
Write-Host "Endpoint: $BaseUrl"
Write-Host ""
$PromptPath = Join-Path (Join-Path $env:APPDATA "FZAstroAI\openclaude") "latest_openclaude_prompt.md"
if (Test-Path -LiteralPath $PromptPath) {
    Write-Host "Prompt:  $PromptPath"
}
Write-Host "Paste the FZAstro-generated DEV task prompt first, or type /help."
Write-Host ""
& $openclaude.Source
