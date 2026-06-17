param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$PythonExe = $env:FZASTRO_PYTHON,
    [string]$BuildRoot = "",
    [switch]$SkipDependencyInstall,
    [switch]$SkipPlaywrightBrowserInstall,
    [switch]$SkipFormat,
    [switch]$SkipValidationPrompt,
    [switch]$RunValidation,
    [switch]$VerboseOutput
)

$ErrorActionPreference = "Stop"
$ScriptsRoot = $PSScriptRoot

function Write-BuildLog {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [Parameter(Mandatory=$false)][AllowNull()][object]$Value
    )

    $text = [string]$Value
    $dir = Split-Path -Parent $Path
    if ($dir -and -not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }

    for ($i = 1; $i -le 40; $i++) {
        try {
            $bytes = [System.Text.Encoding]::UTF8.GetBytes($text + [Environment]::NewLine)
            $fs = [System.IO.File]::Open(
                $Path,
                [System.IO.FileMode]::Append,
                [System.IO.FileAccess]::Write,
                [System.IO.FileShare]::ReadWrite
            )
            try {
                $fs.Write($bytes, 0, $bytes.Length)
            } finally {
                $fs.Dispose()
            }
            return
        } catch {
            Start-Sleep -Milliseconds (150 + ($i * 25))
        }
    }

    # Final fallback: do not fail the whole build only because Dropbox locked the log.
    Write-Warning "Could not write to build log after retries: $Path"
}



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
    Write-BuildLog -Path $LogPath -Value "`n[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Description"
    Write-BuildLog -Path $LogPath -Value ("COMMAND: {0} {1}" -f $CommandPath, $argumentLine)

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
            Write-BuildLog -Path $LogPath -Value "`n[stdout]"
            Write-BuildLog -Path $LogPath -Value $stdoutText
            if ($VerboseOutput) { Write-Host $stdoutText }
        }
        if ($stderrText) {
            Write-BuildLog -Path $LogPath -Value "`n[stderr]"
            Write-BuildLog -Path $LogPath -Value $stderrText
            if ($VerboseOutput) { Write-Host $stderrText }
        }

        Write-BuildLog -Path $LogPath -Value ("EXIT CODE: {0}" -f $process.ExitCode)
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



function Invoke-PythonSnippet {
    param(
        [string]$PythonExe,
        [string]$Code,
        [string]$Name = "snippet"
    )

    $tempDir = Join-Path ([System.IO.Path]::GetTempPath()) "fzastroai_build_checks"
    New-Item -ItemType Directory -Force -Path $tempDir | Out-Null
    $tempFile = Join-Path $tempDir ("{0}_{1}.py" -f $Name, ([Guid]::NewGuid().ToString("N")))

    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($tempFile, $Code, $utf8NoBom)

    try {
        $snippetLogPath = $script:WorkflowLogPath
        if (-not $snippetLogPath) {
            $snippetLogPath = Join-Path $tempDir "$Name.log"
        }
        $snippetVerboseOutput = (-not $script:QuietOutput) -or $VerboseOutput
        $script:PythonSnippetExitCode = Invoke-NativeCommand -Description "Python snippet: $Name" -CommandPath $PythonExe -Arguments @($tempFile) -LogPath $snippetLogPath -VerboseOutput:$snippetVerboseOutput
    }
    finally {
        Remove-Item -Force $tempFile -ErrorAction SilentlyContinue
    }
}


function Resolve-PlaywrightLocalBrowsersDir {
    param([string]$PythonExe)

    $CandidatePackageDirs = @()

    # Fast path for the normal virtualenv layout. The build diagnostic in
    # Windows commonly reports:
    #   <venv>\Lib\site-packages\playwright\__init__.py
    # so the package-local browser directory is deterministic from the venv.
    if ($PythonExe) {
        try {
            $ResolvedPythonExe = (Resolve-Path -LiteralPath $PythonExe -ErrorAction Stop).Path
        }
        catch {
            $ResolvedPythonExe = $PythonExe
        }

        $PythonExeDir = Split-Path -Parent $ResolvedPythonExe
        $PotentialVenvRoot = Split-Path -Parent $PythonExeDir
        if ($PotentialVenvRoot) {
            $CandidatePackageDirs += (Join-Path $PotentialVenvRoot "Lib\site-packages\playwright")
        }
    }

    # Import-based path resolution, executed from a temp file rather than
    # python -c. This avoids Windows PowerShell quoting/newline edge cases and
    # gives us exactly the path reported by importlib for the build Python.
    $PythonCode = @'
import importlib.util
import pathlib
import site
import sysconfig

paths = []

def add(value):
    if not value:
        return
    try:
        path = pathlib.Path(value)
    except Exception:
        return
    if path.name == "playwright":
        paths.append(path)
    else:
        paths.append(path / "playwright")

spec = importlib.util.find_spec("playwright")
if spec is not None:
    for location in spec.submodule_search_locations or []:
        add(location)
    if spec.origin:
        add(pathlib.Path(spec.origin).parent)

for key in ("purelib", "platlib"):
    add(sysconfig.get_paths().get(key))

try:
    for location in site.getsitepackages():
        add(location)
except Exception:
    pass

try:
    add(site.getusersitepackages())
except Exception:
    pass

seen = set()
for path in paths:
    text = str(path)
    key = text.lower()
    if key in seen:
        continue
    seen.add(key)
    print(text)
'@

    $TempPythonFile = Join-Path ([System.IO.Path]::GetTempPath()) ("fzastro_playwright_resolve_{0}.py" -f ([System.Guid]::NewGuid().ToString("N")))
    try {
        $Utf8NoBom = New-Object System.Text.UTF8Encoding $false
        [System.IO.File]::WriteAllText($TempPythonFile, $PythonCode, $Utf8NoBom)
        $PathOutput = & $PythonExe $TempPythonFile 2>$null
        if ($LASTEXITCODE -eq 0 -and $PathOutput) {
            foreach ($Line in $PathOutput) {
                if ($Line) {
                    $CandidatePackageDirs += $Line.Trim()
                }
            }
        }
    }
    catch {
        # Keep the venv-derived fallback above.
    }
    finally {
        Remove-Item -Force $TempPythonFile -ErrorAction SilentlyContinue
    }

    $SeenPackageDirs = @{}
    foreach ($PackageDir in $CandidatePackageDirs) {
        if (-not $PackageDir) { continue }
        $PackageDir = $PackageDir.Trim()
        if (-not $PackageDir) { continue }

        try {
            $PackageDir = [System.IO.Path]::GetFullPath($PackageDir)
        }
        catch {
            continue
        }

        $Key = $PackageDir.ToLowerInvariant()
        if ($SeenPackageDirs.ContainsKey($Key)) { continue }
        $SeenPackageDirs[$Key] = $true

        if (Test-Path -LiteralPath $PackageDir) {
            $DriverPackageDir = Join-Path $PackageDir "driver\package"
            return (Join-Path $DriverPackageDir ".local-browsers")
        }
    }

    return ""
}


function Resolve-PlaywrightCacheBrowsersDir {
    param([string]$PythonExe)

    $PythonCode = @'
import os
import pathlib
import sys

env_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
if env_path and env_path != "0":
    print(str(pathlib.Path(env_path).expanduser()))
elif sys.platform == "win32":
    print(str(pathlib.Path(os.environ.get("LOCALAPPDATA", pathlib.Path.home() / "AppData" / "Local")) / "ms-playwright"))
elif sys.platform == "darwin":
    print(str(pathlib.Path.home() / "Library" / "Caches" / "ms-playwright"))
else:
    print(str(pathlib.Path(os.environ.get("XDG_CACHE_HOME", pathlib.Path.home() / ".cache")) / "ms-playwright"))
'@

    $TempPythonFile = Join-Path ([System.IO.Path]::GetTempPath()) ("fzastro_playwright_cache_{0}.py" -f ([System.Guid]::NewGuid().ToString("N")))
    try {
        $Utf8NoBom = New-Object System.Text.UTF8Encoding $false
        [System.IO.File]::WriteAllText($TempPythonFile, $PythonCode, $Utf8NoBom)
        $PathOutput = & $PythonExe $TempPythonFile 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $PathOutput) { return "" }
        return ($PathOutput | Select-Object -Last 1).Trim()
    }
    catch {
        return ""
    }
    finally {
        Remove-Item -Force $TempPythonFile -ErrorAction SilentlyContinue
    }
}


function Test-PlaywrightChromiumPayload {
    param([string]$BrowsersDir)

    if (-not $BrowsersDir -or -not (Test-Path -LiteralPath $BrowsersDir)) { return $false }

    $ChromiumDirs = @(
        Get-ChildItem -LiteralPath $BrowsersDir -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^chromium-' -or $_.Name -match '^chromium_headless_shell-' }
    )
    if ($ChromiumDirs.Count -eq 0) { return $false }

    $BrowserExecutables = @(
        Get-ChildItem -LiteralPath $BrowsersDir -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -in @("chrome.exe", "chrome", "headless_shell.exe", "headless_shell", "chrome-headless-shell.exe", "chrome-headless-shell") }
    )

    return ($BrowserExecutables.Count -gt 0)
}


function Copy-PlaywrightCacheToLocalBrowsers {
    param(
        [string]$SourceDir,
        [string]$DestinationDir
    )

    if (-not $SourceDir -or -not (Test-Path -LiteralPath $SourceDir)) { return $false }

    $BrowserDirs = @(
        Get-ChildItem -LiteralPath $SourceDir -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^(chromium|chromium_headless_shell|ffmpeg)-' }
    )
    if ($BrowserDirs.Count -eq 0) { return $false }

    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
    foreach ($BrowserDir in $BrowserDirs) {
        Copy-Item -LiteralPath $BrowserDir.FullName -Destination $DestinationDir -Recurse -Force
    }

    return $true
}


function Install-PlaywrightChromiumBrowser {
    param(
        [string]$PythonExe,
        [string]$BuildLog,
        [switch]$VerboseOutput
    )

    $LocalBrowsersDir = Resolve-PlaywrightLocalBrowsersDir -PythonExe $PythonExe
    if (-not $LocalBrowsersDir) {
        $PlaywrightDiagnostic = & $PythonExe -c "import importlib.util, sys; spec = importlib.util.find_spec('playwright'); print('python=' + sys.executable); print('playwright_spec=' + repr(spec))" 2>&1
        throw "Unable to resolve Playwright package-local browser directory. Dependency restore may not have installed Playwright into the build Python. Python: $PythonExe. Diagnostic: $PlaywrightDiagnostic"
    }

    $PreviousPlaywrightBrowsersPath = $env:PLAYWRIGHT_BROWSERS_PATH
    try {
        # Package Chromium into Playwright's package-local .local-browsers
        # directory so PyInstaller can include it in the frozen app instead of
        # depending on the builder's user-cache directory. Frozen Playwright
        # automatically looks here by setting PLAYWRIGHT_BROWSERS_PATH=0.
        $env:PLAYWRIGHT_BROWSERS_PATH = "0"
        Invoke-LoggedCommand -Description "Playwright Chromium install" -CommandPath $PythonExe -Arguments @("-m", "playwright", "install", "chromium") -LogPath $BuildLog -VerboseOutput:$VerboseOutput
    }
    finally {
        if ($null -eq $PreviousPlaywrightBrowsersPath) {
            Remove-Item Env:\PLAYWRIGHT_BROWSERS_PATH -ErrorAction SilentlyContinue
        }
        else {
            $env:PLAYWRIGHT_BROWSERS_PATH = $PreviousPlaywrightBrowsersPath
        }
    }

    if (Test-PlaywrightChromiumPayload -BrowsersDir $LocalBrowsersDir) {
        Write-BuildLog -Path $BuildLog -Value "Playwright package-local Chromium payload found: $LocalBrowsersDir"
        return $LocalBrowsersDir
    }

    # Some environments report a successful Playwright install but still place
    # the browser files in the normal ms-playwright cache. Recover by copying
    # the current Chromium payload into package-local .local-browsers, then
    # fail loudly if the payload is still unavailable.
    $CacheBrowsersDir = Resolve-PlaywrightCacheBrowsersDir -PythonExe $PythonExe
    if (Copy-PlaywrightCacheToLocalBrowsers -SourceDir $CacheBrowsersDir -DestinationDir $LocalBrowsersDir) {
        Write-BuildLog -Path $BuildLog -Value "Copied Playwright browser cache from $CacheBrowsersDir to package-local $LocalBrowsersDir."
    }

    if (Test-PlaywrightChromiumPayload -BrowsersDir $LocalBrowsersDir) {
        Write-Host "Recovered Playwright package-local Chromium payload: $LocalBrowsersDir"
        return $LocalBrowsersDir
    }

    throw "Playwright Chromium install completed, but package-local .local-browsers was not created at $LocalBrowsersDir and no recoverable Chromium payload was found in $CacheBrowsersDir. Re-run with -VerboseOutput and check $BuildLog. Fully bundled browser support requires a package-local Playwright Chromium payload."
}



$ProjectRoot = (Resolve-Path $ProjectRoot).Path
$BuildRoot = Resolve-BuildRootPath -RequestedBuildRoot $BuildRoot -Root $ProjectRoot
$ResolvedPython = Resolve-PythonExecutable -RequestedPython $PythonExe -Root $ProjectRoot
Set-FZAstroBuildEnvironment -PythonPath $ResolvedPython -Root $ProjectRoot -BuildPath $BuildRoot
Set-Location $ProjectRoot
if ($env:PYTHONPATH) {
    $PythonPathParts = @($env:PYTHONPATH -split ";" | Where-Object { $_ })
    if ($PythonPathParts -notcontains $ProjectRoot) {
        $env:PYTHONPATH = ($ProjectRoot + ";" + $env:PYTHONPATH)
    }
}
else {
    $env:PYTHONPATH = $ProjectRoot
}

$DistDir = Join-Path $BuildRoot "dist"
$WorkDir = Join-Path $BuildRoot "build"
$SpecDir = Join-Path $BuildRoot "spec"
$ReleaseDir = Join-Path $BuildRoot "release"

$MainScript = Join-Path $ProjectRoot "main.py"
$IconPath = Join-Path $ProjectRoot "favicon.ico"
$RequirementsFile = Join-Path $ProjectRoot "requirements.txt"
$VersionFile = Join-Path $ProjectRoot "VERSION.txt"
$FzastroToolsDir = Join-Path $ProjectRoot "fzastro_ai\astro_tools\fzastro"
$FzastroToolsDestination = "fzastro_ai\astro_tools\fzastro"
$FinalExe = Join-Path $DistDir "FZAstroAI.exe"
$ReleaseExe = Join-Path $ReleaseDir "FZAstroAI.exe"

$LogDir = Join-Path $BuildRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$BuildLog = Join-Path $LogDir "build_exe.log"
Set-Content -Path $BuildLog -Value "FZAstro AI build log" -Encoding UTF8
$script:QuietOutput = -not $VerboseOutput
$script:WorkflowLogPath = $BuildLog

Write-Host "FZAstro AI Version 2 EXE Build"
Write-Host "Python: $ResolvedPython"
Write-Host "Logs:   $BuildLog"
Initialize-StageProgress -Activity "Build EXE" -TotalSteps 15
Show-StageStep "Preflight checks"

if (-not (Test-Path $MainScript)) { throw "Main script not found: $MainScript" }
if (-not (Test-Path $IconPath)) { throw "Icon file not found: $IconPath" }
if (-not (Test-Path $RequirementsFile)) { throw "requirements.txt not found: $RequirementsFile" }
if (-not (Test-Path $FzastroToolsDir)) { throw "FZASTRO tools folder not found: $FzastroToolsDir" }
foreach ($FzastroFile in @("script.py", "imagefetch.py", "see.py", "target.py", "solarsystem.py")) {
    $FzastroPath = Join-Path $FzastroToolsDir $FzastroFile
    if (-not (Test-Path $FzastroPath)) { throw "FZASTRO tool script not found: $FzastroPath" }
}

Show-StageStep "Stop running app instances"
Stop-Process -Name "FZAstroAI" -Force -ErrorAction SilentlyContinue

Show-StageStep "Prepare build folders"
Remove-Item -Recurse -Force $DistDir -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force $WorkDir -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force $SpecDir -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force $ReleaseDir -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType Directory -Force -Path $DistDir | Out-Null
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
New-Item -ItemType Directory -Force -Path $SpecDir | Out-Null
New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null

Set-FZAstroBuildEnvironment -PythonPath $ResolvedPython -Root $ProjectRoot -BuildPath $BuildRoot

Show-StageStep "Install/update dependencies"
if (-not $SkipDependencyInstall) {
    Invoke-LoggedCommand -Description "pip upgrade" -CommandPath $ResolvedPython -Arguments @("-m", "pip", "install", "--upgrade", "pip") -LogPath $BuildLog -VerboseOutput:$VerboseOutput
    Invoke-LoggedCommand -Description "dependency install" -CommandPath $ResolvedPython -Arguments @("-m", "pip", "install", "-r", $RequirementsFile) -LogPath $BuildLog -VerboseOutput:$VerboseOutput
}
else {
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    Write-BuildLog -Path $BuildLog -Value "Dependency install skipped."
}

Show-StageStep "Install Playwright Chromium browser"
$PlaywrightLocalBrowsersDir = ""
if (-not $SkipPlaywrightBrowserInstall) {
    $PlaywrightLocalBrowsersDir = Install-PlaywrightChromiumBrowser -PythonExe $ResolvedPython -BuildLog $BuildLog -VerboseOutput:$VerboseOutput
}
else {
    Write-Warning "Playwright Chromium browser install skipped. Frozen webpage screenshot/extraction will rely on installed Edge/Chrome fallback."
    Write-BuildLog -Path $BuildLog -Value "Playwright Chromium browser install skipped."
}

Show-StageStep "Formatting source with Black before build"
if (-not $SkipFormat) {
    Invoke-LoggedCommand -Description "Black formatting" -CommandPath $ResolvedPython -Arguments @("-m", "black", "--workers", "1", $MainScript, (Join-Path $ProjectRoot "fzastro_ai"), (Join-Path $ProjectRoot "tests")) -LogPath $BuildLog -VerboseOutput:$VerboseOutput
}
else {
    Write-Warning "Black formatting skipped. Run .\scripts\format_code.ps1 before release."
}
Show-StageStep "Compile source"
Invoke-LoggedCommand -Description "Python compile check" -CommandPath $ResolvedPython -Arguments @("-m", "compileall", "-q", $ProjectRoot) -LogPath $BuildLog -VerboseOutput:$VerboseOutput

Show-StageStep "Run automated tests"
Invoke-LoggedCommand -Description "Automated tests" -CommandPath $ResolvedPython -Arguments @("-m", "pytest", (Join-Path $ProjectRoot "tests")) -LogPath $BuildLog -VerboseOutput:$VerboseOutput

Show-StageStep "Check startup imports"
$StartupImportCheck = @'
import importlib
importlib.import_module("fzastro_ai")
importlib.import_module("fzastro_ai.workers")
importlib.import_module("fzastro_ai.app")
print("startup imports ok")
'@
Invoke-PythonSnippet -PythonExe $ResolvedPython -Code $StartupImportCheck -Name "startup_import_check"
if ($script:PythonSnippetExitCode -ne 0) { throw "Startup import check failed. See log: $BuildLog" }

Show-StageStep "Check critical imports"
$ImportCheck = @'
import importlib
modules = [
    "PySide6", "openai", "requests", "bs4", "ddgs", "playwright",
    "markdown", "pygments", "PyPDF2", "fitz", "PIL", "pytesseract", "openpyxl", "PyInstaller",
    "astropy", "astroquery", "numpy", "matplotlib", "skyfield", "black",
    "vosk", "sounddevice"
]
missing = []
for name in modules:
    try:
        importlib.import_module(name)
    except Exception as exc:
        missing.append(f"{name}: {exc}")
if missing:
    raise SystemExit("Missing/broken imports:\n" + "\n".join(missing))
print("critical imports ok")
'@
Invoke-PythonSnippet -PythonExe $ResolvedPython -Code $ImportCheck -Name "critical_import_check"
if ($script:PythonSnippetExitCode -ne 0) { throw "Critical import check failed." }

Show-StageStep "Check astronomy package data"
$AstroDataCheck = @'
import importlib.resources as resources
checks = [
    ("astroquery", ("CITATION",)),
    ("astroquery.simbad", ("data", "query_criteria_fields.json")),
    ("astropy.samp", ("data", "astropy_icon.png")),
    ("astropy.samp", ("data", "crossdomain.xml")),
    ("astropy.samp", ("data", "clientaccesspolicy.xml")),
]
missing = []
for package, parts in checks:
    try:
        path = resources.files(package).joinpath(*parts)
        if not path.is_file():
            missing.append(f"{package}/{'/'.join(parts)}")
    except Exception as exc:
        missing.append(f"{package}/{'/'.join(parts)}: {exc}")
if missing:
    print("optional astronomy package data missing:")
    for item in missing:
        print(" - " + item)
    raise SystemExit(2)
print("astronomy package data ok")
'@
Invoke-PythonSnippet -PythonExe $ResolvedPython -Code $AstroDataCheck -Name "astro_data_check"
if ($script:PythonSnippetExitCode -ne 0) {
    Write-Warning "Some optional astronomy package data was not found in the build Python. Build will continue and bundle project fallbacks where available."
}

function Resolve-AstropySampDataFile {
    param(
        [string]$FileName,
        [string]$FallbackPath
    )

    $PythonCode = "import importlib.resources as r; p=r.files('astropy.samp').joinpath('data', '$FileName'); print(str(p) if p.is_file() else '')"
    $PathOutput = & $ResolvedPython -c $PythonCode
    $PackagePath = ($PathOutput | Select-Object -Last 1).Trim()
    if ($PackagePath -and (Test-Path -LiteralPath $PackagePath)) { return $PackagePath }
    if ($FallbackPath -and (Test-Path -LiteralPath $FallbackPath)) {
        Write-Warning "Using bundled fallback Astropy SAMP data file: $FileName"
        return $FallbackPath
    }
    throw "Astropy SAMP data file not found and no fallback exists: $FileName"
}

$FallbackResourcesDir = Join-Path $ProjectRoot "fzastro_ai"
$FallbackResourcesDir = Join-Path $FallbackResourcesDir "resources"
$FallbackSampDir = Join-Path $FallbackResourcesDir "astropy_samp"
$FlatAstropyIconPath = Join-Path $FallbackResourcesDir "astropy_icon.png"
if (-not (Test-Path $FlatAstropyIconPath)) {
    $FlatAstropyIconPath = Join-Path $FallbackSampDir "astropy_icon.png"
}
if (-not (Test-Path $FlatAstropyIconPath)) {
    throw "Astropy icon fallback not found: $FlatAstropyIconPath"
}

$AstropySampIconPath = Resolve-AstropySampDataFile -FileName "astropy_icon.png" -FallbackPath (Join-Path $FallbackSampDir "astropy_icon.png")
$AstropySampCrossdomainPath = Resolve-AstropySampDataFile -FileName "crossdomain.xml" -FallbackPath (Join-Path $FallbackSampDir "crossdomain.xml")
$AstropySampClientPolicyPath = Resolve-AstropySampDataFile -FileName "clientaccesspolicy.xml" -FallbackPath (Join-Path $FallbackSampDir "clientaccesspolicy.xml")

function Resolve-AstroquerySimbadDataFile {
    param(
        [string]$FileName
    )

    $PythonCode = "import importlib.resources as r; p=r.files('astroquery.simbad').joinpath('data', '$FileName'); print(str(p) if p.is_file() else '')"
    $PathOutput = & $ResolvedPython -c $PythonCode
    $PackagePath = ($PathOutput | Select-Object -Last 1).Trim()
    if ($PackagePath -and (Test-Path -LiteralPath $PackagePath)) { return $PackagePath }
    throw "Astroquery SIMBAD data file not found: $FileName"
}

$AstroquerySimbadCriteriaPath = Resolve-AstroquerySimbadDataFile -FileName "query_criteria_fields.json"

$NinaTemplatesDir = Join-Path $ProjectRoot "fzastro_ai\resources\nina_templates"
$NinaSequenceTemplatePath = Join-Path $NinaTemplatesDir "osc_advanced_sequence_template.json"
if (-not (Test-Path -LiteralPath $NinaSequenceTemplatePath)) {
    throw "N.I.N.A. sequence template resource not found: $NinaSequenceTemplatePath"
}

if (-not $PlaywrightLocalBrowsersDir) {
    $PlaywrightLocalBrowsersDir = Resolve-PlaywrightLocalBrowsersDir -PythonExe $ResolvedPython
}

Show-StageStep "Resolve bundled resources"
Show-StageStep "Build one-file EXE"
Set-Location $ProjectRoot

$PyInstallerArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onefile",
    "--windowed",
    "--name", "FZAstroAI",
    "--icon", $IconPath,
    "--add-data", "$IconPath;.",
    "--add-data", "$FzastroToolsDir;$FzastroToolsDestination",
    "--add-data", "$FlatAstropyIconPath;fzastro_ai/resources",
    "--add-data", "$FallbackSampDir;fzastro_ai/resources/astropy_samp",
    "--add-data", "$AstropySampIconPath;astropy\samp\data",
    "--add-data", "$AstropySampCrossdomainPath;astropy\samp\data",
    "--add-data", "$AstropySampClientPolicyPath;astropy\samp\data",
    "--add-data", "$AstroquerySimbadCriteriaPath;astroquery\simbad\data",
    "--add-data", "$NinaTemplatesDir;fzastro_ai/resources/nina_templates",
    "--add-data", "$AstropySampIconPath;astropy\vo\samp\data",
    "--add-data", "$AstropySampCrossdomainPath;astropy\vo\samp\data",
    "--add-data", "$AstropySampClientPolicyPath;astropy\vo\samp\data",
    "--collect-data", "astroquery",
    "--collect-data", "astropy",
    "--collect-data", "skyfield",
    "--collect-data", "playwright",
    "--collect-all", "vosk",
    "--collect-all", "sounddevice",
    "--hidden-import", "vosk",
    "--hidden-import", "sounddevice",
    "--hidden-import", "_sounddevice",
    "--hidden-import", "_sounddevice_data",
    "--distpath", $DistDir,
    "--workpath", $WorkDir,
    "--specpath", $SpecDir,
    $MainScript
)

if ($PlaywrightLocalBrowsersDir -and (Test-Path -LiteralPath $PlaywrightLocalBrowsersDir)) {
    $PyInstallerArgs = @(
        $PyInstallerArgs[0..($PyInstallerArgs.Count - 2)]
        "--add-data"
        "$PlaywrightLocalBrowsersDir;playwright\driver\package\.local-browsers"
        $PyInstallerArgs[$PyInstallerArgs.Count - 1]
    )
}
elseif (-not $SkipPlaywrightBrowserInstall) {
    throw "Playwright package-local .local-browsers was expected but was not found: $PlaywrightLocalBrowsersDir"
}

Invoke-LoggedCommand -Description "PyInstaller build" -CommandPath $ResolvedPython -Arguments $PyInstallerArgs -LogPath $BuildLog -VerboseOutput:$VerboseOutput
if (-not (Test-Path $FinalExe)) { throw "Build finished but EXE was not found: $FinalExe" }

Show-StageStep "Prepare release folder"
Copy-Item -Force $FinalExe $ReleaseExe
Copy-Item -Force (Join-Path $ProjectRoot "README.md") $ReleaseDir -ErrorAction SilentlyContinue
$ReleaseValidationDoc = Join-Path $ProjectRoot "docs\RELEASE_VALIDATION.md"
if (-not (Test-Path $ReleaseValidationDoc)) { $ReleaseValidationDoc = Join-Path $ProjectRoot "RELEASE_VALIDATION.md" }
Copy-Item -Force $ReleaseValidationDoc (Join-Path $ReleaseDir "RELEASE_VALIDATION.md") -ErrorAction SilentlyContinue
Copy-Item -Force (Join-Path $ProjectRoot "docs\OFFLINE_VOICE_COMMANDS.md") (Join-Path $ReleaseDir "OFFLINE_VOICE_COMMANDS.md") -ErrorAction SilentlyContinue
Copy-Item -Force (Join-Path $ScriptsRoot "install_offline_voice.ps1") $ReleaseDir -ErrorAction SilentlyContinue
Copy-Item -Force $RequirementsFile $ReleaseDir -ErrorAction SilentlyContinue
Copy-Item -Force $VersionFile $ReleaseDir -ErrorAction SilentlyContinue

$Hash = (Get-FileHash $ReleaseExe -Algorithm SHA256).Hash
$SizeMB = [Math]::Round((Get-Item $ReleaseExe).Length / 1MB, 2)
$VersionText = "unknown"
if (Test-Path $VersionFile) {
    $VersionText = (Get-Content $VersionFile -Raw).Trim()
}
$ManifestPath = Join-Path $ReleaseDir "release_manifest.txt"
$Manifest = @"
FZAstro AI Imaging Production
Generated: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
ProjectRoot: $ProjectRoot
Python: $ResolvedPython
BuildRoot: $BuildRoot
Version: $VersionText
VoiceModelsRoot: $env:FZASTRO_VOICE_MODELS_DIR
VoskModel: $env:FZASTRO_VOSK_MODEL
EXE: $ReleaseExe
SizeMB: $SizeMB
SHA256: $Hash
"@
Set-Content -Path $ManifestPath -Value $Manifest -Encoding UTF8

Show-StageStep "Build complete"
Complete-StageProgress
Write-Host ""
Write-Host "BUILD COMPLETE"
Write-Host "EXE:      $ReleaseExe"
Write-Host "Size:     $SizeMB MB"
Write-Host "SHA256:   $Hash"
Write-Host "Manifest: $ManifestPath"
Write-Host "Log:      $BuildLog"
Write-Host ""
$ValidationScript = Join-Path $ScriptsRoot "validate_release.ps1"
$ValidationCommand = "powershell -ExecutionPolicy Bypass -File `"$ValidationScript`" -PythonExe `"$ResolvedPython`" -ExePath `"$ReleaseExe`" -KeepRunning"

Write-Host "Next validation command:"
Write-Host $ValidationCommand

$ShouldRunValidation = $false
if ($RunValidation) {
    $ShouldRunValidation = $true
}
elseif (-not $SkipValidationPrompt) {
    Write-Host ""
    $ValidationAnswer = Read-Host "Run release validation now? This will launch the EXE smoke test and keep it open for manual checks. [Y/N]"
    if ($ValidationAnswer -match "^(?i:y|yes)$") {
        $ShouldRunValidation = $true
    }
}
else {
    Write-Host "Validation prompt skipped."
}

if ($ShouldRunValidation) {
    if (-not (Test-Path $ValidationScript)) { throw "Validation script not found: $ValidationScript" }
    Write-Host ""
    Write-Host "Starting validate_release.ps1..."
    $ValidationParams = @{ ProjectRoot = $ProjectRoot; PythonExe = $ResolvedPython; BuildRoot = $BuildRoot; ExePath = $ReleaseExe; KeepRunning = $true }
    if ($VerboseOutput) { $ValidationParams["VerboseOutput"] = $true }
    & $ValidationScript @ValidationParams
    if (-not $?) { throw "Validation script failed." }
}
else {
    Write-Host "Validation not started. Run it later with the command above."
}

