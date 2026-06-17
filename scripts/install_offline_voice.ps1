param(
    [string]$ModelName = "vosk-model-small-en-us-0.15",
    [string]$ModelUrl = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
    [string]$VoiceModelsRoot = "",
    [string]$ModelZip = "",
    [switch]$SkipDownload,
    [switch]$Force,
    [switch]$PersistEnvironment,
    [switch]$VerboseOutput
)

$ErrorActionPreference = "Stop"

function Resolve-VoiceModelsRoot {
    param([string]$RequestedRoot)

    if ($RequestedRoot) {
        try {
            return [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $RequestedRoot -ErrorAction Stop).Path)
        }
        catch {
            return [System.IO.Path]::GetFullPath($RequestedRoot)
        }
    }

    if ($env:FZASTRO_VOICE_MODELS_DIR) {
        return [System.IO.Path]::GetFullPath($env:FZASTRO_VOICE_MODELS_DIR)
    }

    if ($env:FZASTRO_APP_DIR) {
        return [System.IO.Path]::GetFullPath((Join-Path $env:FZASTRO_APP_DIR "voice_models"))
    }

    if ($env:APPDATA) {
        return [System.IO.Path]::GetFullPath((Join-Path $env:APPDATA "FZAstroAI\voice_models"))
    }

    return [System.IO.Path]::GetFullPath((Join-Path $HOME "AppData\Roaming\FZAstroAI\voice_models"))
}

function Test-VoskModelFolder {
    param([string]$Path)

    if (-not $Path -or -not (Test-Path -LiteralPath $Path -PathType Container)) { return $false }

    $required = @("am", "conf", "graph")
    foreach ($name in $required) {
        if (-not (Test-Path -LiteralPath (Join-Path $Path $name))) { return $false }
    }
    return $true
}

function Find-VoskModelFolder {
    param(
        [string]$Root,
        [string]$PreferredName
    )

    if ($env:FZASTRO_VOSK_MODEL -and (Test-VoskModelFolder -Path $env:FZASTRO_VOSK_MODEL)) {
        return [System.IO.Path]::GetFullPath($env:FZASTRO_VOSK_MODEL)
    }

    $preferred = Join-Path $Root $PreferredName
    if (Test-VoskModelFolder -Path $preferred) { return [System.IO.Path]::GetFullPath($preferred) }

    if (Test-Path -LiteralPath $Root) {
        $candidates = Get-ChildItem -LiteralPath $Root -Directory -Filter "vosk-model*" -ErrorAction SilentlyContinue | Sort-Object Name
        foreach ($candidate in $candidates) {
            if (Test-VoskModelFolder -Path $candidate.FullName) { return $candidate.FullName }
        }
    }

    return ""
}

$VoiceModelsRoot = Resolve-VoiceModelsRoot -RequestedRoot $VoiceModelsRoot
$TargetModelPath = Join-Path $VoiceModelsRoot $ModelName
$ExistingModelPath = Find-VoskModelFolder -Root $VoiceModelsRoot -PreferredName $ModelName

Write-Host "FZAstro AI offline voice setup"
Write-Host "Voice models root: $VoiceModelsRoot"

if ($ExistingModelPath -and -not $Force) {
    $env:FZASTRO_VOICE_MODELS_DIR = $VoiceModelsRoot
    $env:FZASTRO_VOSK_MODEL = $ExistingModelPath
    if ($PersistEnvironment) {
        [Environment]::SetEnvironmentVariable("FZASTRO_VOICE_MODELS_DIR", $VoiceModelsRoot, "User")
        [Environment]::SetEnvironmentVariable("FZASTRO_VOSK_MODEL", $ExistingModelPath, "User")
    }
    Write-Host "Vosk model already installed: $ExistingModelPath"
    Write-Host "FZASTRO_VOICE_MODELS_DIR=$VoiceModelsRoot"
    Write-Host "FZASTRO_VOSK_MODEL=$ExistingModelPath"
    return
}

if ($SkipDownload -and -not $ModelZip) {
    throw "No Vosk model found and -SkipDownload was set. Put an extracted model under $VoiceModelsRoot or pass -ModelZip."
}

New-Item -ItemType Directory -Force -Path $VoiceModelsRoot | Out-Null

$DownloadCache = Join-Path $VoiceModelsRoot "_downloads"
New-Item -ItemType Directory -Force -Path $DownloadCache | Out-Null

if ($ModelZip) {
    if (-not (Test-Path -LiteralPath $ModelZip)) {
        throw "Model zip not found: $ModelZip"
    }
    $ZipPath = [System.IO.Path]::GetFullPath($ModelZip)
}
else {
    $ZipPath = Join-Path $DownloadCache ("$ModelName.zip")
    if ($Force -or -not (Test-Path -LiteralPath $ZipPath)) {
        Write-Host "Downloading Vosk model: $ModelUrl"
        Invoke-WebRequest -Uri $ModelUrl -OutFile $ZipPath -UseBasicParsing
    }
    else {
        Write-Host "Using cached model zip: $ZipPath"
    }
}

if ($Force -and (Test-Path -LiteralPath $TargetModelPath)) {
    Remove-Item -Recurse -Force -LiteralPath $TargetModelPath
}

$ExtractDir = Join-Path $VoiceModelsRoot ("_extract_{0}" -f ([Guid]::NewGuid().ToString("N")))
New-Item -ItemType Directory -Force -Path $ExtractDir | Out-Null
try {
    Write-Host "Extracting model..."
    Expand-Archive -LiteralPath $ZipPath -DestinationPath $ExtractDir -Force

    $ExtractedModelPath = Join-Path $ExtractDir $ModelName
    if (-not (Test-VoskModelFolder -Path $ExtractedModelPath)) {
        $found = Get-ChildItem -LiteralPath $ExtractDir -Directory -Filter "vosk-model*" -Recurse -ErrorAction SilentlyContinue |
            Where-Object { Test-VoskModelFolder -Path $_.FullName } |
            Select-Object -First 1
        if ($found) { $ExtractedModelPath = $found.FullName }
    }

    if (-not (Test-VoskModelFolder -Path $ExtractedModelPath)) {
        throw "Downloaded/extracted payload does not look like a Vosk model. Expected am, conf, and graph folders."
    }

    if (Test-Path -LiteralPath $TargetModelPath) {
        Remove-Item -Recurse -Force -LiteralPath $TargetModelPath
    }
    Move-Item -LiteralPath $ExtractedModelPath -Destination $TargetModelPath
}
finally {
    Remove-Item -Recurse -Force -LiteralPath $ExtractDir -ErrorAction SilentlyContinue
}

if (-not (Test-VoskModelFolder -Path $TargetModelPath)) {
    throw "Vosk model setup failed: $TargetModelPath"
}

$env:FZASTRO_VOICE_MODELS_DIR = $VoiceModelsRoot
$env:FZASTRO_VOSK_MODEL = $TargetModelPath
if ($PersistEnvironment) {
    [Environment]::SetEnvironmentVariable("FZASTRO_VOICE_MODELS_DIR", $VoiceModelsRoot, "User")
    [Environment]::SetEnvironmentVariable("FZASTRO_VOSK_MODEL", $TargetModelPath, "User")
}

Write-Host "Offline voice model installed: $TargetModelPath"
Write-Host "FZASTRO_VOICE_MODELS_DIR=$VoiceModelsRoot"
Write-Host "FZASTRO_VOSK_MODEL=$TargetModelPath"
