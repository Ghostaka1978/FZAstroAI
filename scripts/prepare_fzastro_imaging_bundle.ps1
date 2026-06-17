param(
    [string]$NinaSourceZip = "",
    [string]$NinaSourceDir = "",
    [switch]$AutoInstallDotNetSdk,
    [switch]$KeepWork
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not (Get-Variable -Name IsWindows -ErrorAction SilentlyContinue)) {
    $script:IsWindows = $true
}

if (-not $IsWindows) {
    throw "FZAstro Imaging bundle build is Windows-only."
}

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptRoot
$BundleDir = Join-Path $ProjectRoot "bundled_apps\FZAstroImaging"
$LogsDir = Join-Path (Split-Path -Parent $ProjectRoot) "FZAstroAI_BUILD\logs"
$LogFile = Join-Path $LogsDir "fzastro_imaging_bundle.log"

New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null

function Write-Step([string]$Message) {
    Write-Host "[FZAstro Imaging] $Message"
    Add-Content -Path $LogFile -Value "[FZAstro Imaging] $Message"
}

function Find-DotNet {
    $cmd = Get-Command dotnet -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $paths = @(
        "$env:ProgramFiles\dotnet\dotnet.exe",
        "${env:ProgramFiles(x86)}\dotnet\dotnet.exe"
    )

    foreach ($path in $paths) {
        if ($path -and (Test-Path $path)) { return $path }
    }

    return $null
}

function Ensure-DotNetSdk {
    $dotnet = Find-DotNet
    if ($dotnet) { return $dotnet }

    if (-not $AutoInstallDotNetSdk) {
        throw ".NET SDK is missing. Rerun with -AutoInstallDotNetSdk or install Microsoft.DotNet.SDK.10."
    }

    Write-Step "Installing .NET SDK using winget"
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "winget is not available. Install .NET SDK 10 manually."
    }

    & $winget.Source install Microsoft.DotNet.SDK.10 --accept-package-agreements --accept-source-agreements
    $dotnet = Find-DotNet

    if (-not $dotnet) {
        throw ".NET SDK install finished, but dotnet.exe was not found. Open a new PowerShell and rerun deploy."
    }

    return $dotnet
}

function Copy-SourceToWork {
    param([string]$WorkSourceRoot)

    if ($NinaSourceZip) {
        if (-not (Test-Path $NinaSourceZip)) {
            throw "N.I.N.A. source zip not found: $NinaSourceZip"
        }

        Write-Step "Extracting N.I.N.A. source zip"
        Expand-Archive -Path $NinaSourceZip -DestinationPath $WorkSourceRoot -Force
        return
    }

    if ($NinaSourceDir) {
        if (-not (Test-Path $NinaSourceDir)) {
            throw "N.I.N.A. source folder not found: $NinaSourceDir"
        }

        Write-Step "Copying N.I.N.A. source folder"
        New-Item -ItemType Directory -Path $WorkSourceRoot -Force | Out-Null
        Copy-Item -Path "$NinaSourceDir\*" -Destination $WorkSourceRoot -Recurse -Force
        return
    }

    throw "Provide -NinaSourceZip or -NinaSourceDir."
}

function Find-NinaProject {
    param([string]$Root)

    $project = Get-ChildItem -Path $Root -Recurse -Filter "NINA.csproj" -File |
        Select-Object -First 1

    if (-not $project) {
        throw "Could not find NINA.csproj under: $Root"
    }

    return $project
}

function Set-CsprojProperty {
    param(
        [string]$Path,
        [string]$Name,
        [string]$Value
    )

    $text = [System.IO.File]::ReadAllText($Path)
    $pattern = "<$Name>.*?</$Name>"

    if ([System.Text.RegularExpressions.Regex]::IsMatch($text, $pattern)) {
        $text = [System.Text.RegularExpressions.Regex]::Replace($text, $pattern, "<$Name>$Value</$Name>", 1)
    } else {
        $text = [System.Text.RegularExpressions.Regex]::Replace(
            $text,
            "(<PropertyGroup>\s*)",
            "`$1`r`n    <$Name>$Value</$Name>`r`n",
            1
        )
    }

    [System.IO.File]::WriteAllText($Path, $text, [System.Text.UTF8Encoding]::new($false))
}

function Apply-ThinBranding {
    param([string]$NinaCsproj)

    Write-Step "Applying thin FZAstro branding"

    # Keep AssemblyName and RootNamespace as NINA.
    # WPF pack/resource references expect the internal assembly to be NINA.
    Set-CsprojProperty -Path $NinaCsproj -Name "Product" -Value "FZAstro Imaging Control"
    Set-CsprojProperty -Path $NinaCsproj -Name "Description" -Value "FZAstro Imaging Control based on N.I.N.A."

    $text = [System.IO.File]::ReadAllText($NinaCsproj)
    $text = $text -replace '<AssemblyName>FZAstroImaging</AssemblyName>', '<AssemblyName>NINA</AssemblyName>'
    $text = $text -replace '<RootNamespace>FZAstroImaging</RootNamespace>', '<RootNamespace>NINA</RootNamespace>'
    [System.IO.File]::WriteAllText($NinaCsproj, $text, [System.Text.UTF8Encoding]::new($false))
}

function Run-DotNetBuildQuiet {
    param(
        [string]$DotNet,
        [string]$NinaCsproj
    )

    Write-Step "Building FZAstro Imaging executable"

    $stdout = Join-Path $LogsDir "fzastro_imaging_dotnet_stdout.log"
    $stderr = Join-Path $LogsDir "fzastro_imaging_dotnet_stderr.log"
    $exitFile = Join-Path $LogsDir "fzastro_imaging_dotnet_exitcode.txt"
    $cmdFile = Join-Path $LogsDir "fzastro_imaging_dotnet_build.cmd"

    Remove-Item $stdout, $stderr, $exitFile, $cmdFile -Force -ErrorAction SilentlyContinue
    New-Item -ItemType File -Path $stdout -Force | Out-Null
    New-Item -ItemType File -Path $stderr -Force | Out-Null

    $cmdText = @"
@echo off
"$DotNet" build "$NinaCsproj" -c Release -r win-x64 --nologo -v:q 1> "$stdout" 2> "$stderr"
echo %ERRORLEVEL% > "$exitFile"
exit /b %ERRORLEVEL%
"@

    Set-Content -Path $cmdFile -Value $cmdText -Encoding ASCII

    $process = Start-Process `
        -FilePath $env:ComSpec `
        -ArgumentList @("/d", "/c", "`"$cmdFile`"") `
        -PassThru `
        -WindowStyle Hidden

    $seconds = 0

    while (-not $process.HasExited) {
        $seconds += 1
        $percent = [Math]::Min(95, 5 + ($seconds * 2))
        Write-Progress -Activity "Building FZAstro Imaging" -Status "dotnet build running... ${seconds}s" -PercentComplete $percent
        Start-Sleep -Seconds 1
        $process.Refresh()
    }

    $process.WaitForExit()
    $process.Refresh()

    Write-Progress -Activity "Building FZAstro Imaging" -Completed

    Add-Content -Path $LogFile -Value "---- dotnet stdout ----"
    Get-Content $stdout -ErrorAction SilentlyContinue | Add-Content $LogFile

    Add-Content -Path $LogFile -Value "---- dotnet stderr ----"
    Get-Content $stderr -ErrorAction SilentlyContinue | Add-Content $LogFile

    $exitCode = $process.ExitCode

    if (Test-Path $exitFile) {
        $rawExit = (Get-Content $exitFile -Raw).Trim()
        if ($rawExit -match "^-?\d+$") {
            $exitCode = [int]$rawExit
        }
    }

    if ($null -eq $exitCode) {
        $exitCode = -999999
    }

    if ($exitCode -ne 0) {
        Write-Host ""
        Write-Host "FZAstro Imaging build failed. See logs:"
        Write-Host $stdout
        Write-Host $stderr
        Write-Host $LogFile
        throw "dotnet build failed with exit code $exitCode"
    }

    Write-Step "Build succeeded"
}

function Find-BuildOutput {
    param([string]$NinaProjectDir)

    $preferred = Join-Path $NinaProjectDir "bin\Release\net10.0-windows\win-x64"

    if ((Test-Path (Join-Path $preferred "NINA.exe")) -or (Test-Path (Join-Path $preferred "FZAstroImaging.exe"))) {
        return $preferred
    }

    $exe = Get-ChildItem -Path (Join-Path $NinaProjectDir "bin") -Recurse -Include NINA.exe,FZAstroImaging.exe -File -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -notmatch "\\obj\\" } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if (-not $exe) {
        throw "Build succeeded, but no NINA.exe/FZAstroImaging.exe was found under: $(Join-Path $NinaProjectDir 'bin')"
    }

    return $exe.DirectoryName
}

function Copy-Bundle {
    param([string]$BuildOutput)

    Write-Step "Copying imaging runtime bundle"

    Remove-Item -Recurse -Force $BundleDir -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path $BundleDir -Force | Out-Null

    Copy-Item -Path "$BuildOutput\*" -Destination $BundleDir -Recurse -Force

    if (Test-Path (Join-Path $BundleDir "NINA.exe")) {
        Copy-Item (Join-Path $BundleDir "NINA.exe") (Join-Path $BundleDir "FZAstroImaging.exe") -Force
    }

    if (-not (Test-Path (Join-Path $BundleDir "FZAstroImaging.exe"))) {
        throw "FZAstroImaging.exe was not created in bundle folder."
    }

    if (-not (Test-Path (Join-Path $BundleDir "NINA.dll"))) {
        throw "NINA.dll missing. Internal assembly must remain NINA for WPF resource compatibility."
    }

    Write-Step "Bundle ready: $BundleDir"
}

Write-Step "Preparing quiet FZAstro Imaging bundle build"
$dotnet = Ensure-DotNetSdk

$WorkRoot = Join-Path $env:TEMP ("fzastro_imaging_work_" + [System.Guid]::NewGuid().ToString("N"))
$WorkSourceRoot = Join-Path $WorkRoot "source"

try {
    Copy-SourceToWork -WorkSourceRoot $WorkSourceRoot

    $ninaProject = Find-NinaProject -Root $WorkSourceRoot
    $ninaCsproj = $ninaProject.FullName
    $ninaProjectDir = Split-Path -Parent $ninaCsproj

    Apply-ThinBranding -NinaCsproj $ninaCsproj
    Run-DotNetBuildQuiet -DotNet $dotnet -NinaCsproj $ninaCsproj

    $buildOutput = Find-BuildOutput -NinaProjectDir $ninaProjectDir
    Write-Step "Found build output: $buildOutput"

    Copy-Bundle -BuildOutput $buildOutput
}
finally {
    if (-not $KeepWork) {
        Remove-Item -Recurse -Force $WorkRoot -ErrorAction SilentlyContinue
    }
}

Write-Host ""
Write-Host "FZAstro Imaging bundle completed."
Write-Host "Log: $LogFile"


