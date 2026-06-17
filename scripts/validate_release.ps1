

param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$PythonExe = $env:FZASTRO_PYTHON,
    [string]$BuildRoot = "",
    [string]$ExePath = "",
    [switch]$KeepRunning,
    [switch]$SkipLaunch,
    [switch]$VerboseOutput
)

function Write-Ok {
    param([string]$Message)
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Write-Fail {
    param([string]$Message)
    Write-Host "[FAIL] $Message" -ForegroundColor Red
}

function Write-Warn {
    param([string]$Message)
    Write-Warning $Message
}


$ErrorActionPreference = "Stop"
$ScriptsRoot = $PSScriptRoot

function Write-ValidationLog {
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

    Write-Warning "Could not write to validation log after retries: $Path"
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
    Write-ValidationLog -Path $LogPath -Value "`n[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Description"
    Write-ValidationLog -Path $LogPath -Value ("COMMAND: {0} {1}" -f $CommandPath, $argumentLine)

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
            Write-ValidationLog -Path $LogPath -Value "`n[stdout]"
            Write-ValidationLog -Path $LogPath -Value $stdoutText
            if ($VerboseOutput) { Write-Host $stdoutText }
        }
        if ($stderrText) {
            Write-ValidationLog -Path $LogPath -Value "`n[stderr]"
            Write-ValidationLog -Path $LogPath -Value $stderrText
            if ($VerboseOutput) { Write-Host $stderrText }
        }

        Write-ValidationLog -Path $LogPath -Value ("EXIT CODE: {0}" -f $process.ExitCode)
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


function Assert-ReleaseArtifactHygiene {
    param([string]$ReleaseDirectory)

    if (-not $ReleaseDirectory -or -not (Test-Path $ReleaseDirectory)) {
        Write-Warning "Release directory not found for artifact hygiene check: $ReleaseDirectory"
        return
    }

    $unexpectedPatterns = @(
        "*.bak",
        "*.bak_*",
        "*.orig",
        "*.rej",
        "*.patch",
        "repair_*.ps1",
        "*_fixture_fix.patch",
        "llm_benchmark_history.json",
        "*.json.tmp"
    )

    $unexpectedFiles = @()
    foreach ($pattern in $unexpectedPatterns) {
        $unexpectedFiles += Get-ChildItem -Path $ReleaseDirectory -Recurse -File -Filter $pattern -ErrorAction SilentlyContinue
    }

    $uniqueUnexpectedFiles = @($unexpectedFiles | Sort-Object -Property FullName -Unique)
    if ($uniqueUnexpectedFiles.Count -gt 0) {
        $relativeFiles = $uniqueUnexpectedFiles | ForEach-Object {
            try {
                [System.IO.Path]::GetRelativePath($ReleaseDirectory, $_.FullName)
            }
            catch {
                $_.FullName
            }
        }
        throw ("Release folder contains development/repair artifacts: {0}" -f ($relativeFiles -join ", "))
    }

    Write-ValidationLog -Path $script:WorkflowLogPath -Value "Release artifact hygiene ok"
}


function Assert-ReleaseManifest {
    param(
        [string]$ReleaseDirectory,
        [string]$ExpectedExePath,
        [string]$ExpectedHash
    )

    if (-not $ReleaseDirectory -or -not (Test-Path $ReleaseDirectory)) {
        throw "Release directory not found: $ReleaseDirectory"
    }

    $requiredFiles = @(
        "FZAstroAI.exe",
        "README.md",
        "RELEASE_VALIDATION.md",
        "OFFLINE_VOICE_COMMANDS.md",
        "install_offline_voice.ps1",
        "requirements.txt",
        "VERSION.txt",
        "release_manifest.txt"
    )

    $missingFiles = @()
    foreach ($fileName in $requiredFiles) {
        $candidate = Join-Path $ReleaseDirectory $fileName
        if (-not (Test-Path $candidate)) {
            $missingFiles += $fileName
        }
    }

    if ($missingFiles.Count -gt 0) {
        throw ("Release folder is incomplete. Missing required files: {0}" -f ($missingFiles -join ", "))
    }

    $manifestPath = Join-Path $ReleaseDirectory "release_manifest.txt"
    $manifestText = Get-Content -Path $manifestPath -Raw
    foreach ($requiredField in @("Generated:", "ProjectRoot:", "Python:", "BuildRoot:", "Version:", "VoiceModelsRoot:", "VoskModel:", "EXE:", "SizeMB:", "SHA256:")) {
        if ($manifestText -notmatch [regex]::Escape($requiredField)) {
            throw "release_manifest.txt is missing required field: $requiredField"
        }
    }

    if ($ExpectedHash -and $manifestText -notmatch [regex]::Escape($ExpectedHash)) {
        throw "release_manifest.txt SHA256 does not match the validated EXE hash"
    }

    $expectedExeName = Split-Path -Leaf $ExpectedExePath
    if ($expectedExeName -and $manifestText -notmatch [regex]::Escape($expectedExeName)) {
        throw "release_manifest.txt does not reference the validated EXE: $expectedExeName"
    }

    Write-ValidationLog -Path $script:WorkflowLogPath -Value "Release manifest and required files ok"
}


function Assert-PyInstallerResourceConfiguration {
    param([string]$Root)

    $buildScript = Join-Path $ScriptsRoot "build_exe.ps1"
    $specFile = Join-Path $Root "FZAstroAI.spec"

    foreach ($requiredPath in @($buildScript, $specFile)) {
        if (-not (Test-Path $requiredPath)) {
            throw "Required build configuration file not found: $requiredPath"
        }
    }

    $buildText = Get-Content -Path $buildScript -Raw
    $specText = Get-Content -Path $specFile -Raw
    $combinedText = $buildText + "`n" + $specText

    $requiredMarkers = @(
        "favicon.ico",
        "fzastro_ai/astro_tools/fzastro",
        "fzastro_ai/resources/astropy_samp",
        "astroquery",
        "astropy",
        "skyfield",
        "playwright",
        "vosk",
        "sounddevice",
        "_sounddevice_data",
        "astroquery\simbad\data",
        "astropy\samp\data",
        "astropy\vo\samp\data"
    )

    $missingMarkers = @()
    foreach ($marker in $requiredMarkers) {
        if ($combinedText -notmatch [regex]::Escape($marker)) {
            $missingMarkers += $marker
        }
    }

    if ($missingMarkers.Count -gt 0) {
        throw ("PyInstaller resource configuration is missing required markers: {0}" -f ($missingMarkers -join ", "))
    }

    Write-ValidationLog -Path $script:WorkflowLogPath -Value "PyInstaller resource configuration ok"
}



$ProjectRoot = (Resolve-Path $ProjectRoot).Path
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
$BuildRoot = Resolve-BuildRootPath -RequestedBuildRoot $BuildRoot -Root $ProjectRoot
$ResolvedPython = Resolve-PythonExecutable -RequestedPython $PythonExe -Root $ProjectRoot
Set-FZAstroBuildEnvironment -PythonPath $ResolvedPython -Root $ProjectRoot -BuildPath $BuildRoot
if (-not $ExePath) {
    $releaseCandidate = Join-Path $BuildRoot "release\FZAstroAI.exe"
    $distCandidate = Join-Path $BuildRoot "dist\FZAstroAI.exe"
    if (Test-Path $releaseCandidate) { $ExePath = $releaseCandidate }
    else { $ExePath = $distCandidate }
}

$LogDir = Join-Path $BuildRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$ValidationLog = Join-Path $LogDir "validate_release.log"
Set-Content -Path $ValidationLog -Value "FZAstro AI validation log" -Encoding UTF8
$script:QuietOutput = -not $VerboseOutput
$script:WorkflowLogPath = $ValidationLog

Write-Host "FZAstro AI v2.0.0 Production Validation"
Write-Host "EXE:  $ExePath"
Write-Host "Logs: $ValidationLog"
Set-FZAstroBuildEnvironment -PythonPath $ResolvedPython -Root $ProjectRoot -BuildPath $BuildRoot
Initialize-StageProgress -Activity "Validation" -TotalSteps 13

Show-StageStep "Check EXE and manifest data"
if (-not (Test-Path $ExePath)) { throw "EXE not found: $ExePath" }
$hash = (Get-FileHash $ExePath -Algorithm SHA256).Hash
$sizeMB = [Math]::Round((Get-Item $ExePath).Length / 1MB, 2)
Write-ValidationLog -Path $ValidationLog -Value "EXE: $ExePath"
Write-ValidationLog -Path $ValidationLog -Value "SHA256: $hash"
Write-ValidationLog -Path $ValidationLog -Value "SizeMB: $sizeMB"

$VersionFile = Join-Path $ProjectRoot "VERSION.txt"
if (Test-Path $VersionFile) {
    $version = (Get-Content $VersionFile -Raw).Trim()
    if ($version -match "^2\.0\.0$") { Write-ValidationLog -Path $ValidationLog -Value "VERSION.txt reports $version" }
    else { Write-Warning "VERSION.txt does not look like v2.0.0: $version" }
}
else { Write-Warning "VERSION.txt not found" }

Show-StageStep "Checking Black formatting"
Invoke-LoggedCommand -Description "Black formatting check" -CommandPath $ResolvedPython -Arguments @("-m", "black", "--check", "--workers", "1", (Join-Path $ProjectRoot "main.py"), (Join-Path $ProjectRoot "fzastro_ai"), (Join-Path $ProjectRoot "tests")) -LogPath $ValidationLog -VerboseOutput:$VerboseOutput

Show-StageStep "Compile source"
Invoke-LoggedCommand -Description "Source compile check" -CommandPath $ResolvedPython -Arguments @("-m", "compileall", "-q", $ProjectRoot) -LogPath $ValidationLog -VerboseOutput:$VerboseOutput

Show-StageStep "Run automated tests"
Invoke-LoggedCommand -Description "Automated tests" -CommandPath $ResolvedPython -Arguments @("-m", "pytest", (Join-Path $ProjectRoot "tests")) -LogPath $ValidationLog -VerboseOutput:$VerboseOutput

Show-StageStep "Check critical imports"
$ImportCheck = @'
import importlib
modules = [
    "PySide6", "openai", "requests", "bs4", "ddgs", "playwright",
    "markdown", "pygments", "PyPDF2", "fitz", "PIL", "pytesseract", "openpyxl", "PyInstaller",
    "astropy", "astroquery", "numpy", "matplotlib", "skyfield", "black",
    "vosk", "sounddevice",
    "fzastro_ai.ui.llm_benchmark_dialog"
]
for name in modules:
    importlib.import_module(name)
print("critical imports ok")
'@
Invoke-PythonSnippet -PythonExe $ResolvedPython -Code $ImportCheck -Name "critical_import_check"
if ($script:PythonSnippetExitCode -ne 0) { throw "Critical import check failed. See log: $ValidationLog" }

Show-StageStep "Check astronomy package data"
$AstroDataCheck = @'
import importlib.resources as resources
checks = [
    ("astroquery", ("CITATION",)),
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
    print("optional package data missing: " + ", ".join(missing))
    raise SystemExit(2)
print("astro package data ok")
'@
Invoke-PythonSnippet -PythonExe $ResolvedPython -Code $AstroDataCheck -Name "astro_data_check"
if ($script:PythonSnippetExitCode -ne 0) { Write-Warning "optional astronomy package data missing in build Python; fallback resources may be used by the packaged app" }

Show-StageStep "Check PyInstaller resource configuration"
Assert-PyInstallerResourceConfiguration -Root $ProjectRoot

Show-StageStep "Check optional external tools"
$ollamaCommand = Get-Command ollama -ErrorAction SilentlyContinue
if ($ollamaCommand) {
    $ollamaVersionExit = Invoke-NativeCommand -Description "Ollama version check" -CommandPath $ollamaCommand.Source -Arguments @("--version") -LogPath $ValidationLog -VerboseOutput:$VerboseOutput
    $ollamaListExit = Invoke-NativeCommand -Description "Ollama model list check" -CommandPath $ollamaCommand.Source -Arguments @("list") -LogPath $ValidationLog -VerboseOutput:$VerboseOutput
    if (($ollamaVersionExit -ne 0) -or ($ollamaListExit -ne 0)) { Write-Warning "Ollama command exists but model list/version check failed" }
}
else { Write-Warning "Ollama command not found. Chat requires Ollama or another configured API endpoint." }

$tesseractCommand = Get-Command tesseract -ErrorAction SilentlyContinue
if ($tesseractCommand) {
    $tesseractExit = Invoke-NativeCommand -Description "Tesseract version check" -CommandPath $tesseractCommand.Source -Arguments @("--version") -LogPath $ValidationLog -VerboseOutput:$VerboseOutput
    if ($tesseractExit -ne 0) { Write-Warning "Tesseract command exists but version check failed" }
}
else { Write-Warning "Tesseract command not found. OCR will be unavailable unless installed/configured." }

$PlaywrightCheck = @'
from pathlib import Path
import importlib.resources as resources
from playwright.sync_api import sync_playwright

local_browsers = resources.files("playwright").joinpath("driver", "package", ".local-browsers")
if local_browsers.is_dir() and any(local_browsers.rglob("chrome*.exe")):
    print(local_browsers)
    raise SystemExit(0)

with sync_playwright() as p:
    exe = p.chromium.executable_path
    if not exe or not Path(exe).exists():
        raise SystemExit(f"Chromium executable not found: {exe}")
    print(exe)
'@
Invoke-PythonSnippet -PythonExe $ResolvedPython -Code $PlaywrightCheck -Name "playwright_check"
if ($script:PythonSnippetExitCode -ne 0) { Write-Warning "Playwright Chromium is not installed in the build environment. Run: `$env:PLAYWRIGHT_BROWSERS_PATH='0'; python -m playwright install chromium" }


Show-StageStep "Check release manifest and required files"
$ReleaseDirectory = Split-Path -Parent $ExePath
Assert-ReleaseManifest -ReleaseDirectory $ReleaseDirectory -ExpectedExePath $ExePath -ExpectedHash $hash

Show-StageStep "Check release artifact hygiene"
Assert-ReleaseArtifactHygiene -ReleaseDirectory $ReleaseDirectory

Show-StageStep "Launch EXE smoke test"
if (-not $SkipLaunch) {
    Stop-Process -Name "FZAstroAI" -Force -ErrorAction SilentlyContinue
    $SmokeAppDir = Join-Path $BuildRoot "smoke_appdata"
    Remove-Item -Recurse -Force $SmokeAppDir -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $SmokeAppDir | Out-Null
    $HadFZAstroAppDir = Test-Path Env:FZASTRO_APP_DIR
    $PreviousFZAstroAppDir = $env:FZASTRO_APP_DIR
    $env:FZASTRO_APP_DIR = $SmokeAppDir
    Write-ValidationLog -Path $ValidationLog -Value "Smoke test FZASTRO_APP_DIR: $SmokeAppDir"
    try {
        $proc = Start-Process -FilePath $ExePath -PassThru
        Start-Sleep -Seconds 8
        if ($proc.HasExited) {
            Write-Fail "EXE exited during smoke test. Check validation smoke_appdata logs."
            throw "EXE launch smoke test failed."
        }
        else {
            Write-Ok "EXE stayed open for smoke test"
            if (-not $KeepRunning) {
                Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
                Write-Ok "Smoke-test process closed"
            }
            else {
                Write-Ok "EXE left running for manual validation"
            }
        }
    }
    finally {
        if ($HadFZAstroAppDir) {
            $env:FZASTRO_APP_DIR = $PreviousFZAstroAppDir
        }
        else {
            Remove-Item Env:FZASTRO_APP_DIR -ErrorAction SilentlyContinue
        }
    }
}
else { Write-Warning "Launch smoke test skipped" }

Show-StageStep "Validation complete"
Complete-StageProgress
Write-Host ""
Write-Host "VALIDATION SCRIPT COMPLETE"
Write-Host "Log: $ValidationLog"
Write-Host "Manual checklist: RELEASE_VALIDATION.md"


