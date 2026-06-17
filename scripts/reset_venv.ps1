param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$Python311Exe = "",
    [string]$VenvPath = "",
    [string]$BuildRoot = "",
    [switch]$SkipDependencyInstall,
    [switch]$Force
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

function Invoke-PythonVersionProbe {
    param(
        [string]$CommandPath,
        [string[]]$PrefixArguments = @()
    )

    try {
        $arguments = @($PrefixArguments) + @("-c", "import sys; print(f'{sys.executable}|{sys.version_info.major}|{sys.version_info.minor}|{sys.version_info.micro}')")
        $output = & $CommandPath @arguments 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $output) { return $null }
        $line = ($output | Select-Object -Last 1).Trim()
        $parts = $line -split "\|"
        if ($parts.Count -lt 4) { return $null }
        return [pscustomobject]@{
            Command = $CommandPath
            PrefixArguments = $PrefixArguments
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

function Find-Python311 {
    param([string]$RequestedPython)

    $candidateSpecs = @()
    if ($RequestedPython) {
        $candidateSpecs += [pscustomobject]@{ Command = $RequestedPython; Args = @() }
    }

    $pyLauncher = Get-Command "py" -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        $candidateSpecs += [pscustomobject]@{ Command = "py"; Args = @("-3.11") }
    }

    foreach ($name in @("python3.11", "python")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) {
            $candidateSpecs += [pscustomobject]@{ Command = $name; Args = @() }
        }
    }

    foreach ($spec in $candidateSpecs) {
        $command = $spec.Command
        if (Test-Path $command) {
            $command = (Resolve-Path $command).Path
        }
        $info = Invoke-PythonVersionProbe -CommandPath $command -PrefixArguments $spec.Args
        if ($info -and $info.Major -eq 3 -and $info.Minor -eq 11) {
            return $info
        }
    }

    throw "Python 3.11 was not found. Install Python 3.11, then rerun: powershell -ExecutionPolicy Bypass -File .\scripts\reset_venv.ps1"
}

function Test-IsPathInside {
    param(
        [string]$ChildPath,
        [string]$ParentPath
    )

    if (-not $ChildPath -or -not $ParentPath) { return $false }

    try {
        $child = [System.IO.Path]::GetFullPath($ChildPath).TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
        $parent = [System.IO.Path]::GetFullPath($ParentPath).TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
        return $child.StartsWith($parent, [System.StringComparison]::OrdinalIgnoreCase)
    }
    catch {
        return $false
    }
}

function Assert-VenvNotActive {
    param([string]$TargetVenvPath)

    $resolvedTarget = [System.IO.Path]::GetFullPath($TargetVenvPath).TrimEnd('\', '/')
    $activeVenv = $env:VIRTUAL_ENV
    $activePython = $null

    $pythonCommand = Get-Command "python" -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $activePython = $pythonCommand.Source
    }

    $envPointsAtTarget = $activeVenv -and (([System.IO.Path]::GetFullPath($activeVenv).TrimEnd('\', '/')) -ieq $resolvedTarget)
    $pythonInsideTarget = Test-IsPathInside -ChildPath $activePython -ParentPath $resolvedTarget

    if ($envPointsAtTarget -or $pythonInsideTarget) {
        throw @"
Cannot reset .venv while it is active in this PowerShell session.

Safe recovery:
  1. Run: deactivate
  2. Close this terminal completely.
  3. Open a new PowerShell in the project folder.
  4. Run: powershell -ExecutionPolicy Bypass -File .\scripts\reset_venv.ps1 -Force

The previous reset may have partially deleted .venv. That is OK; rerun reset_venv.ps1 from a fresh non-venv shell.
"@
    }
}

function Remove-VenvSafely {
    param([string]$TargetVenvPath)

    if (-not (Test-Path $TargetVenvPath)) { return }

    Assert-VenvNotActive -TargetVenvPath $TargetVenvPath

    try {
        Remove-Item -Recurse -Force $TargetVenvPath
    }
    catch {
        throw @"
Could not remove the existing virtual environment: $TargetVenvPath

Most common cause: a terminal, IDE, Python process, or antivirus scanner still has a file open in .venv.

Close PyCharm/VS Code terminals and any running FZAstro/Python processes, then run again:
  powershell -ExecutionPolicy Bypass -File .\scripts\reset_venv.ps1 -Force

Original error:
$($_.Exception.Message)
"@
    }
}

$ProjectRoot = (Resolve-Path $ProjectRoot).Path
if (-not $VenvPath) {
    $VenvPath = Join-Path $ProjectRoot ".venv"
}
if (-not [System.IO.Path]::IsPathRooted($VenvPath)) {
    $VenvPath = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $VenvPath))
}
$BuildRoot = Resolve-BuildRootPath -RequestedBuildRoot $BuildRoot -Root $ProjectRoot
$RequirementsFile = Join-Path $ProjectRoot "requirements.txt"

if (-not (Test-Path $RequirementsFile)) {
    throw "requirements.txt not found: $RequirementsFile"
}

$python = Find-Python311 -RequestedPython $Python311Exe
Write-Host "Using Python $($python.Version): $($python.Executable)"

if (Test-Path $VenvPath) {
    Assert-VenvNotActive -TargetVenvPath $VenvPath

    if (-not $Force) {
        $answer = Read-Host "Remove and recreate existing virtual environment at $VenvPath? [y/N]"
        if ($answer -notmatch "^(y|yes)$") {
            throw "Reset cancelled."
        }
    }
    Remove-VenvSafely -TargetVenvPath $VenvPath
}

Write-Host "Creating virtual environment: $VenvPath"
$venvArgs = @($python.PrefixArguments) + @("-m", "venv", $VenvPath)
& $python.Command @venvArgs
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.11 venv creation failed."
}

$VenvPython = Join-Path $VenvPath "Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    throw "Virtual environment Python was not created: $VenvPython"
}

$versionCheck = Invoke-PythonVersionProbe -CommandPath $VenvPython
if (-not $versionCheck -or $versionCheck.Major -ne 3 -or $versionCheck.Minor -ne 11) {
    throw "Created virtual environment is not Python 3.11."
}

$env:FZASTRO_PROJECT_ROOT = $ProjectRoot
$env:FZASTRO_BUILD_ROOT = $BuildRoot
$env:FZASTRO_PYTHON = $VenvPython
$env:VIRTUAL_ENV = $VenvPath
$ScriptsDir = Split-Path -Parent $VenvPython
$PathParts = @($env:PATH -split ";" | Where-Object { $_ })
if ($PathParts -notcontains $ScriptsDir) {
    $env:PATH = ($ScriptsDir + ";" + $env:PATH)
}

if (-not $SkipDependencyInstall) {
    Write-Host "Installing/updating dependencies..."
    & $VenvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }
    & $VenvPython -m pip install -r $RequirementsFile
    if ($LASTEXITCODE -ne 0) { throw "dependency install failed." }
}
else {
    Write-Host "Dependency install skipped."
}

Write-Host ""
Write-Host "Python 3.11 virtual environment is ready."
Write-Host "Venv:           $VenvPath"
Write-Host "FZASTRO_PYTHON: $VenvPython"
Write-Host "Build root:     $BuildRoot"
Write-Host ""
Write-Host "Activate it in the current shell with:"
Write-Host ". .\scripts\activate_venv.ps1"
Write-Host ""
Write-Host "Then deploy with:"
Write-Host ".\scripts\deploy.ps1"
