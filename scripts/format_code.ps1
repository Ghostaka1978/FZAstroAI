param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$PythonExe = $env:FZASTRO_PYTHON,
    [switch]$Check
)

$ErrorActionPreference = "Stop"


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
$ResolvedPython = Resolve-PythonExecutable -RequestedPython $PythonExe -Root $ProjectRoot

$targets = @(
    (Join-Path $ProjectRoot "main.py"),
    (Join-Path $ProjectRoot "fzastro_ai"),
    (Join-Path $ProjectRoot "tests")
)

Write-Host "========================================"
if ($Check) { Write-Host "FZAstro AI Black formatting check" } else { Write-Host "FZAstro AI Black formatting" }
Write-Host "========================================"
Write-Host "Project root: $ProjectRoot"
Write-Host "Python:       $ResolvedPython"
Write-Host ""

if ($Check) {
    & $ResolvedPython -m black --check --workers 1 @targets
}
else {
    & $ResolvedPython -m black --workers 1 @targets
}

if ($LASTEXITCODE -ne 0) {
    if ($Check) { throw "Black formatting check failed. Run .\scripts\format_code.ps1 before release." }
    throw "Black formatting failed."
}

if ($Check) { Write-Host "Black formatting check passed." } else { Write-Host "Black formatting complete." }
