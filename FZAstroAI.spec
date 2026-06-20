# -*- mode: python ; coding: utf-8 -*-

import importlib.resources as resources
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

web_companion_static_datas = [
    (
        str(PROJECT_ROOT / "fzastro_ai" / "web_companion" / "static" / "index.html"),
        "fzastro_ai/web_companion/static",
    ),
]

openclaude_datas = [
    (str(PROJECT_ROOT / "scripts" / "run_openclaude.ps1"), "scripts"),
    (str(PROJECT_ROOT / "scripts" / "setup_openclaude_companion.ps1"), "scripts"),
]
terminal_resource_dir = PROJECT_ROOT / "fzastro_ai" / "resources" / "terminal"
if terminal_resource_dir.exists():
    openclaude_datas.append((str(terminal_resource_dir), "fzastro_ai/resources/terminal"))

astro_datas = []
for package_name in ("astroquery", "astropy", "skyfield"):
    astro_datas += collect_data_files(package_name)

playwright_datas = collect_data_files("playwright")

openclaude_pywinpty_datas = []
try:
    openclaude_pywinpty_datas += collect_data_files("winpty")
except Exception:
    pass

voice_datas = []
voice_binaries = []
openclaude_binaries = []
try:
    openclaude_binaries += collect_dynamic_libs("winpty")
except Exception:
    pass
for package_name in ("vosk", "sounddevice", "_sounddevice_data"):
    try:
        voice_datas += collect_data_files(package_name)
    except Exception:
        pass
    try:
        voice_binaries += collect_dynamic_libs(package_name)
    except Exception:
        pass

# Explicitly include Astropy SAMP data. If these files are missing in a
# frozen app, Astropy falls back to old data.astropy.org URLs such as
# data/crossdomain.xml, which now return 404.
def add_astropy_samp_data(filename):
    try:
        package_file = resources.files("astropy.samp").joinpath("data", filename)
        if package_file.is_file():
            astro_datas.append((str(package_file), "astropy/samp/data"))
            astro_datas.append((str(package_file), "astropy/vo/samp/data"))
            return
    except Exception:
        pass

    fallback_file = Path("fzastro_ai/resources/astropy_samp") / filename
    if fallback_file.is_file():
        astro_datas.append((str(fallback_file), "astropy/samp/data"))
        astro_datas.append((str(fallback_file), "astropy/vo/samp/data"))


for samp_filename in ("astropy_icon.png", "crossdomain.xml", "clientaccesspolicy.xml"):
    add_astropy_samp_data(samp_filename)


# Explicitly include astroquery SIMBAD package data. The file is read during
# `from astroquery.simbad import Simbad`; if it is missing from the one-file
# extraction folder, Astropy tries old data.astropy.org URLs and lookup fails.
def add_astroquery_simbad_data(filename):
    try:
        package_file = resources.files("astroquery.simbad").joinpath("data", filename)
        if package_file.is_file():
            astro_datas.append((str(package_file), "astroquery/simbad/data"))
    except Exception:
        pass


for simbad_filename in ("query_criteria_fields.json",):
    add_astroquery_simbad_data(simbad_filename)



a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[
        *voice_binaries,
        *openclaude_binaries,
    ],
    datas=[
        ('favicon.ico', '.'),
        ('fzastro_ai/astro_tools/fzastro', 'fzastro_ai/astro_tools/fzastro'),
        ('fzastro_ai/resources/astropy_icon.png', 'fzastro_ai/resources'),
        ('fzastro_ai/resources/astropy_samp', 'fzastro_ai/resources/astropy_samp'),
        ('fzastro_ai/resources/nina_templates', 'fzastro_ai/resources/nina_templates'),
        *astro_datas,
        *web_companion_static_datas,
        *openclaude_datas,
        *openclaude_pywinpty_datas,
        *playwright_datas,
        *voice_datas,
    ],
    hiddenimports=[
        "vosk",
        "sounddevice",
        "_sounddevice",
        "_sounddevice_data",
        # Optional Windows ConPTY backend for the embedded OpenClaude terminal.
        # Safe if pywinpty is unavailable in non-Windows build environments.
        "winpty",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebChannel",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='FZAstroAI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['favicon.ico'],
)
