param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$VenvPath = "",
    [string]$BuildRoot = ""
)

$ErrorActionPreference = "Stop"

function Resolve-BuildRootPath {
    param(
        [string]$RequestedBuildRoot,
        [string]$Root
    )

    if ($RequestedBuildRoot) {
        if ([System.IO.Path]::IsPathRooted($RequestedBuildRoot)) {
            return [System.IO.Path]::GetFullPath($RequestedBuildRoot)
        }
        return [System.IO.Path]::GetFullPath((Join-Path $Root $RequestedBuildRoot))
    }

    $ParentRoot = Split-Path -Parent $Root
    return [System.IO.Path]::GetFullPath((Join-Path $ParentRoot "FZAstroAI_BUILD"))
}


function Get-PythonVersionInfo {
    param([string]$PythonPath)

    if (-not $PythonPath) { return $null }

    try {
        $output = & $PythonPath -c "import sys; print(f'{sys.executable}|{sys.version_info.major}|{sys.version_info.minor}|{sys.version_info.micro}')" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $output) { return $null }
        $line = ($output | Select-Object -Last 1).Trim()
        $parts = $line -split "\|"
        if ($parts.Count -lt 4) { return $null }
        return [pscustomobject]@{
            Executable = $parts[0]
            Major = [int]$parts[1]
            Minor = [int]$parts[2]
            Micro = [int]$parts[3]
            Version = ("{0}.{1}.{2}" -f $parts[1], $parts[2], $parts[3])
        }
    }
    catch {
        return $null
    }
}

function Assert-Python311 {
    param([string]$PythonPath)

    $info = Get-PythonVersionInfo -PythonPath $PythonPath
    if (-not $info) {
        throw "Python interpreter is not usable: $PythonPath. Recreate the environment with: powershell -ExecutionPolicy Bypass -File .\scripts\reset_venv.ps1"
    }
    if ($info.Major -ne 3 -or $info.Minor -ne 11) {
        throw ("FZAstro AI build/deploy requires Python 3.11. Found Python {0} at {1}. Recreate the environment with: powershell -ExecutionPolicy Bypass -File .\scripts\reset_venv.ps1" -f $info.Version, $info.Executable)
    }
    return $info
}

function Resolve-PythonExecutable {
    param(
        [string]$RequestedPython,
        [string]$Root
    )

    if ($RequestedPython) {
        $candidate = $RequestedPython
        if (Test-Path $candidate) {
            $candidate = (Resolve-Path $candidate).Path
        }
        Assert-Python311 -PythonPath $candidate | Out-Null
        return $candidate
    }

    $DefaultVenvPython = Join-Path $Root ".venv\Scripts\python.exe"
    if (Test-Path $DefaultVenvPython) {
        $resolved = (Resolve-Path $DefaultVenvPython).Path
        Assert-Python311 -PythonPath $resolved | Out-Null
        return $resolved
    }

    foreach ($candidate in @("python3.11", "python")) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        $info = Get-PythonVersionInfo -PythonPath $candidate
        if ($info -and $info.Major -eq 3 -and $info.Minor -eq 11) {
            return $candidate
        }
    }

    throw "Python 3.11 environment not found. Run: powershell -ExecutionPolicy Bypass -File .\scripts\reset_venv.ps1"
}

$ProjectRoot = (Resolve-Path $ProjectRoot).Path
if (-not $VenvPath) {
    $VenvPath = Join-Path $ProjectRoot ".venv"
}
$BuildRoot = Resolve-BuildRootPath -RequestedBuildRoot $BuildRoot -Root $ProjectRoot

if (-not (Test-Path $VenvPath)) {
    throw "Virtual environment not found: $VenvPath. Create it with: powershell -ExecutionPolicy Bypass -File .\scripts\reset_venv.ps1 -Force"
}

$PythonExe = Join-Path $VenvPath "Scripts\python.exe"
$ActivateScript = Join-Path $VenvPath "Scripts\Activate.ps1"

if (-not (Test-Path $PythonExe)) {
    throw "Virtual environment Python not found: $PythonExe. Recreate it with: powershell -ExecutionPolicy Bypass -File .\scripts\reset_venv.ps1 -Force"
}
if (-not (Test-Path $ActivateScript)) {
    throw "Virtual environment activation script not found: $ActivateScript. The venv may be partially deleted; open a fresh PowerShell and run: powershell -ExecutionPolicy Bypass -File .\scripts\reset_venv.ps1 -Force"
}

$VenvPath = (Resolve-Path $VenvPath).Path
$PythonExe = (Resolve-Path $PythonExe).Path
$PythonInfo = Assert-Python311 -PythonPath $PythonExe
$ScriptsDir = Split-Path -Parent $PythonExe

$env:FZASTRO_PROJECT_ROOT = $ProjectRoot
$env:FZASTRO_BUILD_ROOT = $BuildRoot
$env:FZASTRO_PYTHON = $PythonExe
$env:VIRTUAL_ENV = $VenvPath

$PathParts = @($env:PATH -split ";" | Where-Object { $_ })
if ($PathParts -notcontains $ScriptsDir) {
    $env:PATH = ($ScriptsDir + ";" + $env:PATH)
}

Write-Host "Project root:        $ProjectRoot"
Write-Host "Virtual env:         $VenvPath"
Write-Host "Build root:          $BuildRoot"
Write-Host "FZASTRO_PYTHON:      $env:FZASTRO_PYTHON"
Write-Host "Python version:      $($PythonInfo.Version)"
Write-Host "FZASTRO_BUILD_ROOT:  $env:FZASTRO_BUILD_ROOT"
Write-Host ""
Write-Host "Activating virtual environment..."

. $ActivateScript

# Re-assert project-specific variables after Activate.ps1 updates shell state.
$env:FZASTRO_PROJECT_ROOT = $ProjectRoot
$env:FZASTRO_BUILD_ROOT = $BuildRoot
$env:FZASTRO_PYTHON = $PythonExe

Write-Host ""
Write-Host "Virtual environment active."
Write-Host "Deploy command: .\scripts\deploy.ps1"
