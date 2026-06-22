param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$PythonExe = $env:FZASTRO_PYTHON,
    [string]$BuildRoot = "",
    [switch]$BuildImagingBundle,
    [string]$NinaSourceZip = "",
    [string]$NinaSourceDir = "",
    [switch]$AutoInstallDotNetSdk,
    [string]$VoiceModelsRoot = $env:FZASTRO_VOICE_MODELS_DIR,
    [string]$VoiceModelZip = "",
    [switch]$SkipOfflineVoiceSetup,
    [switch]$PersistVoiceEnvironment,
    [switch]$SkipDependencyInstall,
    [switch]$SetupOpenClaudeCompanion,
    [switch]$InstallOpenClaudeIfMissing,
    [switch]$InstallNodeWithWinget,
    [switch]$InstallEmbeddedTerminalBackend,
    [switch]$InstallTerminalFrontend,
    [switch]$SkipFormat,
    [switch]$SkipValidationPrompt,
    [switch]$RunValidation,
    [switch]$CleanOnly,
    [switch]$VerboseOutput,
    [switch]$GitRelease,
    [string]$GitTag = "",
    [string]$GitCommitMessage = "",
    [switch]$GitPush,
    [string]$GitRemote = "origin",
    [string]$GitBranch = ""
)

$ErrorActionPreference = "Stop"
$ScriptsRoot = $PSScriptRoot

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

function Invoke-FZAstroVirtualEnvironmentActivation {
    param(
        [string]$PythonPath,
        [string]$Root,
        [string]$BuildPath
    )

    if (-not $PythonPath) { return }

    if (Test-Path $PythonPath) {
        $PythonPath = (Resolve-Path $PythonPath).Path
    }

    $ScriptsDir = Split-Path -Parent $PythonPath
    $VenvPath = Split-Path -Parent $ScriptsDir
    if (-not $VenvPath -or -not (Test-Path (Join-Path $VenvPath "pyvenv.cfg"))) {
        Write-Host "[deploy] Python is not from a virtual environment; activation skipped: $PythonPath"
        return
    }

    $ActivateScript = Join-Path $VenvPath "Scripts\Activate.ps1"
    if (-not (Test-Path $ActivateScript)) {
        throw "Virtual environment activation script not found: $ActivateScript. Recreate it with: powershell -ExecutionPolicy Bypass -File .\scripts\reset_venv.ps1 -Force"
    }

    Write-Host "[deploy] Activating virtual environment: $VenvPath"
    . $ActivateScript

    # Activate.ps1 adjusts PATH and VIRTUAL_ENV; re-assert FZAstro-specific
    # variables afterwards so nested build scripts inherit the exact deploy
    # configuration selected above.
    $env:FZASTRO_PROJECT_ROOT = $Root
    $env:FZASTRO_BUILD_ROOT = $BuildPath
    $env:FZASTRO_PYTHON = $PythonPath
    $env:VIRTUAL_ENV = $VenvPath

    $PathParts = @($env:PATH -split ";" | Where-Object { $_ })
    if ($PathParts -notcontains $ScriptsDir) {
        $env:PATH = ($ScriptsDir + ";" + $env:PATH)
    }
}

function Invoke-OfflineVoiceSetup {
    param(
        [string]$Root,
        [string]$ModelsRoot,
        [string]$ModelZipPath,
        [switch]$PersistEnvironment,
        [switch]$VerboseOutput
    )

    $VoiceSetupScript = Join-Path $ScriptsRoot "install_offline_voice.ps1"
    if (-not (Test-Path $VoiceSetupScript)) {
        throw "Offline voice setup script not found: $VoiceSetupScript"
    }

    $VoiceParams = @{}
    if ($ModelsRoot) { $VoiceParams["VoiceModelsRoot"] = $ModelsRoot }
    if ($ModelZipPath) { $VoiceParams["ModelZip"] = $ModelZipPath }
    if ($PersistEnvironment) { $VoiceParams["PersistEnvironment"] = $true }
    if ($VerboseOutput) { $VoiceParams["VerboseOutput"] = $true }

    & $VoiceSetupScript @VoiceParams
    if (-not $?) { throw "Offline voice setup failed." }
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

function Invoke-GitRelease {
    param(
        [string]$Root,
        [string]$RequestedTag,
        [string]$RequestedCommitMessage,
        [switch]$Push,
        [string]$Remote,
        [string]$Branch
    )

    $gitCommand = Get-Command git -ErrorAction SilentlyContinue
    if (-not $gitCommand) {
        throw "Git release automation requested, but git was not found on PATH."
    }

    $inside = & $gitCommand.Source -C $Root rev-parse --is-inside-work-tree 2>$null
    if ($LASTEXITCODE -ne 0 -or "$inside".Trim() -ne "true") {
        throw "Git release automation requested, but ProjectRoot is not inside a git repository: $Root"
    }

    $repoRoot = (& $gitCommand.Source -C $Root rev-parse --show-toplevel).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $repoRoot) {
        throw "Could not resolve git repository root for: $Root"
    }

    $versionFile = Join-Path $Root "VERSION.txt"
    if (-not (Test-Path $versionFile)) {
        throw "VERSION.txt not found; cannot derive release tag."
    }

    $version = (Get-Content -Path $versionFile -Raw).Trim()
    if (-not $version) {
        throw "VERSION.txt is empty; cannot derive release tag."
    }

    $resolvedTag = $RequestedTag.Trim()
    if (-not $resolvedTag) { $resolvedTag = "v$version" }

    $commitMessage = $RequestedCommitMessage.Trim()
    if (-not $commitMessage) {
        $commitMessage = "Release FZAstro AI $resolvedTag"
    }

    Write-Host "[git] Repository: $repoRoot"
    Write-Host "[git] Release tag: $resolvedTag"

    $initialStatus = & $gitCommand.Source -C $repoRoot status --short
    if ($LASTEXITCODE -ne 0) {
        throw "Could not read git status."
    }

    if ($initialStatus) {
        Write-Host "[git] Staging release changes..."
        & $gitCommand.Source -C $repoRoot add -A -- .
        if ($LASTEXITCODE -ne 0) { throw "git add failed." }

        $stagedStatus = & $gitCommand.Source -C $repoRoot status --short
        if ($stagedStatus) {
            Write-Host "[git] Creating release commit..."
            & $gitCommand.Source -C $repoRoot commit -m $commitMessage
            if ($LASTEXITCODE -ne 0) { throw "git commit failed." }
        }
        else {
            Write-Host "[git] No staged changes after git add; skipping commit."
        }
    }
    else {
        Write-Host "[git] Working tree is clean; skipping release commit."
    }

    $existingTag = & $gitCommand.Source -C $repoRoot tag --list $resolvedTag
    if ($LASTEXITCODE -ne 0) { throw "git tag lookup failed." }
    if ($existingTag) {
        Write-Host "[git] Tag already exists locally: $resolvedTag"
    }
    else {
        $tagMessage = "FZAstro AI $resolvedTag"
        Write-Host "[git] Creating annotated tag..."
        & $gitCommand.Source -C $repoRoot tag -a $resolvedTag -m $tagMessage
        if ($LASTEXITCODE -ne 0) { throw "git tag failed." }
    }

    if ($Push) {
        $resolvedBranch = $Branch.Trim()
        if (-not $resolvedBranch) {
            $resolvedBranch = (& $gitCommand.Source -C $repoRoot branch --show-current).Trim()
            if ($LASTEXITCODE -ne 0 -or -not $resolvedBranch) {
                throw "Could not determine current git branch. Pass -GitBranch explicitly."
            }
        }

        if (-not $Remote.Trim()) {
            throw "Git push requested, but GitRemote is empty."
        }

        Write-Host "[git] Pushing branch $resolvedBranch to $Remote..."
        & $gitCommand.Source -C $repoRoot push $Remote $resolvedBranch
        if ($LASTEXITCODE -ne 0) { throw "git push branch failed." }

        Write-Host "[git] Pushing tag $resolvedTag to $Remote..."
        & $gitCommand.Source -C $repoRoot push $Remote $resolvedTag
        if ($LASTEXITCODE -ne 0) { throw "git push tag failed." }
    }
    else {
        Write-Host "[git] Push skipped. Add -GitPush to push the branch and tag."
    }
}


$ProjectRoot = (Resolve-Path $ProjectRoot).Path
$BuildRoot = Resolve-BuildRootPath -RequestedBuildRoot $BuildRoot -Root $ProjectRoot
$CleanScript = Join-Path $ScriptsRoot "clean_build.ps1"
$ImagingBundleScript = Join-Path $ScriptsRoot "prepare_fzastro_imaging_bundle.ps1"
$OpenClaudeSetupScript = Join-Path $ScriptsRoot "setup_openclaude_companion.ps1"

if (-not (Test-Path $CleanScript)) {
    throw "Clean/build script not found: $CleanScript"
}
if ($BuildImagingBundle -and -not (Test-Path $ImagingBundleScript)) {
    throw "FZAstro Imaging bundle script not found: $ImagingBundleScript"
}
if ($SetupOpenClaudeCompanion -and -not (Test-Path $OpenClaudeSetupScript)) {
    throw "OpenClaude companion setup script not found: $OpenClaudeSetupScript"
}
if ($GitRelease -and $CleanOnly) {
    throw "Git release automation cannot run with -CleanOnly."
}

$ResolvedPython = Resolve-PythonExecutable -RequestedPython $PythonExe -Root $ProjectRoot
Set-FZAstroBuildEnvironment -PythonPath $ResolvedPython -Root $ProjectRoot -BuildPath $BuildRoot
Invoke-FZAstroVirtualEnvironmentActivation -PythonPath $ResolvedPython -Root $ProjectRoot -BuildPath $BuildRoot

$LogDir = Join-Path $BuildRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Write-Host "FZAstro AI deploy workflow"
Write-Host "Project: $ProjectRoot"
Write-Host "Build:   $BuildRoot"
Write-Host "Logs:    $LogDir"
Write-Host ""
$TotalDeploySteps = 2
if ($SetupOpenClaudeCompanion) { $TotalDeploySteps += 1 }
if ($BuildImagingBundle) { $TotalDeploySteps += 1 }
if ($GitRelease) { $TotalDeploySteps += 1 }
Initialize-StageProgress -Activity "FZAstro AI deploy" -TotalSteps $TotalDeploySteps
if ($SetupOpenClaudeCompanion) {
    Show-StageStep "OpenClaude companion setup"
    $OpenClaudeParams = @{ PythonExe = $ResolvedPython }
    if ($InstallOpenClaudeIfMissing) { $OpenClaudeParams["InstallOpenClaudeIfMissing"] = $true }
    if ($InstallNodeWithWinget) { $OpenClaudeParams["InstallNodeWithWinget"] = $true }
    if ($InstallEmbeddedTerminalBackend) { $OpenClaudeParams["InstallEmbeddedTerminalBackend"] = $true }
    if ($InstallTerminalFrontend) { $OpenClaudeParams["InstallTerminalFrontend"] = $true }
    & $OpenClaudeSetupScript @OpenClaudeParams
    if (-not $?) { throw "OpenClaude companion setup failed." }
}

if ($SkipOfflineVoiceSetup) {
    Show-StageStep "Offline voice setup skipped"
}
else {
    Show-StageStep "Offline voice model setup"
    Invoke-OfflineVoiceSetup -Root $ProjectRoot -ModelsRoot $VoiceModelsRoot -ModelZipPath $VoiceModelZip -PersistEnvironment:$PersistVoiceEnvironment -VerboseOutput:$VerboseOutput
}

if ($BuildImagingBundle) {
    Show-StageStep "FZAstro Imaging bundle"
    $BundleParams = @{}
    if ($NinaSourceZip) { $BundleParams["NinaSourceZip"] = $NinaSourceZip }
    if ($NinaSourceDir) { $BundleParams["NinaSourceDir"] = $NinaSourceDir }
    if ($AutoInstallDotNetSdk) { $BundleParams["AutoInstallDotNetSdk"] = $true }
    & $ImagingBundleScript @BundleParams
    if (-not $?) { throw "FZAstro Imaging bundle workflow failed." }
}

Show-StageStep "Clean/build workflow"

$CleanParams = @{
    ProjectRoot = $ProjectRoot
    BuildRoot = $BuildRoot
}

if ($ResolvedPython) { $CleanParams["PythonExe"] = $ResolvedPython }
if ($SkipDependencyInstall) { $CleanParams["SkipDependencyInstall"] = $true }
if ($SkipFormat) { $CleanParams["SkipFormat"] = $true }
if ($SkipValidationPrompt) { $CleanParams["SkipValidationPrompt"] = $true }
if ($RunValidation) { $CleanParams["RunValidation"] = $true }
if ($CleanOnly) { $CleanParams["CleanOnly"] = $true }
if ($VerboseOutput) { $CleanParams["VerboseOutput"] = $true }

& $CleanScript @CleanParams
if (-not $?) { throw "Deploy workflow failed." }

# FZAstro Imaging bundle copy for frozen EXE release
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BuildRoot = Join-Path (Split-Path -Parent $ProjectRoot) "FZAstroAI_BUILD"
$DistDir = Join-Path $BuildRoot "dist"
$ImagingSource = Join-Path $ProjectRoot "bundled_apps\FZAstroImaging"
$ImagingDest = Join-Path $DistDir "bundled_apps\FZAstroImaging"

if (Test-Path $ImagingSource) {
    Write-Host "[deploy] Copying bundled FZAstro Imaging runtime..."
    Remove-Item -Recurse -Force $ImagingDest -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path $ImagingDest -Force | Out-Null
    Copy-Item -Path "$ImagingSource\*" -Destination $ImagingDest -Recurse -Force

    $RequiredImagingFiles = @(
        "FZAstroImaging.exe",
        "NINA.exe",
        "NINA.dll"
    )

    foreach ($file in $RequiredImagingFiles) {
        $check = Join-Path $ImagingDest $file
        if (-not (Test-Path $check)) {
            throw "Bundled FZAstro Imaging runtime is incomplete. Missing: $check"
        }
    }

    Write-Host "[deploy] FZAstro Imaging runtime copied to: $ImagingDest"
} else {
    Write-Host "[deploy] FZAstro Imaging runtime not copied because source folder was not found: $ImagingSource"
}

if ($GitRelease) {
    Show-StageStep "Git release commit/tag"
    Invoke-GitRelease `
        -Root $ProjectRoot `
        -RequestedTag $GitTag `
        -RequestedCommitMessage $GitCommitMessage `
        -Push:$GitPush `
        -Remote $GitRemote `
        -Branch $GitBranch
}

Complete-StageProgress

Write-Host ""
Write-Host "Deploy workflow complete."

