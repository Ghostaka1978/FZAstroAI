param(
    [string]$ProjectRoot = (Get-Location).Path,
    [switch]$NoBackup
)

$ErrorActionPreference = 'Stop'

function Write-Step($Message) {
    Write-Host "[FZAstro Attachment Context] $Message" -ForegroundColor Cyan
}

$bundleRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$overlayRoot = Join-Path $bundleRoot 'overlay'

if (-not (Test-Path (Join-Path $ProjectRoot 'fzastro_ai'))) {
    throw "ProjectRoot does not look like an FZAstro AI source folder: $ProjectRoot"
}

if (-not (Test-Path $overlayRoot)) {
    throw "Missing overlay folder in bundle: $overlayRoot"
}

$timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$backupRoot = Join-Path $ProjectRoot ".fzastro_patch_backups\attachment_context_$timestamp"

$files = @(
    'fzastro_ai\file_tools.py',
    'fzastro_ai\conversation_context.py',
    'fzastro_ai\actions\web_news_actions.py',
    'tests\test_file_tools.py',
    'tests\test_conversation_context.py'
)

Write-Step "Applying bundle to $ProjectRoot"

foreach ($relative in $files) {
    $source = Join-Path $overlayRoot $relative
    $target = Join-Path $ProjectRoot $relative

    if (-not (Test-Path $source)) {
        throw "Bundle overlay is missing: $source"
    }

    if ((Test-Path $target) -and (-not $NoBackup)) {
        $backup = Join-Path $backupRoot $relative
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backup) | Out-Null
        Copy-Item $target $backup -Force
    }

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    Copy-Item $source $target -Force
    Write-Step "Updated $relative"
}

Write-Step "Done. Backups: $backupRoot"
Write-Host ""
Write-Host "Recommended validation:" -ForegroundColor Yellow
Write-Host ".\.venv\Scripts\python.exe -m compileall -q fzastro_ai tests"
Write-Host ".\.venv\Scripts\python.exe -m pytest -q tests\test_file_tools.py tests\test_conversation_context.py tests\test_startup_imports.py"
