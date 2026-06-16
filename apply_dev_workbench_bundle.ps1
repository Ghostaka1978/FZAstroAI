param(
    [switch]$OverlayFallback
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Get-Location
$BundleRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PatchPath = Join-Path $BundleRoot "fzastro_ai_dev_workbench.patch"
$OverlayRoot = Join-Path $BundleRoot "overlay"

if (-not (Test-Path (Join-Path $ProjectRoot "fzastro_ai\app.py"))) {
    throw "Run this script from the FZAstro AI project root. Expected fzastro_ai\app.py."
}

if (-not (Test-Path $PatchPath)) {
    throw "Patch file not found: $PatchPath"
}

$git = Get-Command git -ErrorAction SilentlyContinue
if ($git) {
    Write-Host "[1/3] Validating patch with git apply --check..."
    git apply --check $PatchPath
    if ($LASTEXITCODE -ne 0) {
        throw "Patch validation failed. Your working tree may differ from the bundled project state."
    }

    Write-Host "[2/3] Applying patch..."
    git apply $PatchPath
    if ($LASTEXITCODE -ne 0) {
        throw "Patch apply failed."
    }

    Write-Host "[3/3] Running syntax compile check..."
    python -m compileall -q fzastro_ai tests
    if ($LASTEXITCODE -ne 0) {
        throw "Compile check failed after applying the bundle."
    }

    Write-Host "AI Developer Workbench bundle applied successfully."
    Write-Host "Recommended tests:"
    Write-Host "python -m pytest -q tests/test_dev_agent_project_scanner.py tests/test_dev_agent_context_builder.py tests/test_dev_agent_patch_applier.py tests/test_dev_agent_error_analyzer.py"
    exit 0
}

if (-not $OverlayFallback) {
    throw "Git was not found. Install Git or rerun with -OverlayFallback to copy the overlay files directly."
}

Write-Warning "Using overlay fallback. This overwrites files from the overlay after creating timestamped backups."
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupRoot = Join-Path $ProjectRoot ".fzastro_ai_patches\dev_workbench_overlay_$stamp\backups"
New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null

Get-ChildItem -Path $OverlayRoot -Recurse -File | ForEach-Object {
    $relative = $_.FullName.Substring($OverlayRoot.Length).TrimStart('\', '/')
    $target = Join-Path $ProjectRoot $relative
    if (Test-Path $target) {
        $backup = Join-Path $backupRoot $relative
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backup) | Out-Null
        Copy-Item -Path $target -Destination $backup -Force
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    Copy-Item -Path $_.FullName -Destination $target -Force
}

python -m compileall -q fzastro_ai tests
if ($LASTEXITCODE -ne 0) {
    throw "Compile check failed after overlay copy. Backups are in $backupRoot"
}

Write-Host "Overlay copied successfully. Backups are in $backupRoot"
