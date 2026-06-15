param(
    [string]$ProjectRoot = $PSScriptRoot,
    [string]$PythonExe = $env:FZASTRO_PYTHON,
    [string]$BuildRoot = "",
    [switch]$SkipDependencyInstall,
    [switch]$SkipFormat,
    [switch]$SkipValidationPrompt,
    [switch]$RunValidation,
    [switch]$CleanOnly,
    [switch]$VerboseOutput
)

$ErrorActionPreference = "Stop"

function Initialize-StageProgress {
    param(
        [string]$Activity,
        [int]$TotalSteps
    )
    $script:ProgressActivity = $Activity
    $script:ProgressTotal = [Math]::Max(1, $TotalSteps)
    $script:ProgressStep = 0
    Write-Progress -Activity $script:ProgressActivity -Status "Starting" -PercentComplete 0
}

function Show-StageStep {
    param([string]$Status)
    $script:ProgressStep += 1
    $percent = [Math]::Min(100, [Math]::Round(($script:ProgressStep / $script:ProgressTotal) * 100))
    Write-Progress -Activity $script:ProgressActivity -Status ("{0}/{1} {2}" -f $script:ProgressStep, $script:ProgressTotal, $Status) -PercentComplete $percent
    Write-Host ("[{0}/{1}] {2}" -f $script:ProgressStep, $script:ProgressTotal, $Status)
}

function Complete-StageProgress {
    if ($script:ProgressActivity) {
        Write-Progress -Activity $script:ProgressActivity -Completed
    }
}

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
        throw "Python interpreter is not usable: $PythonPath. Recreate the environment with: powershell -ExecutionPolicy Bypass -File .\reset_venv.ps1"
    }
    if ($info.Major -ne 3 -or $info.Minor -ne 11) {
        throw ("FZAstro AI build/deploy requires Python 3.11. Found Python {0} at {1}. Recreate the environment with: powershell -ExecutionPolicy Bypass -File .\reset_venv.ps1" -f $info.Version, $info.Executable)
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

    throw "Python 3.11 environment not found. Run: powershell -ExecutionPolicy Bypass -File .\reset_venv.ps1"
}

function Set-FZAstroBuildEnvironment {
    param(
        [string]$PythonPath,
        [string]$Root,
        [string]$BuildPath
    )

    $env:FZASTRO_PROJECT_ROOT = $Root
    $env:FZASTRO_BUILD_ROOT = $BuildPath

    if ($PythonPath) {
        if (Test-Path $PythonPath) {
            $PythonPath = (Resolve-Path $PythonPath).Path
        }
        $env:FZASTRO_PYTHON = $PythonPath

        $ScriptsDir = Split-Path -Parent $PythonPath
        $PossibleVenv = Split-Path -Parent $ScriptsDir
        if ($PossibleVenv -and (Test-Path (Join-Path $PossibleVenv "pyvenv.cfg"))) {
            $env:VIRTUAL_ENV = $PossibleVenv
            $PathParts = @($env:PATH -split ";" | Where-Object { $_ })
            if ($PathParts -notcontains $ScriptsDir) {
                $env:PATH = ($ScriptsDir + ";" + $env:PATH)
            }
        }
    }
}

function ConvertTo-NativeArgumentLine {
    param([string[]]$Arguments)

    $quotedArguments = @()
    foreach ($argument in $Arguments) {
        if ($null -eq $argument) { continue }
        $value = [string]$argument
        if ($value.Length -eq 0) {
            $quotedArguments += '""'
            continue
        }
        if ($value -notmatch '[\s"`]') {
            $quotedArguments += $value
            continue
        }
        $escaped = $value.Replace('"', '\"')
        if ($escaped.EndsWith('\')) {
            $escaped = $escaped + '\'
        }
        $quotedArguments += '"' + $escaped + '"'
    }

    return ($quotedArguments -join " ")
}

function Invoke-NativeCommand {
    param(
        [string]$Description,
        [string]$CommandPath,
        [string[]]$Arguments,
        [string]$LogPath,
        [switch]$VerboseOutput
    )

    $logDirectory = Split-Path -Parent $LogPath
    if ($logDirectory) {
        New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
    }

    $argumentLine = ConvertTo-NativeArgumentLine -Arguments $Arguments
    Add-Content -Path $LogPath -Value "`n[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Description"
    Add-Content -Path $LogPath -Value ("COMMAND: {0} {1}" -f $CommandPath, $argumentLine)

    $tempBase = Join-Path $logDirectory ([Guid]::NewGuid().ToString("N"))
    $stdoutPath = "$tempBase.stdout.log"
    $stderrPath = "$tempBase.stderr.log"

    try {
        $process = Start-Process -FilePath $CommandPath -ArgumentList $argumentLine -NoNewWindow -Wait -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
        $stdoutText = ""
        $stderrText = ""
        if (Test-Path $stdoutPath) { $stdoutText = Get-Content -Path $stdoutPath -Raw -ErrorAction SilentlyContinue }
        if (Test-Path $stderrPath) { $stderrText = Get-Content -Path $stderrPath -Raw -ErrorAction SilentlyContinue }

        if ($stdoutText) {
            Add-Content -Path $LogPath -Value "`n[stdout]"
            Add-Content -Path $LogPath -Value $stdoutText
            if ($VerboseOutput) { Write-Host $stdoutText }
        }
        if ($stderrText) {
            Add-Content -Path $LogPath -Value "`n[stderr]"
            Add-Content -Path $LogPath -Value $stderrText
            if ($VerboseOutput) { Write-Host $stderrText }
        }

        Add-Content -Path $LogPath -Value ("EXIT CODE: {0}" -f $process.ExitCode)
        return [int]$process.ExitCode
    }
    finally {
        Remove-Item -Force $stdoutPath, $stderrPath -ErrorAction SilentlyContinue
    }
}

function Invoke-LoggedCommand {
    param(
        [string]$Description,
        [string]$CommandPath,
        [string[]]$Arguments,
        [string]$LogPath,
        [switch]$VerboseOutput
    )

    $exitCode = Invoke-NativeCommand -Description $Description -CommandPath $CommandPath -Arguments $Arguments -LogPath $LogPath -VerboseOutput:$VerboseOutput
    if ($exitCode -ne 0) {
        throw "$Description failed with exit code $exitCode. See log: $LogPath"
    }
}


$ProjectRoot = (Resolve-Path $ProjectRoot).Path
$BuildRoot = Resolve-BuildRootPath -RequestedBuildRoot $BuildRoot -Root $ProjectRoot
$ResolvedPython = Resolve-PythonExecutable -RequestedPython $PythonExe -Root $ProjectRoot
Set-FZAstroBuildEnvironment -PythonPath $ResolvedPython -Root $ProjectRoot -BuildPath $BuildRoot
$BuildScript = Join-Path $ProjectRoot "build_exe.ps1"
$LogDir = Join-Path $BuildRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$CleanLog = Join-Path $LogDir "clean_build.log"
Set-Content -Path $CleanLog -Value "FZAstro AI clean/build log" -Encoding UTF8

Write-Host "FZAstro AI clean/build workflow"
Write-Host "Logs: $LogDir"
Initialize-StageProgress -Activity "Clean/build" -TotalSteps 4

Show-StageStep "Clean build output"
Remove-Item -Recurse -Force $BuildRoot -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Content -Path $CleanLog -Value "FZAstro AI clean/build log" -Encoding UTF8

Show-StageStep "Clean Python caches"
Get-ChildItem -Path $ProjectRoot -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path $ProjectRoot -Recurse -Directory -Filter ".pytest_cache" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path $ProjectRoot -Recurse -File -Filter "*.pyc" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue

if ($CleanOnly) {
    Show-StageStep "Clean only requested"
    Complete-StageProgress
    Write-Host "CleanOnly was set, so the build step was skipped."
    return
}

if (-not (Test-Path $BuildScript)) {
    throw "Build script not found: $BuildScript"
}

Show-StageStep "Starting build_exe.ps1 automatically"

$BuildParams = @{
    ProjectRoot = $ProjectRoot
    BuildRoot = $BuildRoot
}

if ($ResolvedPython) { $BuildParams["PythonExe"] = $ResolvedPython }
if ($SkipDependencyInstall) { $BuildParams["SkipDependencyInstall"] = $true }
if ($SkipFormat) { $BuildParams["SkipFormat"] = $true }
if ($SkipValidationPrompt) { $BuildParams["SkipValidationPrompt"] = $true }
if ($RunValidation) { $BuildParams["RunValidation"] = $true }
if ($VerboseOutput) { $BuildParams["VerboseOutput"] = $true }

& $BuildScript @BuildParams
if (-not $?) { throw "Build script failed." }
Show-StageStep "Clean/build workflow complete"
Complete-StageProgress
