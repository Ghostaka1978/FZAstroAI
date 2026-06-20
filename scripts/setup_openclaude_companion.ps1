param(
    [string]$PythonExe = "",
    [switch]$InstallOpenClaudeIfMissing,
    [switch]$InstallNodeWithWinget,
    [switch]$InstallEmbeddedTerminalBackend,
    [switch]$InstallTerminalFrontend,
    [switch]$RequireReady
)

$ErrorActionPreference = "Stop"

function Add-PathEntry {
    param([string]$PathEntry)
    if ($PathEntry -and (Test-Path -LiteralPath $PathEntry) -and ($env:Path -notlike "*$PathEntry*")) {
        $env:Path = $PathEntry + ";" + $env:Path
    }
}

function Get-CommandPath {
    param([string]$Name)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $directCandidates = @()
    if ($Name -eq "npm") {
        $directCandidates += "C:\Program Files\nodejs\npm.cmd"
    }
    elseif ($Name -eq "node") {
        $directCandidates += "C:\Program Files\nodejs\node.exe"
    }
    elseif ($Name -eq "openclaude") {
        $directCandidates += (Join-Path $env:APPDATA "npm\openclaude.cmd")
    }
    foreach ($candidate in $directCandidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) { return $candidate }
    }
    return ""
}

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$StateDir = Join-Path $env:APPDATA "FZAstroAI\openclaude"
New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
$StatusPath = Join-Path $StateDir "setup_status.txt"

Add-PathEntry "C:\Program Files\nodejs"
Add-PathEntry (Join-Path $env:APPDATA "npm")

if (-not (Get-CommandPath "node") -and $InstallNodeWithWinget) {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        Write-Warning "winget is not available. Install Node.js LTS manually."
    }
    else {
        Write-Host "Installing Node.js LTS through winget. Windows may request administrator approval."
        & $winget.Source install OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
        Add-PathEntry "C:\Program Files\nodejs"
    }
}

$node = Get-CommandPath "node"
$npm = Get-CommandPath "npm"
$openclaude = Get-CommandPath "openclaude"

$python = ""
if ($PythonExe) {
    if (Test-Path -LiteralPath $PythonExe) {
        $python = (Resolve-Path -LiteralPath $PythonExe).Path
    }
    else {
        $python = $PythonExe
    }
}
if (-not $python) {
    $VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $VenvPython) { $python = (Resolve-Path -LiteralPath $VenvPython).Path }
}
if (-not $python) { $python = Get-CommandPath "python" }
if (-not $python) { $python = Get-CommandPath "py" }

if (-not $openclaude -and $npm -and $InstallOpenClaudeIfMissing) {
    Write-Host "Installing OpenClaude npm package..."
    & $npm install -g "@gitlawb/openclaude@latest"
    Add-PathEntry (Join-Path $env:APPDATA "npm")
    $openclaude = Get-CommandPath "openclaude"
}

$embeddedBackend = "not checked"
if ($python) {
    & $python -c "import winpty" 2>$null
    if ($LASTEXITCODE -eq 0) {
        $embeddedBackend = "pywinpty available"
    }
    else {
        $embeddedBackend = "pywinpty missing"
        if ($InstallEmbeddedTerminalBackend) {
            Write-Host "Installing pywinpty for embedded OpenClaude terminal..."
            & $python -m pip install "pywinpty>=2.0,<3"
            & $python -c "import winpty" 2>$null
            if ($LASTEXITCODE -eq 0) { $embeddedBackend = "pywinpty available" }
        }
    }
}
else {
    $embeddedBackend = "python not found; pywinpty check skipped"
}


$terminalFrontend = "basic fallback"
$TerminalResourceDir = Join-Path $ProjectRoot "fzastro_ai\resources\terminal"
$TerminalVendorDir = Join-Path $TerminalResourceDir "vendor"
$XtermJsPath = Join-Path $TerminalVendorDir "xterm.js"
$XtermCssPath = Join-Path $TerminalVendorDir "xterm.css"
$FitAddonPath = Join-Path $TerminalVendorDir "addon-fit.js"
if ($InstallTerminalFrontend) {
    if (-not $npm) {
        Write-Warning "npm is required to prepare the xterm.js terminal frontend."
    }
    else {
        $ToolsDir = Join-Path $ProjectRoot ".tools\openclaude_terminal_frontend"
        New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null
        New-Item -ItemType Directory -Force -Path $TerminalVendorDir | Out-Null
        Write-Host "Installing/copying xterm.js terminal frontend assets..."
        & $npm install --prefix $ToolsDir "@xterm/xterm@latest" "@xterm/addon-fit@latest"
        $NodeModules = Join-Path $ToolsDir "node_modules"
        $XtermPkg = Join-Path $NodeModules "@xterm\xterm"
        $FitPkg = Join-Path $NodeModules "@xterm\addon-fit"
        $Candidates = @(
            @{ Source = (Join-Path $XtermPkg "lib\xterm.js"); Target = $XtermJsPath },
            @{ Source = (Join-Path $XtermPkg "css\xterm.css"); Target = $XtermCssPath },
            @{ Source = (Join-Path $FitPkg "lib\addon-fit.js"); Target = $FitAddonPath }
        )
        foreach ($item in $Candidates) {
            if (Test-Path -LiteralPath $item.Source) {
                Copy-Item -Force $item.Source $item.Target
            }
            else {
                Write-Warning "Missing terminal frontend asset: $($item.Source)"
            }
        }
    }
}
if ((Test-Path -LiteralPath $XtermJsPath) -and (Test-Path -LiteralPath $XtermCssPath) -and (Test-Path -LiteralPath $FitAddonPath)) {
    $terminalFrontend = "xterm.js available"
}

$missing = @()
if (-not $node) { $missing += "node" }
if (-not $npm) { $missing += "npm" }
if (-not $openclaude) { $missing += "openclaude" }

$status = @(
    "FZAstro OpenClaude Companion setup",
    "Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
    "Node: $node",
    "npm: $npm",
    "OpenClaude: $openclaude",
    "Python for embedded backend: $python",
    "Embedded terminal backend: $embeddedBackend",
    "Terminal frontend: $terminalFrontend",
    "Missing: $($missing -join ', ')",
    "",
    "If node/npm are missing: winget install OpenJS.NodeJS.LTS",
    "If OpenClaude is missing: npm install -g @gitlawb/openclaude@latest",
    "If terminal frontend is basic fallback: rerun this script with -InstallTerminalFrontend before build/deploy.",
    "Runtime launchers are generated by FZAstro under AppData\\Roaming\\FZAstroAI\\openclaude."
)
Set-Content -Path $StatusPath -Value ($status -join [Environment]::NewLine) -Encoding UTF8

Write-Host "OpenClaude companion setup status: $StatusPath"
Get-Content -Path $StatusPath

if ($missing.Count -gt 0 -and $RequireReady) {
    throw "OpenClaude companion is not ready. Missing: $($missing -join ', ')"
}
