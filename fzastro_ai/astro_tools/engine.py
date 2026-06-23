from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from io import StringIO
from urllib.parse import quote, quote_plus
from urllib.request import Request, urlopen
from html import escape as html_escape
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

from ..config import APP_DIR
from ..logging_utils import log_debug, log_exception, log_warning


def _is_user_cancelled_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return (
        "stopped by user" in text
        or "cancelled by user" in text
        or "canceled by user" in text
    )


PACKAGE_DIR = Path(__file__).resolve().parent
FZASTRO_DIR = PACKAGE_DIR / "fzastro"
SCRIPT_FILE = FZASTRO_DIR / "script.py"
IMAGEFETCH_FILE = FZASTRO_DIR / "imagefetch.py"
SEE_FILE = FZASTRO_DIR / "see.py"
TARGET_FILE = FZASTRO_DIR / "target.py"
SOLAR_FILE = FZASTRO_DIR / "solarsystem.py"
RESOURCES_DIR = PACKAGE_DIR.parent / "resources"
ASTROPY_ICON_FALLBACK = RESOURCES_DIR / "astropy_icon.png"
SOLAR_SYSTEM_REFERENCE_DIR = RESOURCES_DIR / "astro_reference_images"
_ASTROPY_RUNTIME_DATA_READY = False
_ASTROPY_ICON_URLS = {
    "http://data.astropy.org/data/astropy_icon.png",
    "https://data.astropy.org/data/astropy_icon.png",
    "http://www.astropy.org/astropy-data/data/astropy_icon.png",
    "https://www.astropy.org/astropy-data/data/astropy_icon.png",
}


class AstroToolCancelled(RuntimeError):
    """Raised when the user stops a migrated astro tool."""


_ASTRO_THREAD_STATE = threading.local()


def _astro_cancel_requested() -> bool:
    callback = getattr(_ASTRO_THREAD_STATE, "cancel_callback", None)

    if callback is None:
        return False

    try:
        return bool(callback())
    except Exception as exc:
        log_debug("Astro cancel callback failed", exc)
        return False


@contextmanager
def astro_cancel_context(cancel_callback=None):
    """Give blocking embedded FZASTRO helpers a cooperative stop callback."""
    previous_callback = getattr(_ASTRO_THREAD_STATE, "cancel_callback", None)
    previous_process = getattr(_ASTRO_THREAD_STATE, "active_process", None)
    _ASTRO_THREAD_STATE.cancel_callback = cancel_callback
    _ASTRO_THREAD_STATE.active_process = previous_process

    try:
        yield
    finally:
        _ASTRO_THREAD_STATE.cancel_callback = previous_callback
        _ASTRO_THREAD_STATE.active_process = previous_process


def _terminate_process(process: subprocess.Popen):
    if process is None or process.poll() is not None:
        return

    try:
        process.terminate()
    except Exception as exc:
        log_debug("Astro subprocess terminate failed", exc)

    try:
        process.wait(timeout=2)
        return
    except Exception as exc:
        log_debug("Astro subprocess did not exit after terminate", exc)

    try:
        process.kill()
    except Exception as exc:
        log_debug("Astro subprocess kill failed", exc)


def _check_cancelled():
    if _astro_cancel_requested():
        raise AstroToolCancelled("Astro tool stopped by user.")


ASTRO_CACHE_DIR = APP_DIR / "astro_tools"
ASTRO_IMAGE_CACHE_DIR = ASTRO_CACHE_DIR / "images"
ASTRO_SKYFIELD_DIR = ASTRO_CACHE_DIR / "skyfield"
ASTRO_OUTPUT_DIR = ASTRO_CACHE_DIR / "outputs"
ASTRO_LOOKUP_CACHE_DIR = ASTRO_CACHE_DIR / "lookup_cache"

SIMBAD_TAP_ENDPOINTS = (
    "https://simbad.cds.unistra.fr/simbad/sim-tap/sync",
    "https://simbad.u-strasbg.fr/simbad/sim-tap/sync",
)

SESAME_LOOKUP_ENDPOINT_PATTERNS = (
    "https://cds.unistra.fr/cgi-bin/nph-sesame/-oxpI/S?{query}",
    "https://cds.unistra.fr/cgi-bin/nph-sesame/-oxpI/SNV?{query}",
)

SIMBAD_RESEARCH_TABLES = (
    # These raw SIMBAD TAP tables are displayed as research details only.
    # They must not feed or reorder the FZAstro distance ladder.
    ("mesDistance", "Distance measurements"),
    ("mesDiameter", "Diameter / angular-size measurements"),
    ("mesPM", "Proper-motion measurements"),
    ("mesPLX", "Parallax measurements"),
    ("mesVelocities", "Velocity / redshift measurements"),
    ("mesVar", "Variability measurements"),
    ("mesFe_H", "Metallicity measurements"),
    ("mesRot", "Rotation measurements"),
    ("mesSpT", "Spectral-type measurements"),
)


@dataclass
class AstroToolResult:
    """Structured result returned by the embedded astro tools."""

    title: str
    text: str
    files: List[str] = field(default_factory=list)
    success: bool = True
    source: str = "Astro Web APIs"
    metadata: Dict[str, Any] = field(default_factory=dict)


_REQUIRED_DEPENDENCIES = {
    "astropy": "object coordinates, target planning",
    "astroquery": "SIMBAD/NED/JPL Horizons lookup",
    "numpy": "target planning and solar-system map calculations",
    "matplotlib": "solar-system map rendering",
    "skyfield": "solar-system ephemerides",
    "tzdata": "IANA timezone database on Windows",
}

_OPTIONAL_DEPENDENCIES = {
    "timezonefinder": "auto-detect IANA timezone from latitude/longitude",
}


def _candidate_resource_file(relative_path: str) -> Optional[Path]:
    """Return a bundled resource from source or PyInstaller extraction paths.

    PyInstaller builds may contain Astropy's icon either as the project-level
    fallback ``fzastro_ai/resources/astropy_icon.png`` or inside the bundled
    SAMP fallback folder ``fzastro_ai/resources/astropy_samp/astropy_icon.png``.
    Check both forms before logging a missing-resource warning so the EXE does
    not report a false Astropy fallback failure from the temporary ``_MEI``
    extraction directory.
    """
    rel = Path(relative_path)
    rel_variants = [rel]

    if rel.as_posix() == "astropy_icon.png":
        rel_variants.append(Path("astropy_samp") / "astropy_icon.png")

    candidates: List[Path] = []
    resource_roots = [
        RESOURCES_DIR,
        PACKAGE_DIR.parent / "resources",
    ]

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        root = Path(str(meipass))
        resource_roots.extend(
            [
                root / "fzastro_ai" / "resources",
                root / "resources",
                root,
            ]
        )

    for resource_root in resource_roots:
        for variant in rel_variants:
            candidates.append(resource_root / variant)

    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except Exception:
            continue
    return None


def _ensure_astropy_runtime_data() -> None:
    """Make Astropy's tiny package data available inside a frozen EXE.

    In the frozen app, Astropy can still try to resolve
    astropy/data/astropy_icon.png through its remote data cache even when a
    fallback file was bundled beside the application. Those historical Astropy
    URLs now return 404, which breaks astroquery/SIMBAD before the real object
    query is made. This guard does three things before astroquery is imported:

    1. Copies the bundled fallback into the extracted astropy/data folder.
    2. Seeds Astropy's URL cache for the old icon URLs with the local file.
    3. Patches Astropy's data helpers so any remaining icon request resolves
       locally instead of touching the network.
    """
    global _ASTROPY_RUNTIME_DATA_READY

    if _ASTROPY_RUNTIME_DATA_READY:
        return

    source = _candidate_resource_file("astropy_icon.png") or ASTROPY_ICON_FALLBACK
    if not source.is_file():
        log_warning("Astropy runtime data fallback missing", source)
        _ASTROPY_RUNTIME_DATA_READY = True
        return

    destination_dirs: List[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        root = Path(str(meipass))
        destination_dirs.extend(
            [
                root / "astropy" / "data",
                root / "_internal" / "astropy" / "data",
            ]
        )

    try:
        import astropy  # type: ignore

        astropy_file = getattr(astropy, "__file__", "")
        if astropy_file:
            astropy_dir = Path(astropy_file).resolve().parent
            destination_dirs.append(astropy_dir / "data")
    except Exception as exc:
        log_debug("Astropy runtime data check skipped import path", exc)

    copied = False
    seen = set()
    for destination_dir in destination_dirs:
        try:
            key = (
                str(destination_dir.resolve()).casefold()
                if os.name == "nt"
                else str(destination_dir.resolve())
            )
        except Exception:
            key = str(destination_dir)
        if key in seen:
            continue
        seen.add(key)

        try:
            destination_dir.mkdir(parents=True, exist_ok=True)
            destination = destination_dir / "astropy_icon.png"
            if not destination.is_file() or destination.stat().st_size <= 0:
                shutil.copyfile(source, destination)
                copied = True
        except Exception as exc:
            log_debug("Astropy runtime data copy skipped", f"{destination_dir}: {exc}")

    try:
        import astropy.utils.data as astropy_data  # type: ignore

        for icon_url in _ASTROPY_ICON_URLS:
            try:
                astropy_data.import_file_to_cache(icon_url, str(source))
            except Exception as exc:
                log_debug("Astropy icon cache seed skipped", f"{icon_url}: {exc}")

        if not getattr(astropy_data, "_fzastro_icon_patch", False):
            original_get_pkg_data_filename = astropy_data.get_pkg_data_filename
            original_download_file = astropy_data.download_file

            def _fzastro_get_pkg_data_filename(data_name, *args, **kwargs):
                normalized = str(data_name).replace("\\", "/")
                if (
                    normalized.endswith("data/astropy_icon.png")
                    or normalized == "astropy_icon.png"
                ):
                    local_icon = _candidate_resource_file("astropy_icon.png") or source
                    if local_icon.is_file():
                        return str(local_icon)
                return original_get_pkg_data_filename(data_name, *args, **kwargs)

            def _fzastro_download_file(remote_url, *args, **kwargs):
                if str(remote_url).strip() in _ASTROPY_ICON_URLS:
                    local_icon = _candidate_resource_file("astropy_icon.png") or source
                    if local_icon.is_file():
                        return str(local_icon)
                return original_download_file(remote_url, *args, **kwargs)

            astropy_data.get_pkg_data_filename = _fzastro_get_pkg_data_filename
            astropy_data.download_file = _fzastro_download_file
            astropy_data._fzastro_icon_patch = True
    except Exception as exc:
        log_debug("Astropy runtime data helper patch skipped", exc)

    if copied:
        log_debug("Astropy runtime data fallback installed", source)

    _ASTROPY_RUNTIME_DATA_READY = True


def astro_dependency_report() -> Dict[str, str]:
    """Return dependency availability without importing heavy packages."""
    report: Dict[str, str] = {}

    for module_name, purpose in _REQUIRED_DEPENDENCIES.items():
        report[module_name] = (
            "available"
            if importlib.util.find_spec(module_name)
            else f"missing — {purpose}"
        )

    for module_name, purpose in _OPTIONAL_DEPENDENCIES.items():
        report[module_name] = (
            "available"
            if importlib.util.find_spec(module_name)
            else f"optional missing — {purpose}"
        )

    return report


_RESOLVED_ASTRO_PYTHON: Optional[str] = None


def _normalise_python_candidate(candidate: object) -> str:
    text = str(candidate or "").strip().strip('"')
    if not text:
        return ""

    path = Path(text)
    if path.exists():
        return str(path)

    resolved = shutil.which(text)
    return str(resolved or "")


def _python_supports_astro(candidate: str) -> bool:
    """Return True when a Python executable can run the migrated ASTRO scripts."""
    if not candidate:
        return False

    try:
        startupinfo = None
        if os.name == "nt":
            try:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            except Exception:
                startupinfo = None

        check = subprocess.run(
            [
                candidate,
                "-c",
                "import astropy, astroquery, numpy, requests; print('astro-python-ok')",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=8,
            startupinfo=startupinfo,
        )
        if check.returncode == 0:
            return True

        log_warning(
            "Astro Python candidate lacks dependencies",
            f"{candidate}: {_decode(check.stderr)}",
        )
    except Exception as exc:
        log_debug("Astro Python candidate check failed", f"{candidate}: {exc}")

    return False


def _resolve_python_interpreter() -> str:
    """Return an interpreter suitable for embedded FZASTRO scripts.

    In source mode this is normally the active venv. In a PyInstaller EXE,
    sys.executable is the app itself, so we must find a real Python that has
    astropy/astroquery installed. Prefer explicit configuration, then a
    portable Python beside the EXE or project, then PATH.
    """
    global _RESOLVED_ASTRO_PYTHON

    if _RESOLVED_ASTRO_PYTHON and Path(_RESOLVED_ASTRO_PYTHON).exists():
        return _RESOLVED_ASTRO_PYTHON

    candidates: List[str] = []

    for variable_name in ("FZASTRO_PYTHON", "PYTHON_EXECUTABLE"):
        value = _normalise_python_candidate(os.environ.get(variable_name))
        if value:
            candidates.append(value)

    if not getattr(sys, "frozen", False) and sys.executable:
        candidates.append(str(sys.executable))

    exe_dir = Path(sys.executable).resolve().parent if sys.executable else PACKAGE_DIR
    project_dir = (
        PACKAGE_DIR.parents[1] if len(PACKAGE_DIR.parents) > 1 else PACKAGE_DIR
    )

    if os.name == "nt":
        candidates.extend(
            [
                str(exe_dir / "python" / "python.exe"),
                str(exe_dir / ".venv" / "Scripts" / "python.exe"),
                str(project_dir / ".venv" / "Scripts" / "python.exe"),
            ]
        )
    else:
        candidates.extend(
            [
                str(exe_dir / "python" / "bin" / "python"),
                str(exe_dir / ".venv" / "bin" / "python"),
                str(project_dir / ".venv" / "bin" / "python"),
            ]
        )

    for command in ("python", "python3", "py"):
        value = _normalise_python_candidate(command)
        if value:
            candidates.append(value)

    seen = set()
    for candidate in candidates:
        candidate = _normalise_python_candidate(candidate)
        key = candidate.casefold() if os.name == "nt" else candidate
        if not candidate or key in seen:
            continue
        seen.add(key)

        if _python_supports_astro(candidate):
            _RESOLVED_ASTRO_PYTHON = candidate
            log_debug("Astro Python selected", candidate)
            return candidate

    return ""


def _base_env() -> Dict[str, str]:
    ASTRO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ASTRO_IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ASTRO_SKYFIELD_DIR.mkdir(parents=True, exist_ok=True)
    ASTRO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    env.setdefault("ASTROPY_CACHE_DIR", str(ASTRO_CACHE_DIR / "astropy"))
    env.setdefault("FZASTRO_SKYFIELD_DIR", str(ASTRO_SKYFIELD_DIR))
    env.setdefault("FZASTRO_FAST_LOOKUP", "1")
    env.setdefault("FZASTRO_ENABLE_GAIA", "0")
    env.setdefault("FZASTRO_DISABLE_IERS_DOWNLOAD", "1")
    return env


def _script_error(script: Path) -> AstroToolResult:
    return AstroToolResult(
        title="Astro tool unavailable",
        text=f"The migrated FZASTRO script is missing:\n\n`{script}`",
        success=False,
    )


def _run_script(
    script: Path, args: Iterable[str], timeout: int = 180, binary: bool = False
) -> Tuple[int, bytes, bytes, float]:
    if not script.exists():
        raise FileNotFoundError(str(script))

    _check_cancelled()
    python_executable = _resolve_python_interpreter()

    if not python_executable:
        raise RuntimeError(
            "No Python interpreter with the ASTRO dependencies was found. "
            "Set FZASTRO_PYTHON to your venv python.exe path, or place a .venv beside the app/project."
        )

    start = time.perf_counter()
    startupinfo = None

    if os.name == "nt":
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        except Exception:
            startupinfo = None

    command = [python_executable, str(script), *[str(arg) for arg in args]]
    process = subprocess.Popen(
        command,
        cwd=str(FZASTRO_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_base_env(),
        startupinfo=startupinfo,
    )
    _ASTRO_THREAD_STATE.active_process = process

    try:
        deadline = start + max(5, int(timeout))
        stdout = b""
        stderr = b""

        # Important: use communicate(timeout=...) instead of poll()+sleep.
        # Some migrated tools, especially solarsystem.py, write a PNG to stdout.
        # If the parent does not read stdout while the child is running, the OS
        # pipe can fill and the child blocks forever. That looked like a tool
        # timeout even though the renderer itself was working.
        while True:
            try:
                stdout, stderr = process.communicate(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                if _astro_cancel_requested():
                    _terminate_process(process)
                    try:
                        stdout, stderr = process.communicate(timeout=2)
                    except Exception:
                        stdout = stdout or b""
                        stderr = stderr or b""
                    raise AstroToolCancelled("Astro tool stopped by user.")

                if time.perf_counter() >= deadline:
                    _terminate_process(process)
                    try:
                        stdout, stderr = process.communicate(timeout=2)
                    except Exception:
                        stdout = stdout or b""
                        stderr = stderr or b""

                    elapsed = max(0.0, time.perf_counter() - start)
                    stdout_for_log = (
                        "<binary stdout>" if binary and stdout else _decode(stdout)
                    )
                    _log_script_failure(
                        script.name,
                        -1,
                        stdout_for_log,
                        f"Timeout after {max(5, int(timeout))}s\n" + _decode(stderr),
                        elapsed,
                        args,
                    )
                    raise subprocess.TimeoutExpired(
                        cmd=command,
                        timeout=max(5, int(timeout)),
                        output=stdout,
                        stderr=stderr,
                    )

        elapsed = max(0.0, time.perf_counter() - start)
        return process.returncode, stdout, stderr, elapsed
    finally:
        _ASTRO_THREAD_STATE.active_process = None


def _decode(data: bytes) -> str:
    return (data or b"").decode("utf-8", errors="replace").strip()


def _trim_log_text(value: object, limit: int = 4000) -> str:
    text = str(value or "").strip()

    if len(text) <= limit:
        return text

    return text[:limit] + f"... [trimmed {len(text) - limit} chars]"


def _log_script_failure(
    tool_name: str,
    return_code: int,
    stdout: str,
    stderr: str,
    elapsed: float,
    args: Iterable[str] | None = None,
):
    details = (
        f"tool={tool_name}; return_code={return_code}; elapsed={float(elapsed):.2f}s; "
        f"args={list(args or [])}; stderr={_trim_log_text(stderr)}; stdout={_trim_log_text(stdout)}"
    )
    log_warning("FZASTRO tool script failed", details)


@contextmanager
def _fzastro_import_path():
    fzastro_text = str(FZASTRO_DIR)
    inserted = False

    if fzastro_text not in sys.path:
        sys.path.insert(0, fzastro_text)
        inserted = True

    try:
        yield
    finally:
        if inserted:
            try:
                sys.path.remove(fzastro_text)
            except ValueError as exc:
                log_debug("FZASTRO import path removal skipped", exc)


def _load_module(module_name: str, file_path: Path):
    if not file_path.exists():
        raise FileNotFoundError(str(file_path))

    spec = importlib.util.spec_from_file_location(module_name, str(file_path))

    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {file_path}")

    module = importlib.util.module_from_spec(spec)

    with _fzastro_import_path():
        spec.loader.exec_module(module)

    return module


def _parse_ra_dec(text: str) -> Tuple[Optional[float], Optional[float]]:
    ra_match = re.search(r"(?im)^\s*RA:\s*([+-]?\d+(?:\.\d+)?)\s*°", text)
    dec_match = re.search(r"(?im)^\s*Dec:\s*([+-]?\d+(?:\.\d+)?)\s*°", text)

    if not ra_match or not dec_match:
        return None, None

    try:
        return float(ra_match.group(1)), float(dec_match.group(1))
    except ValueError:
        return None, None


def _parse_object_type(text: str) -> str:
    match = re.search(r"(?im)^\s*Type:\s*(.+?)\s*$", text)
    return match.group(1).strip() if match else ""


def _safe_slug(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
    clean = clean.strip("._-")
    return clean[:80] or "astro_output"


def _imagefetch_module():
    module = _load_module("fzastro_migrated_imagefetch", IMAGEFETCH_FILE)
    module.CACHE_DIR = ASTRO_IMAGE_CACHE_DIR
    return module


def lookup_survey_presets() -> List[Dict[str, str]]:
    """Return curated HiPS survey choices for LOOKUP previews."""
    try:
        imagefetch = _imagefetch_module()
        presets = imagefetch.lookup_survey_presets()
        if isinstance(presets, list):
            return [dict(item) for item in presets if isinstance(item, dict)]
    except Exception as exc:
        log_debug("astro_tools.lookup_survey_presets fallback used", exc)
    return [
        {"label": "Auto optical color · DSS2", "survey": ""},
        {"label": "DSS2 color · broadband optical", "survey": "DSS2/color"},
        {
            "label": "Finkbeiner H-alpha composite · narrowband full sky",
            "survey": "https://alasky.cds.unistra.fr/FinkbeinerHalpha/",
        },
    ]


def _format_pc_distance(distance_pc: Optional[float]) -> List[str]:
    if distance_pc is None:
        return []
    try:
        pc = float(distance_pc)
    except Exception:
        return []
    if pc <= 0:
        return []
    ly = pc * 3.261563777
    if ly >= 1_000_000:
        human = f"{ly / 1_000_000:.3g} Mly"
    elif ly >= 1_000:
        human = f"{ly / 1_000:.3g} kly"
    else:
        human = f"{ly:.3g} ly"
    return [f"Distance (pc): {pc:.4g}", f"             ({human})"]


_FAST_LITERATURE_OBJECTS: Dict[str, Dict[str, Any]] = {}


def _messier_key(query: str) -> Optional[str]:
    match = re.match(
        r"^\s*M\s*0*([1-9][0-9]{0,2})\s*$", str(query or ""), re.IGNORECASE
    )
    if not match:
        return None
    return f"M{int(match.group(1))}"


def _catalog_fallback_for_query(query: str) -> Optional[Dict[str, Any]]:
    clean = str(query or "").strip().casefold()
    messier = _messier_key(query)
    if messier and messier in _FAST_LITERATURE_OBJECTS:
        return dict(_FAST_LITERATURE_OBJECTS[messier])
    for item in _FAST_LITERATURE_OBJECTS.values():
        names = [item.get("display_name", ""), *list(item.get("aliases", []))]
        if any(clean == str(name).strip().casefold() for name in names):
            return dict(item)
    return None


# These objects are handled by the migrated FZASTRO/Horizons path, not by SIMBAD.
# SIMBAD is for stars/deep-sky/catalog objects; Solar System bodies, comets, and
# spacecraft need ephemerides from the original FZASTRO script.py resolver.
_FZASTRO_HORIZONS_NAMES = {
    "sun",
    "moon",
    "luna",
    "mercury",
    "venus",
    "earth",
    "mars",
    "jupiter",
    "saturn",
    "uranus",
    "neptune",
    "pluto",
    "phobos",
    "deimos",
    "io",
    "europa",
    "ganymede",
    "callisto",
    "amalthea",
    "himalia",
    "mimas",
    "enceladus",
    "tethys",
    "dione",
    "rhea",
    "titan",
    "hyperion",
    "iapetus",
    "phoebe",
    "miranda",
    "ariel",
    "umbriel",
    "titania",
    "oberon",
    "triton",
    "proteus",
    "nereid",
    "charon",
    "iss",
    "international space station",
    "space station",
    "hubble",
    "jwst",
    "james webb space telescope",
    "soho",
    "kepler",
    "tess",
    "gaia",
    "chandra",
    "curiosity",
    "perseverance",
    "ingenuity",
    "juno",
    "cassini",
    "parker solar probe",
    "solar orbiter",
    "voyager 1",
    "voyager 2",
    "new horizons",
    "lucy",
    "psyche",
}


def _normalise_horizons_query_key(value: str) -> str:
    clean = str(value or "").replace("’", "'").replace("ʻ", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", clean.strip()).casefold()


def _looks_like_comet_or_interstellar_query(value: str) -> bool:
    clean = _normalise_horizons_query_key(value)
    if not clean:
        return False
    # Examples: C/2020 F3, P/2023 X1, 1P/Halley, 2I/Borisov, 3I/ATLAS.
    return bool(
        re.match(
            r"^(?:[cp]/\d{4}\s+[a-z0-9]+|\d+\s*[pi]/|\d+\s*i/)", clean, re.IGNORECASE
        )
        or clean.startswith(("c/", "p/", "a/"))
        or "oumuamua" in clean
        or "borisov" in clean
    )


def _is_fzastro_horizons_target(query: str) -> bool:
    clean = _normalise_horizons_query_key(query)
    return clean in _FZASTRO_HORIZONS_NAMES or _looks_like_comet_or_interstellar_query(
        clean
    )


_PLANET_REFERENCE_NAMES = {
    "mercury",
    "venus",
    "earth",
    "mars",
    "jupiter",
    "saturn",
    "uranus",
    "neptune",
    "pluto",
}

_MOON_REFERENCE_NAMES = {
    "moon",
    "luna",
    "phobos",
    "deimos",
    "io",
    "europa",
    "ganymede",
    "callisto",
    "amalthea",
    "himalia",
    "mimas",
    "enceladus",
    "tethys",
    "dione",
    "rhea",
    "titan",
    "hyperion",
    "iapetus",
    "phoebe",
    "miranda",
    "ariel",
    "umbriel",
    "titania",
    "oberon",
    "triton",
    "proteus",
    "nereid",
    "charon",
}

_REFERENCE_BODY_PALETTES: Dict[
    str, Tuple[Tuple[int, int, int], Tuple[int, int, int]]
] = {
    "mercury": ((128, 122, 111), (204, 198, 184)),
    "venus": ((166, 126, 72), (246, 209, 139)),
    "earth": ((36, 85, 155), (90, 171, 111)),
    "mars": ((118, 61, 43), (229, 121, 71)),
    "jupiter": ((155, 111, 79), (237, 202, 155)),
    "saturn": ((170, 140, 83), (240, 215, 152)),
    "uranus": ((91, 168, 176), (189, 238, 239)),
    "neptune": ((40, 67, 150), (118, 150, 243)),
    "pluto": ((112, 92, 80), (210, 190, 171)),
    "moon": ((103, 103, 108), (213, 213, 216)),
}

_SOLAR_SYSTEM_REFERENCE_SEARCH_QUERIES = {
    "mercury": "Mercury planet NASA true color",
    "venus": "Venus planet NASA real image",
    "earth": "Earth planet NASA blue marble",
    "mars": "Mars planet NASA global mosaic",
    "jupiter": "Jupiter planet NASA Juno image",
    "saturn": "Saturn planet NASA Cassini image",
    "uranus": "Uranus planet NASA Voyager 2 image",
    "neptune": "Neptune planet NASA Voyager 2 image",
    "pluto": "Pluto planet NASA New Horizons image",
    "moon": "Moon NASA full disk real image",
    "phobos": "Phobos moon NASA image",
    "deimos": "Deimos moon NASA image",
    "io": "Io moon NASA Galileo image",
    "europa": "Europa moon NASA Galileo image",
    "ganymede": "Ganymede moon NASA Galileo image",
    "callisto": "Callisto moon NASA Galileo image",
    "mimas": "Mimas moon NASA Cassini image",
    "enceladus": "Enceladus moon NASA Cassini image",
    "tethys": "Tethys moon NASA Cassini image",
    "dione": "Dione moon NASA Cassini image",
    "rhea": "Rhea moon NASA Cassini image",
    "titan": "Titan moon NASA Cassini image",
    "hyperion": "Hyperion moon NASA Cassini image",
    "iapetus": "Iapetus moon NASA Cassini image",
    "phoebe": "Phoebe moon NASA Cassini image",
    "miranda": "Miranda moon NASA Voyager 2 image",
    "ariel": "Ariel moon NASA Voyager 2 image",
    "umbriel": "Umbriel moon NASA Voyager 2 image",
    "titania": "Titania moon NASA Voyager 2 image",
    "oberon": "Oberon moon NASA Voyager 2 image",
    "triton": "Triton moon NASA Voyager 2 image",
    "charon": "Charon moon NASA New Horizons image",
}

_SOLAR_SYSTEM_REFERENCE_STATIC_URLS = {
    "mars": "https://commons.wikimedia.org/wiki/Special:FilePath/Mars_Valles_Marineris_EDIT.jpg",
    "jupiter": "https://commons.wikimedia.org/wiki/Special:FilePath/Jupiter_and_its_shrunken_Great_Red_Spot.jpg",
    "saturn": "https://commons.wikimedia.org/wiki/Special:FilePath/Saturn_during_Equinox.jpg",
    "moon": "https://commons.wikimedia.org/wiki/Special:FilePath/FullMoon2010.jpg",
    "earth": "https://commons.wikimedia.org/wiki/Special:FilePath/The_Earth_seen_from_Apollo_17.jpg",
    "pluto": "https://commons.wikimedia.org/wiki/Special:FilePath/Pluto_in_True_Color_-_High-Res.jpg",
}


def _solar_system_reference_kind(query: str, object_type: object = "") -> str:
    clean = _normalise_horizons_query_key(query)
    object_text = str(object_type or "").casefold()
    if clean in _PLANET_REFERENCE_NAMES or "planet" in object_text:
        return "planet"
    if (
        clean in _MOON_REFERENCE_NAMES
        or "moon" in object_text
        or "satellite" in object_text
    ):
        return "moon"
    return ""


def _solar_system_reference_label(query: str) -> str:
    clean = _normalise_horizons_query_key(query)
    if clean == "luna":
        clean = "moon"
    if not clean:
        return "Solar-system body"
    return " ".join(part[:1].upper() + part[1:] for part in clean.split())


def _reference_body_key(query: str) -> str:
    clean = _normalise_horizons_query_key(query)
    if clean == "luna":
        clean = "moon"
    return re.sub(r"[^a-z0-9]+", "_", clean).strip("_") or "body"


def _bundled_solar_system_reference_image(query: str) -> Optional[Path]:
    key = _reference_body_key(query)
    for suffix in (".jpg", ".jpeg", ".png", ".webp"):
        path = SOLAR_SYSTEM_REFERENCE_DIR / f"{key}{suffix}"
        if path.exists() and path.is_file():
            return path
    return None


def _is_probably_image_payload(data: bytes, content_type: str = "") -> bool:
    head = bytes(data[:16])
    ctype = str(content_type or "").casefold()
    return (
        ctype.startswith("image/")
        or head.startswith(b"\xff\xd8\xff")
        or head.startswith(b"\x89PNG\r\n\x1a\n")
        or head.startswith(b"RIFF")
        and b"WEBP" in head[:16]
    )


def _download_reference_image(url: str, dest: Path, *, timeout: int = 12) -> bool:
    clean_url = str(url or "").strip()
    if not clean_url:
        return False
    request = Request(
        clean_url,
        headers={
            "User-Agent": "FZAstroAI/2.1 lookup reference image cache",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        },
    )
    with urlopen(request, timeout=max(3, int(timeout))) as response:
        content_type = response.headers.get("Content-Type", "")
        data = response.read(24 * 1024 * 1024)
    if not _is_probably_image_payload(data, content_type):
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return True


def _nasa_images_reference_url(query: str, *, timeout: int = 8) -> str:
    body_key = _reference_body_key(query)
    search_text = _SOLAR_SYSTEM_REFERENCE_SEARCH_QUERIES.get(
        body_key,
        f"{_solar_system_reference_label(query)} NASA planetary moon image",
    )
    api_url = (
        "https://images-api.nasa.gov/search?media_type=image&page_size=1&q="
        + quote_plus(search_text)
    )
    request = Request(api_url, headers={"User-Agent": "FZAstroAI/2.1 lookup"})
    with urlopen(request, timeout=max(3, int(timeout))) as response:
        payload = json.loads(response.read(2 * 1024 * 1024).decode("utf-8", "replace"))
    items = ((payload or {}).get("collection") or {}).get("items") or []
    for item in items:
        for link in item.get("links") or []:
            href = str(link.get("href") or "").strip()
            if href and str(link.get("render") or "").casefold() == "image":
                return href
        href = str(item.get("href") or "").strip()
        if href:
            return href
    return ""


def _fetch_solar_system_real_reference_image(
    query: str, kind: str, *, width: int = 1536, height: int = 1024
) -> Optional[AstroToolResult]:
    """Return a real local/cached reference image when one is available.

    Preference order:
    1. Bundled app resource in fzastro_ai/resources/astro_reference_images.
    2. Cached online image from a previous lookup.
    3. Static trusted file URL / NASA Images API result, cached locally.

    The deterministic painted disk remains only a final offline fallback.
    """
    if not kind:
        return None
    key = _reference_body_key(query)
    bundled = _bundled_solar_system_reference_image(query)
    if bundled is not None:
        return AstroToolResult(
            title="Solar-system real reference image",
            text=f"Real bundled reference image: {bundled}",
            files=[str(bundled)],
            success=True,
            metadata={
                "reference_image": str(bundled),
                "reference_image_kind": kind,
                "reference_image_source": "bundled real image",
            },
        )

    if os.environ.get("FZASTRO_LOOKUP_REAL_REFERENCE_IMAGES", "1").strip() == "0":
        return None

    cache_dir = APP_DIR / "lookup_reference_images"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached_candidates = [
        cache_dir / f"solar_real_{key}.jpg",
        cache_dir / f"solar_real_{key}.png",
        cache_dir / f"solar_real_{key}.webp",
    ]
    for path in cached_candidates:
        if path.exists() and path.is_file():
            return AstroToolResult(
                title="Solar-system real reference image",
                text=f"Cached real reference image: {path}",
                files=[str(path)],
                success=True,
                metadata={
                    "reference_image": str(path),
                    "reference_image_kind": kind,
                    "reference_image_source": "cached real image",
                },
            )

    urls = []
    static_url = _SOLAR_SYSTEM_REFERENCE_STATIC_URLS.get(key)
    if static_url:
        urls.append((static_url, "static real image"))
    try:
        nasa_url = _nasa_images_reference_url(query, timeout=8)
        if nasa_url:
            urls.append((nasa_url, "NASA Images API"))
    except Exception as exc:
        log_debug("astro_tools.lookup NASA reference search skipped", exc)

    for url, source_label in urls:
        suffix = ".png" if ".png" in url.casefold() else ".jpg"
        dest = cache_dir / f"solar_real_{key}{suffix}"
        try:
            if _download_reference_image(url, dest, timeout=12):
                return AstroToolResult(
                    title="Solar-system real reference image",
                    text=f"Real reference image: {dest}",
                    files=[str(dest)],
                    success=True,
                    metadata={
                        "reference_image": str(dest),
                        "reference_image_kind": kind,
                        "reference_image_source": source_label,
                        "reference_image_url": url,
                    },
                )
        except Exception as exc:
            log_debug(
                "astro_tools.lookup real reference download skipped",
                f"{source_label}: {exc}",
            )
    return None


def _generate_solar_system_reference_image(
    query: str, width: int = 1536, height: int = 1024
) -> AstroToolResult:
    """Return a real cached reference image for planets/moons when possible.

    HIPS sky-survey frames are not useful for nearby Solar System bodies because
    their apparent position and disk change with time. LOOKUP therefore tries to
    use a real bundled/cached/NASA reference image first. The deterministic disk
    below remains only an offline fallback and is marked as generated fallback
    metadata so the UI never mistakes it for a real source frame.
    """
    kind = _solar_system_reference_kind(query)
    if not kind:
        return AstroToolResult(
            title="Reference image", text="No reference image needed."
        )

    real_reference = _fetch_solar_system_real_reference_image(
        query, kind, width=width, height=height
    )
    if real_reference is not None:
        return real_reference

    try:
        from PIL import Image, ImageDraw, ImageFilter
    except Exception as exc:
        return AstroToolResult(
            title="Reference image",
            text=f"Solar-system reference image skipped: Pillow unavailable ({exc})",
            success=False,
        )

    clean_key = (
        re.sub(r"[^a-z0-9]+", "_", _normalise_horizons_query_key(query)).strip("_")
        or "body"
    )
    width = int(max(480, min(1920, int(width or 1536))))
    height = int(max(360, min(1280, int(height or 1024))))
    cache_dir = APP_DIR / "lookup_reference_images"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"solar_ref_{clean_key}_{width}x{height}.png"
    if path.exists():
        return AstroToolResult(
            title="Solar-system reference image",
            text=f"Reference image: {path}",
            files=[str(path)],
            success=True,
            metadata={
                "reference_image": str(path),
                "reference_image_kind": kind,
                "reference_image_source": "generated fallback",
            },
        )

    label = _solar_system_reference_label(query)
    palette_key = _normalise_horizons_query_key(query)
    if palette_key == "luna" or palette_key in _MOON_REFERENCE_NAMES:
        palette_key = "moon"
    base, highlight = _REFERENCE_BODY_PALETTES.get(
        palette_key,
        (
            ((92, 100, 110), (210, 216, 224))
            if kind == "moon"
            else ((77, 102, 130), (177, 198, 224))
        ),
    )

    image = Image.new("RGB", (width, height), (6, 9, 13))
    draw = ImageDraw.Draw(image, "RGBA")
    for y in range(height):
        tone = int(9 + 18 * y / max(1, height - 1))
        draw.line([(0, y), (width, y)], fill=(tone // 2, tone, tone + 7, 255))

    # Deterministic star field keyed to the requested body.
    seed = int(hashlib.sha1(clean_key.encode("utf-8")).hexdigest()[:8], 16)
    for idx in range(150):
        seed = (1103515245 * seed + 12345) & 0x7FFFFFFF
        x = seed % width
        seed = (1103515245 * seed + 12345) & 0x7FFFFFFF
        y = seed % height
        alpha = 55 + (seed % 130)
        size = 1 + (seed % 3 == 0)
        draw.ellipse((x, y, x + size, y + size), fill=(210, 225, 255, alpha))

    cx, cy = width // 2, int(height * 0.47)
    radius = int(min(width, height) * (0.27 if palette_key != "saturn" else 0.22))
    # Glow.
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow, "RGBA")
    gdraw.ellipse(
        (cx - radius - 25, cy - radius - 25, cx + radius + 25, cy + radius + 25),
        fill=(*highlight, 38),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(22))
    image = Image.alpha_composite(image.convert("RGBA"), glow)
    draw = ImageDraw.Draw(image, "RGBA")

    if palette_key == "saturn":
        ring_h = max(18, radius // 3)
        draw.ellipse(
            (
                cx - int(radius * 1.85),
                cy - ring_h,
                cx + int(radius * 1.85),
                cy + ring_h,
            ),
            outline=(219, 198, 145, 190),
            width=max(4, radius // 18),
        )
        draw.ellipse(
            (
                cx - int(radius * 1.55),
                cy - ring_h // 2,
                cx + int(radius * 1.55),
                cy + ring_h // 2,
            ),
            outline=(131, 111, 79, 150),
            width=max(3, radius // 28),
        )

    # Body disk with simple directional shading.
    for r in range(radius, 0, -1):
        f = r / max(1, radius)
        mix = 1.0 - f
        col = tuple(int(base[i] * f + highlight[i] * mix) for i in range(3))
        shade = 0.70 + 0.30 * mix
        fill = tuple(int(c * shade) for c in col) + (255,)
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill)

    if palette_key in {"jupiter", "saturn"}:
        for offset, alpha in ((-0.45, 90), (-0.22, 70), (0.05, 100), (0.31, 75)):
            y = cy + int(radius * offset)
            draw.rounded_rectangle(
                (cx - radius, y - radius // 18, cx + radius, y + radius // 18),
                radius=radius // 20,
                fill=(95, 64, 44, alpha),
            )
    elif kind == "moon":
        for n in range(20):
            seed = (1103515245 * seed + 12345) & 0x7FFFFFFF
            rx = cx - radius + (seed % (2 * radius))
            seed = (1103515245 * seed + 12345) & 0x7FFFFFFF
            ry = cy - radius + (seed % (2 * radius))
            if (rx - cx) ** 2 + (ry - cy) ** 2 > radius**2:
                continue
            rr = max(3, radius // (14 + (seed % 22)))
            draw.ellipse(
                (rx - rr, ry - rr, rx + rr, ry + rr),
                fill=(48, 50, 55, 55),
                outline=(230, 230, 235, 35),
            )
    elif palette_key == "mars":
        draw.pieslice(
            (cx - radius // 2, cy - radius, cx + radius // 2, cy - radius // 3),
            180,
            360,
            fill=(235, 218, 188, 115),
        )

    # Terminator shading for a disk-like reference look.
    shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow, "RGBA")
    sdraw.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius), fill=(0, 0, 0, 0)
    )
    sdraw.rectangle((cx, cy - radius, cx + radius + 4, cy + radius), fill=(0, 0, 0, 50))
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(8, radius // 10)))
    image = Image.alpha_composite(image, shadow)
    draw = ImageDraw.Draw(image, "RGBA")

    title = f"{label} reference image"
    note = "Generated fallback disk · no real reference image available"
    draw.rounded_rectangle(
        (28, height - 82, width - 28, height - 24),
        radius=14,
        fill=(8, 14, 20, 190),
        outline=(77, 93, 110, 120),
        width=1,
    )
    draw.text((48, height - 72), title, fill=(245, 249, 255, 255))
    draw.text((48, height - 48), note, fill=(170, 188, 205, 255))

    image.convert("RGB").save(path, "PNG")
    return AstroToolResult(
        title="Solar-system reference image",
        text=f"Reference image: {path}",
        files=[str(path)],
        success=True,
        metadata={
            "reference_image": str(path),
            "reference_image_kind": kind,
            "reference_image_source": "generated fallback",
        },
    )


def _table_column(table: Any, *names: str) -> Optional[str]:
    columns = getattr(table, "colnames", []) or []
    exact = {str(c): str(c) for c in columns}
    lowered = {str(c).casefold(): str(c) for c in columns}

    for name in names:
        if name in exact:
            return exact[name]
        key = str(name).casefold()
        if key in lowered:
            return lowered[key]

    # Astroquery SIMBAD 0.4.8+ switched to lower-case TAP column
    # names, and extra fields can also be returned with service/table
    # prefixes or suffixes depending on the installed astroquery version.
    # Keep matching conservative: only accept exact normalized names,
    # then simple suffix/prefix forms.
    normalized = {re.sub(r"[^a-z0-9]+", "", str(c).casefold()): str(c) for c in columns}
    for name in names:
        key = re.sub(r"[^a-z0-9]+", "", str(name).casefold())
        if key in normalized:
            return normalized[key]

    for name in names:
        key = re.sub(r"[^a-z0-9]+", "", str(name).casefold())
        if not key or len(key) < 3:
            continue
        for column in columns:
            col_key = re.sub(r"[^a-z0-9]+", "", str(column).casefold())
            if col_key == key or col_key.endswith(key) or col_key.startswith(key):
                return str(column)
    return None


def _table_value(row: Any, table: Any, *names: str) -> Any:
    col = _table_column(table, *names)
    if not col:
        return None
    try:
        return row[col]
    except Exception:
        return None


def _float_or_none(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        text = str(value).strip().replace("−", "-")
        if not text or text.lower() in {"--", "nan", "none", "masked"}:
            return None
        val = float(text.split()[0])
        if val == val and abs(val) != float("inf"):
            return val
    except Exception:
        return None
    return None


def _clean_aliases(values: Iterable[Any]) -> List[str]:
    cleaned: List[str] = []
    seen = set()
    for value in values:
        text = re.sub(r"\s+", " ", str(value or "").strip())
        if not text or text.lower() in {"none", "masked", "--"}:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned


def _friendly_type(raw_type: Any) -> str:
    text = re.sub(r"\s+", " ", str(raw_type or "").strip())
    low = text.casefold()
    code = re.sub(r"[^A-Za-z0-9*+]", "", text).upper()
    tokens = {t.strip().upper() for t in re.split(r"[|,;\s]+", text) if t.strip()}
    if not text:
        return "Object"

    # SIMBAD commonly returns compact object codes, not prose.  Preserve the old
    # script.py behavior by mapping those codes before formatting output or
    # deciding which distance-ladder branch is allowed.
    nebula_codes = {"PN", "HII", "SNR", "C+N", "RNE", "EMN", "BNE", "DNE", "NEB"}
    cluster_codes = {"CL*", "OPC", "GLC", "AS*", "OC", "GC"}
    galaxy_codes = {"G", "GAL", "AGN", "SY1", "SY2", "BLLAC", "QSO"}
    star_codes = {"*", "V*", "PM*"}

    if (
        "galaxy" in low
        or low in {"g", "gal", "galaxy"}
        or code in galaxy_codes
        or bool(tokens & galaxy_codes)
        or "|g|" in low
    ):
        return "Galaxy"
    if (
        "nebula" in low
        or "hii" in low
        or "emission" in low
        or code in nebula_codes
        or bool(tokens & nebula_codes)
    ):
        return "Nebula"
    if "cluster" in low or code in cluster_codes or bool(tokens & cluster_codes):
        return "Cluster"
    if "quasar" in low or "qso" in low or code == "QSO" or "QSO" in tokens:
        return "Quasar"
    if (
        "star" in low
        or low in {"*", "star"}
        or code in star_codes
        or bool(tokens & star_codes)
    ):
        return "Star"
    return text[:80]


def _distance_type_code(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9*+]", "", str(value or "").strip()).upper()


def _is_nebula_or_cluster_type(value: Any) -> bool:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    low = text.casefold()
    code = _distance_type_code(text)
    tokens = {t.strip().upper() for t in re.split(r"[|,;\s]+", text) if t.strip()}
    nebula_codes = {"PN", "HII", "SNR", "C+N", "RNE", "EMN", "BNE", "DNE", "NEB"}
    cluster_codes = {"CL*", "OPC", "GLC", "AS*", "OC", "GC"}
    return (
        low in {"nebula", "cluster", "hii region", "open cluster"}
        or "nebula" in low
        or "cluster" in low
        or "hii" in low
        or code in nebula_codes
        or code in cluster_codes
        or bool(tokens & nebula_codes)
        or bool(tokens & cluster_codes)
    )


def _is_extragalactic_distance_type(value: Any) -> bool:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    low = text.casefold()
    code = _distance_type_code(text)
    tokens = {t.strip().upper() for t in re.split(r"[|,;\s]+", text) if t.strip()}
    galaxy_codes = {"G", "GAL", "AGN", "SY1", "SY2", "BLLAC", "QSO"}
    return (
        low in {"galaxy", "quasar", "qso", "agn"}
        or code in galaxy_codes
        or bool(tokens & galaxy_codes)
    )


def _adql_string(value: str) -> str:
    """Return a safely quoted ADQL string literal."""
    return "'" + str(value or "").replace("'", "''") + "'"


def _simbad_identifier_candidates(query: str) -> List[str]:
    """Build a small set of identifier spellings accepted by SIMBAD."""
    clean = re.sub(r"\s+", " ", str(query or "").strip())
    candidates: List[str] = []

    def add(value: str):
        value = re.sub(r"\s+", " ", str(value or "").strip())
        if value and value not in candidates:
            candidates.append(value)

    add(clean)

    match = re.match(r"^(M|NGC|IC)\s*0*([0-9]+)\s*$", clean, re.IGNORECASE)
    if match:
        catalog = match.group(1).upper()
        number = str(int(match.group(2)))
        add(f"{catalog} {number}")
        add(f"{catalog}{number}")

    messier = _messier_key(clean)
    if messier:
        add(f"M {int(messier[1:])}")
        add(messier)

    return candidates[:8]


def _split_env_urls(name: str, defaults: Iterable[str]) -> List[str]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return [str(item).strip() for item in defaults if str(item).strip()]
    values = [item.strip() for item in re.split(r"[;,]", raw) if item.strip()]
    return values or [str(item).strip() for item in defaults if str(item).strip()]


def _network_timeout_pair(timeout: int, *, default_read: int = 6) -> Tuple[int, int]:
    """Return a connect/read timeout pair that keeps the UI responsive."""
    try:
        requested = int(timeout)
    except Exception:
        requested = default_read
    try:
        cap = int(os.environ.get("FZASTRO_LOOKUP_READ_TIMEOUT", str(default_read)))
    except Exception:
        cap = default_read
    read_timeout = max(3, min(max(3, requested), max(3, cap)))
    return 3, read_timeout


def _lookup_cache_key(query: str) -> str:
    clean = re.sub(r"\s+", " ", str(query or "").strip().casefold())
    digest = hashlib.sha1(clean.encode("utf-8", "ignore")).hexdigest()
    return digest[:24]


def _lookup_cache_path(query: str) -> Path:
    return ASTRO_LOOKUP_CACHE_DIR / f"{_lookup_cache_key(query)}.json"


def _load_fast_lookup_cache(
    query: str,
    *,
    max_age_days: Optional[int] = 30,
    allow_stale: bool = False,
) -> Optional[Tuple[Dict[str, Any], List[str], str]]:
    path = _lookup_cache_path(query)
    try:
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        saved_at = float(data.get("saved_at", 0.0) or 0.0)
        if max_age_days is not None and not allow_stale:
            max_age = max(1, int(max_age_days)) * 86400
            if time.time() - saved_at > max_age:
                return None
        info = dict(data.get("info") or {})
        aliases = _clean_aliases(data.get("aliases") or [])
        if info.get("ra_deg") is None or info.get("dec_deg") is None:
            return None
        source = str(data.get("source") or "cache")
        return info, aliases, source
    except Exception as exc:
        log_debug("astro_tools.fast_lookup cache read skipped", exc)
        return None


def _store_fast_lookup_cache(
    query: str, info: Dict[str, Any], aliases: Iterable[Any], source: str
):
    try:
        if not info or info.get("ra_deg") is None or info.get("dec_deg") is None:
            return
        ASTRO_LOOKUP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "query": str(query or "").strip(),
            "saved_at": time.time(),
            "source": source,
            "info": info,
            "aliases": _clean_aliases(aliases),
        }
        _lookup_cache_path(query).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except Exception as exc:
        log_debug("astro_tools.fast_lookup cache write skipped", exc)


def _simbad_tap_csv(adql: str, timeout: int) -> List[Dict[str, str]]:
    """Run a direct SIMBAD TAP query without astroquery/astropy package-data loading.

    TAP can occasionally stall.  Keep each HTTP attempt short and try the
    alternate Strasbourg hostname before failing, instead of blocking the UI.
    """
    import requests

    errors: List[str] = []
    endpoints = _split_env_urls("FZASTRO_SIMBAD_TAP_ENDPOINTS", SIMBAD_TAP_ENDPOINTS)
    for endpoint in endpoints:
        _check_cancelled()
        try:
            response = requests.post(
                endpoint,
                data={
                    "request": "doQuery",
                    "lang": "ADQL",
                    "format": "csv",
                    "query": adql,
                },
                timeout=_network_timeout_pair(timeout, default_read=6),
                headers={"User-Agent": "FZAstroAI/astro-lookup"},
            )
            response.raise_for_status()
            text = response.text or ""
            upper_head = text[:1000].upper()
            if "<VOTABLE" in text[:300].upper() or (
                "QUERY_STATUS" in upper_head and "ERROR" in upper_head
            ):
                raise RuntimeError(text[:600].strip())
            reader = csv.DictReader(StringIO(text))
            return [dict(row) for row in reader]
        except Exception as exc:
            errors.append(f"{endpoint}: {exc}")
            log_debug(
                "astro_tools.fast_lookup SIMBAD TAP endpoint skipped",
                f"{endpoint}: {exc}",
            )

    raise RuntimeError("; ".join(errors) if errors else "SIMBAD TAP request failed")


def _fetch_simbad_aliases_for_oid(oid: Any, timeout: int = 6) -> List[str]:
    """Return every SIMBAD identifier for an object oid.

    SIMBAD stores aliases in the `ident` table.  Do not add an artificial
    `TOP` limit here: the LOOKUP result card should show the complete alias set
    returned by SIMBAD, not only a preview subset.
    """
    oid_text = str(oid or "").strip().lstrip("@")
    if not oid_text.isdigit():
        return []
    alias_rows = _simbad_tap_csv(
        f"SELECT id FROM ident WHERE oidref = {int(oid_text)} ORDER BY id",
        max(4, min(int(timeout), 8)),
    )
    return _clean_aliases([_row_value_any(item, "id", "ID") for item in alias_rows])


def _lookup_clean_text_value(value: Any, *, max_chars: int = 240) -> str:
    """Normalize a TAP/CSV value for metadata and Qt-rich-text rendering."""
    if value is None:
        return ""
    text = re.sub(r"\s+", " ", str(value).strip())
    if not text or text.casefold() in {"--", "nan", "none", "null", "masked"}:
        return ""
    if max_chars > 0 and len(text) > max_chars:
        return text[: max_chars - 1].rstrip() + "…"
    return text


def _lookup_clean_tap_row(
    row: Dict[str, Any], *, max_chars: int = 240
) -> Dict[str, str]:
    """Return all non-empty TAP row fields with stable, readable key names."""
    clean: Dict[str, str] = {}
    for key, value in (row or {}).items():
        field = re.sub(r"\s+", " ", str(key or "").strip())
        if not field:
            continue
        # TAP CSV headers sometimes include table prefixes. Preserve the useful
        # field name while avoiding duplicate labels in the detail card.
        if "." in field:
            field = field.rsplit(".", 1)[-1]
        text = _lookup_clean_text_value(value, max_chars=max_chars)
        if not text:
            continue
        if field not in clean:
            clean[field] = text
    return clean


def _lookup_research_row_limit() -> int:
    """Small safety cap for large SIMBAD measurement tables.

    This is intentionally configurable. Some objects have very large literature
    measurement sets; unbounded TAP pulls would make LOOKUP feel frozen and could
    stress public CDS services.
    """
    raw = os.environ.get("FZASTRO_LOOKUP_RESEARCH_ROW_LIMIT", "200").strip()
    try:
        value = int(raw)
    except Exception:
        value = 200
    return max(1, min(value, 1000))


def _simbad_research_tables() -> List[Tuple[str, str]]:
    """Return SIMBAD measurement tables requested for research lookup panels."""
    raw = os.environ.get("FZASTRO_LOOKUP_RESEARCH_TABLES", "").strip()
    if not raw:
        return list(SIMBAD_RESEARCH_TABLES)
    requested = [item.strip() for item in re.split(r"[;,]", raw) if item.strip()]
    labels = {name.casefold(): label for name, label in SIMBAD_RESEARCH_TABLES}
    return [(name, labels.get(name.casefold(), name)) for name in requested]


def _fetch_simbad_research_tables_for_oid(
    oid: Any, *, timeout: int = 6
) -> Dict[str, Dict[str, Any]]:
    """Fetch broad SIMBAD measurement rows for an object.

    Each table is isolated: a missing/renamed table or endpoint timeout should
    not break the main LOOKUP result. Rows include all non-empty columns returned
    by TAP, not a hand-picked subset.
    """
    oid_text = str(oid or "").strip().lstrip("@")
    if not oid_text.isdigit():
        return {}
    limit = _lookup_research_row_limit()
    details: Dict[str, Dict[str, Any]] = {}
    for table, label in _simbad_research_tables():
        _check_cancelled()
        # Keep table names conservative; they come from constants or an advanced
        # local environment override, not from user query text.
        safe_table = re.sub(r"[^A-Za-z0-9_]", "", str(table or "").strip())
        if not safe_table:
            continue
        try:
            rows = _simbad_tap_csv(
                f"SELECT TOP {limit} * FROM {safe_table} WHERE oidref = {int(oid_text)}",
                # Research rows are extra display data. Keep each table attempt
                # short so LOOKUP still fails soft when CDS is slow.
                max(3, min(int(timeout), 3)),
            )
        except Exception as exc:
            log_debug(
                "astro_tools.fast_lookup SIMBAD research table skipped",
                f"{safe_table}: {exc}",
            )
            continue
        clean_rows = [
            clean for clean in (_lookup_clean_tap_row(row) for row in rows) if clean
        ]
        if clean_rows:
            details[safe_table] = {
                "label": label,
                "row_limit": limit,
                "rows": clean_rows,
            }
    return details


def _enrich_fast_object_details_via_tap(
    info: Dict[str, Any],
    aliases: Iterable[Any],
    *,
    timeout: int = 6,
) -> Tuple[Dict[str, Any], List[str]]:
    """Restore the rich object details the old astroquery path exposed.

    Sesame is the preferred fast resolver, but it does not always return the
    full SIMBAD identifier list or stellar motion fields. When the resolver
    gives us the SIMBAD oid, run one short TAP enrichment query for the details
    that matter in the desktop lookup output: canonical main id, proper motion,
    redshift/radial velocity, parallax, and every SIMBAD alias.
    """
    out = dict(info or {})
    merged_aliases = _clean_aliases(aliases or [])
    oid = str(out.get("oid") or "").strip().lstrip("@")
    if not oid.isdigit():
        return out, merged_aliases

    try:
        rows = _simbad_tap_csv(
            f"SELECT TOP 1 * FROM basic WHERE basic.oid = {oid}",
            max(4, min(int(timeout), 8)),
        )
        if rows:
            row = rows[0]
            basic_fields = _lookup_clean_tap_row(row)
            if basic_fields:
                out["simbad_basic_fields"] = basic_fields

            display_name = str(_row_value_any(row, "main_id") or "").strip()
            if display_name:
                out["display_name"] = display_name
            object_type = _friendly_type(_row_value_any(row, "otype"))
            if object_type and object_type != "Object":
                out["object_type"] = object_type

            detail_map = {
                "ra_deg": ("ra", "RA"),
                "dec_deg": ("dec", "DEC"),
                "pmra_masyr": ("pmra", "PMRA"),
                "pmdec_masyr": ("pmdec", "PMDEC"),
                "parallax_mas": ("plx_value", "parallax", "PLX_VALUE"),
                "redshift": ("rvz_redshift", "z_value", "redshift"),
                "radial_velocity_kms": ("rvz_radvel", "radvel", "radial_velocity"),
                "spectral_type": ("sp_type", "sptype", "spectral_type"),
                "morphology": ("morph_type", "mtype", "morphology"),
                "angular_size_major": ("galdim_majaxis", "diameter", "majaxis"),
                "angular_size_minor": ("galdim_minaxis", "minaxis"),
                "angular_size_angle": ("galdim_angle", "posangle"),
            }
            for key, names in detail_map.items():
                raw_value = _row_value_any(row, *names)
                if key in {"spectral_type", "morphology"}:
                    text_value = _lookup_clean_text_value(raw_value)
                    if text_value and out.get(key) in (None, ""):
                        out[key] = text_value
                    continue
                value = _float_or_none(raw_value)
                if value is None:
                    continue
                if key.startswith("pm") or out.get(key) is None:
                    out[key] = value
    except Exception as exc:
        log_debug("astro_tools.fast_lookup detail enrichment skipped", exc)

    try:
        tap_aliases = _fetch_simbad_aliases_for_oid(oid, timeout=timeout)
        main_id = out.get("display_name")
        merged_aliases = _clean_aliases([main_id, *merged_aliases, *tap_aliases])
        out["_simbad_aliases_complete"] = True
    except Exception as exc:
        log_debug("astro_tools.fast_lookup alias enrichment skipped", exc)

    if not out.get("simbad_measurements"):
        research_tables = _fetch_simbad_research_tables_for_oid(oid, timeout=timeout)
        if research_tables:
            out["simbad_measurements"] = research_tables
        out["_simbad_research_enriched"] = True
    elif out.get("simbad_measurements"):
        out["_simbad_research_enriched"] = True

    if oid.isdigit():
        out["_simbad_details_enriched"] = True
    return out, merged_aliases


def _xml_child_text(parent: Any, *names: str) -> str:
    if parent is None:
        return ""
    for name in names:
        try:
            child = parent.find(name)
        except Exception:
            child = None
        if child is not None and child.text is not None:
            text = str(child.text).strip()
            if text:
                return text
    return ""


def _xml_nested_text(parent: Any, child_name: str, nested_name: str = "v") -> str:
    child = parent.find(child_name) if parent is not None else None
    if child is None:
        return ""
    nested = child.find(nested_name)
    if nested is not None and nested.text is not None:
        return str(nested.text).strip()
    return str(child.text or "").strip()


def _simbad_fast_lookup_via_sesame(
    query: str, timeout: int = 6
) -> Tuple[Dict[str, Any], List[str]]:
    """Resolve an object through CDS Sesame before using slower TAP enrichment.

    Sesame returns coordinates, object type, velocity/parallax/magnitudes and
    aliases in a compact XML response.  It is a better default for a desktop UI
    because it is cached by CDS and does not require astroquery or TAP metadata.

    Distance is still enriched after a successful Sesame resolve when the
    response exposes the SIMBAD oid.  This preserves the fast, reliable resolver
    path while restoring the distance details that came from SIMBAD's
    measurement table in the older direct-TAP implementation.
    """
    import requests

    clean = re.sub(r"\s+", " ", str(query or "").strip())
    if not clean:
        raise RuntimeError("No object name supplied.")

    encoded = quote_plus(clean)
    endpoints = [
        pattern.format(query=encoded)
        for pattern in _split_env_urls(
            "FZASTRO_SESAME_ENDPOINT_PATTERNS",
            SESAME_LOOKUP_ENDPOINT_PATTERNS,
        )
    ]

    errors: List[str] = []
    for endpoint in endpoints:
        _check_cancelled()
        try:
            response = requests.get(
                endpoint,
                timeout=_network_timeout_pair(timeout, default_read=5),
                headers={"User-Agent": "FZAstroAI/astro-lookup"},
            )
            response.raise_for_status()
            text = response.text or ""
            if "<Sesame" not in text and "<Resolver" not in text:
                raise RuntimeError(text[:300].strip() or "Empty Sesame response")
            root = ET.fromstring(text)
            resolvers = list(root.findall(".//Resolver"))
            if not resolvers:
                raise RuntimeError("No Sesame resolver result returned.")

            resolver = None
            for item in resolvers:
                if _xml_child_text(item, "jradeg") and _xml_child_text(item, "jdedeg"):
                    resolver = item
                    break
            if resolver is None:
                resolver = resolvers[0]

            ra_deg = _float_or_none(_xml_child_text(resolver, "jradeg"))
            dec_deg = _float_or_none(_xml_child_text(resolver, "jdedeg"))
            if ra_deg is None or dec_deg is None:
                raise RuntimeError("Sesame returned no usable coordinates.")

            display_name = _xml_child_text(resolver, "oname") or clean
            aliases = _clean_aliases(
                [
                    display_name,
                    clean,
                    *[
                        str(alias.text or "").strip()
                        for alias in resolver.findall("alias")
                    ],
                ]
            )

            info: Dict[str, Any] = {
                "display_name": display_name,
                "object_type": _friendly_type(_xml_child_text(resolver, "otype")),
                "ra_deg": ra_deg,
                "dec_deg": dec_deg,
                "parallax_mas": _float_or_none(
                    _xml_nested_text(resolver, "plx", "v")
                    or _xml_child_text(resolver, "plx")
                ),
                "radial_velocity_kms": _float_or_none(
                    _xml_nested_text(resolver, "Vel", "v")
                    or _xml_child_text(resolver, "Vel")
                ),
            }

            mtype = _xml_child_text(resolver, "MType")
            if mtype and info.get("object_type") == "Galaxy":
                info["morphology"] = mtype

            oid_text = _xml_child_text(resolver, "oid").lstrip("@")
            if oid_text.isdigit():
                info["oid"] = oid_text

            for mag in resolver.findall("mag"):
                band = str(mag.attrib.get("band") or "").strip().upper()
                value = _float_or_none(
                    _xml_nested_text(mag, "v") or _xml_child_text(mag, "v")
                )
                if value is None or not band:
                    continue
                photometry_bands = dict(info.get("photometry_bands") or {})
                photometry_bands[band] = value
                info["photometry_bands"] = photometry_bands
                if band in {"B", "V", "G"}:
                    info[f"mag_{band}"] = value

            info, aliases = _enrich_fast_object_details_via_tap(
                info, aliases, timeout=min(int(timeout), 6)
            )
            info.update(
                _enrich_fast_distance(
                    info, timeout=min(int(timeout), 5), query=clean, aliases=aliases
                )
            )
            return info, aliases
        except Exception as exc:
            errors.append(f"{endpoint}: {exc}")
            log_debug(
                "astro_tools.fast_lookup Sesame endpoint skipped", f"{endpoint}: {exc}"
            )

    raise RuntimeError("; ".join(errors) if errors else "Sesame lookup failed")


def _row_value_any(row: Dict[str, Any], *names: str) -> Any:
    """Return a CSV row value, allowing case and table-prefix differences."""
    if not row:
        return None
    wanted = {re.sub(r"[^a-z0-9]+", "", name.casefold()) for name in names if name}
    for key, value in row.items():
        norm = re.sub(r"[^a-z0-9]+", "", str(key or "").casefold())
        if norm in wanted:
            return value
        for want in wanted:
            if norm.endswith(want):
                return value
    return None


def _distance_unit_to_pc_factor(unit: Any) -> Optional[float]:
    text = re.sub(r"\s+", "", str(unit or "").strip().lower())
    if text in {"pc", "parsec", "parsecs"}:
        return 1.0
    if text in {"kpc", "kiloparsec", "kiloparsecs"}:
        return 1.0e3
    if text in {"mpc", "megaparsec", "megaparsecs"}:
        return 1.0e6
    return None


def _simbad_distance_for_oid_via_tap(oid: str, timeout: int = 10) -> Dict[str, Any]:
    """Fetch SIMBAD's mesDistance values for an object and return a robust pc estimate.

    The direct TAP lookup intentionally bypasses astroquery.  Distance in SIMBAD
    is not a single field in `basic`; it is stored as measurement rows in
    `mesDistance`, with values in pc/kpc/Mpc depending on the row.
    """
    oid_text = str(oid or "").strip()
    if not oid_text or not oid_text.isdigit():
        return {}
    try:
        rows = _simbad_tap_csv(
            f"SELECT TOP 80 * FROM mesDistance WHERE oidref = {int(oid_text)}",
            max(5, min(int(timeout), 10)),
        )
    except Exception as exc:
        log_debug("astro_tools.fast_lookup SIMBAD mesDistance skipped", exc)
        return {}

    values_pc: List[float] = []
    methods: List[str] = []
    refs: List[str] = []
    for row in rows:
        raw_value = _row_value_any(
            row, "dist", "distance", "mesDistance.dist", "mesDistance.distance"
        )
        raw_unit = _row_value_any(row, "unit", "mesDistance.unit")
        value = _float_or_none(raw_value)
        factor = _distance_unit_to_pc_factor(raw_unit)
        if value is None or factor is None or value <= 0:
            continue
        values_pc.append(float(value) * factor)
        method = str(_row_value_any(row, "method", "mesDistance.method") or "").strip()
        ref = str(
            _row_value_any(
                row, "bibcode", "ref", "mesDistance.bibcode", "mesDistance.ref"
            )
            or ""
        ).strip()
        if method and method not in methods:
            methods.append(method)
        if ref and ref not in refs:
            refs.append(ref)

    if not values_pc:
        return {}

    values_pc.sort()
    mid = len(values_pc) // 2
    if len(values_pc) % 2:
        distance_pc = values_pc[mid]
    else:
        distance_pc = 0.5 * (values_pc[mid - 1] + values_pc[mid])

    details: Dict[str, Any] = {
        "distance_pc": distance_pc,
        "distance_method": (
            f"SIMBAD mesDistance median ({len(values_pc)} values)"
            if len(values_pc) > 1
            else "SIMBAD mesDistance"
        ),
    }
    if methods:
        details["distance_method"] += f"; methods: {', '.join(methods[:4])}"
        if len(methods) > 4:
            details["distance_method"] += f", +{len(methods) - 4} more"
    if refs:
        details["distance_reference"] = refs[0]
    return details


def _derive_fast_distance_from_basic(info: Dict[str, Any]) -> Dict[str, Any]:
    """Derive distance only from fields already returned by SIMBAD/Sesame.

    Keep this conservative: nearby galaxies should go through the original
    redshift-independent NED ladder before falling back to a rough Hubble-flow
    estimate.  The old FZASTRO script used z >= 0.005 as the first Hubble-law
    threshold for galaxies.
    """
    object_type = str(info.get("object_type") or "").strip().lower()
    parallax_mas = _float_or_none(info.get("parallax_mas"))
    if (
        parallax_mas is not None
        and parallax_mas > 0
        and not _is_extragalactic_distance_type(object_type)
    ):
        return {"distance_pc": 1000.0 / parallax_mas, "distance_method": "parallax"}

    redshift = _float_or_none(info.get("redshift"))
    radial_velocity = _float_or_none(info.get("radial_velocity_kms"))
    is_quasar_like = object_type in {"quasar", "qso", "agn"}
    is_galaxy = object_type == "galaxy"
    if is_quasar_like or is_galaxy:
        h0 = 70.0
        c_kms = 299_792.458
        if (
            redshift is not None
            and redshift > 0
            and (is_quasar_like or redshift >= 0.005)
        ):
            return {
                "distance_pc": (c_kms * redshift / h0) * 1.0e6,
                "distance_method": "hubble(z)",
            }
        if radial_velocity is not None and radial_velocity > 0 and is_quasar_like:
            return {
                "distance_pc": (radial_velocity / h0) * 1.0e6,
                "distance_method": "hubble(rv)",
            }
    return {}


def _should_replace_fast_distance_with_ladder(info: Dict[str, Any]) -> bool:
    """Return True when a cached/fast distance is only a rough nearby-galaxy Hubble fallback."""
    if not info or info.get("distance_pc") is None:
        return False
    object_type = str(info.get("object_type") or "").strip().casefold()
    method = str(info.get("distance_method") or "").strip().casefold()
    if object_type != "galaxy" or not method.startswith("hubble("):
        return False
    redshift = _float_or_none(info.get("redshift"))
    # The original ladder used NED-D before Hubble for nearby/no-z galaxies.
    return redshift is None or redshift < 0.005


def _distance_ladder_enabled() -> bool:
    """Whether to run the migrated original cosmic distance ladder.

    Default is enabled because this is what the original FZASTRO lookup did.
    Set FZASTRO_USE_DISTANCE_LADDER=0 to keep lookups strictly Sesame/SIMBAD-fast.
    """
    return str(os.environ.get("FZASTRO_USE_DISTANCE_LADDER", "1")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


_FAST_DISTANCE_LADDER_MODULE: Any = None


def _fast_distance_ladder_module():
    """Load the original FZASTRO script only for its distance helper functions."""
    global _FAST_DISTANCE_LADDER_MODULE
    if _FAST_DISTANCE_LADDER_MODULE is not None:
        return _FAST_DISTANCE_LADDER_MODULE
    if not SCRIPT_FILE.exists():
        raise RuntimeError(f"Original FZASTRO script is missing: {SCRIPT_FILE}")

    # Keep the helper import in desktop-fast mode.  We call the NED helpers
    # directly below, so we do not need script.fetch_aliases() to redo the full
    # old lookup.  This preserves the shorter NED/SIMBAD timeouts from the
    # migrated script while restoring the distance ladder order.
    old_fast = os.environ.get("FZASTRO_FAST_LOOKUP")
    old_gaia = os.environ.get("FZASTRO_ENABLE_GAIA")
    os.environ["FZASTRO_FAST_LOOKUP"] = "1"
    os.environ.setdefault("FZASTRO_ENABLE_GAIA", "0")
    try:
        _ensure_astropy_runtime_data()
        module = _load_module("fzastro_distance_ladder_helpers", SCRIPT_FILE)
    finally:
        if old_fast is None:
            os.environ.pop("FZASTRO_FAST_LOOKUP", None)
        else:
            os.environ["FZASTRO_FAST_LOOKUP"] = old_fast
        if old_gaia is None:
            os.environ.pop("FZASTRO_ENABLE_GAIA", None)
        else:
            os.environ["FZASTRO_ENABLE_GAIA"] = old_gaia

    _FAST_DISTANCE_LADDER_MODULE = module
    return module


def _distance_ladder_names(
    query: str, info: Dict[str, Any], aliases: Iterable[Any]
) -> List[str]:
    names: List[str] = []
    seen = set()

    def add(value: Any):
        text = re.sub(r"\s+", " ", str(value or "").strip())
        if not text:
            return
        key = text.casefold()
        if key in seen:
            return
        seen.add(key)
        names.append(text)

    add(query)
    add(info.get("display_name"))
    for alias in aliases or []:
        add(alias)
    return names


def _legacy_ned_trimmed_mean_mpc(
    module: Any,
    names_or_aliases: List[str],
    ra_deg: Optional[float],
    dec_deg: Optional[float],
) -> Optional[float]:
    """Original NED-D trimmed mean, using the old helper functions."""
    collected: List[float] = []
    tried = set()
    expanded: List[str] = []
    for name in names_or_aliases:
        try:
            variants = module._name_variants(name)
        except Exception:
            variants = [name]
        for variant in variants:
            if variant not in tried:
                tried.add(variant)
                expanded.append(variant)

    for name in expanded + [""]:
        try:
            table = module._ned_try_by_name_then_pos_cached(
                name, ra_deg, dec_deg, 120.0
            )
            if table is not None and len(table) > 0:
                collected.extend(
                    module._ned_extract_redshift_independent_values_mpc(table)
                )
        except Exception:
            pass

    values = sorted(
        float(x) for x in collected if x and math.isfinite(float(x)) and float(x) > 0.0
    )
    if not values:
        return None
    n = len(values)
    lo = int(0.10 * n)
    hi = max(lo + 1, int(0.90 * n))
    trimmed = values[lo:hi] if hi > lo else values
    return sum(trimmed) / float(len(trimmed)) if trimmed else None


def _safe_table_float(value: Any) -> Optional[float]:
    """Convert masked/table values from astroquery/astropy to finite float."""
    try:
        import numpy as np  # type: ignore

        if isinstance(value, np.ma.MaskedArray) and np.ma.is_masked(value):
            return None
        if hasattr(value, "mask") and getattr(value, "mask", False) is True:
            return None
    except Exception:
        pass
    try:
        result = float(value)
    except Exception:
        return None
    return result if math.isfinite(result) else None


def _gaia_query_cone(
    module: Any,
    ra_deg: Optional[float],
    dec_deg: Optional[float],
    radius_arcsec: float,
    columns: str,
    where: str = "",
):
    """Run a small Gaia cone query using the old script module's Gaia object."""
    if ra_deg is None or dec_deg is None:
        return None
    radius_deg = float(radius_arcsec) / 3600.0
    where_sql = f"WHERE {where}" if str(where or "").strip() else ""
    adql = f"""
        SELECT {columns}
        FROM {getattr(module, 'GAIA_TABLE', 'gaiadr3.gaia_source')}
        {where_sql}
        AND 1=CONTAINS(POINT('ICRS', ra, dec),
                       CIRCLE('ICRS', {ra_deg}, {dec_deg}, {radius_deg}))
    """.replace(
        "WHERE AND", "WHERE"
    )
    try:
        job = module.Gaia.launch_job_async(adql, dump_to_file=False)
        return job.get_results()
    except Exception as exc:
        log_debug("astro_tools.fast_lookup Gaia cone query skipped", exc)
        return None


def _legacy_gaia_proxy_distance_pc(
    module: Any, ra_deg: Optional[float], dec_deg: Optional[float]
) -> Dict[str, Any]:
    """Original non-galaxy Gaia proxy fallback used by legacy script.py.

    This is intentionally a proxy/association estimate, not a direct target
    parallax.  It is suitable as a best-effort fallback for nebulae/clusters
    when no catalog distance is available, and the method label makes that
    uncertainty visible to the user.
    """
    if ra_deg is None or dec_deg is None:
        return {}

    # Original proxy 1: brightest nearby blue/hot star.
    inner_arcmin = float(getattr(module, "GAIA_PROXY_INNER_ARCMIN", 12.0))
    cols = "source_id, ra, dec, phot_g_mean_mag, bp_rp, parallax, parallax_error"
    where = "(phot_g_mean_mag < 9) AND (bp_rp IS NOT NULL) AND (parallax IS NOT NULL) AND (parallax > 0) AND (bp_rp < 0.6)"
    table = _gaia_query_cone(module, ra_deg, dec_deg, inner_arcmin * 60.0, cols, where)
    if table is not None and len(table) > 0:
        try:
            table.sort("phot_g_mean_mag")
        except Exception:
            pass
        try:
            row = table[0]
            plx = _safe_table_float(row["parallax"])
            if plx is not None and plx > 0:
                return {
                    "distance_pc": 1000.0 / plx,
                    "distance_method": "Gaia proxy (hot-star parallax)",
                    "gaia_source_id": (
                        str(row["source_id"]) if "source_id" in table.colnames else None
                    ),
                    "gaia_parallax_mas": plx,
                    "gaia_parallax_err_mas": (
                        _safe_table_float(row["parallax_error"])
                        if "parallax_error" in table.colnames
                        else None
                    ),
                    "gaia_G": (
                        _safe_table_float(row["phot_g_mean_mag"])
                        if "phot_g_mean_mag" in table.colnames
                        else None
                    ),
                    "gaia_bp_rp": (
                        _safe_table_float(row["bp_rp"])
                        if "bp_rp" in table.colnames
                        else None
                    ),
                }
        except Exception as exc:
            log_debug("astro_tools.fast_lookup Gaia hot-star proxy parse skipped", exc)

    # Original proxy 2: median parallax of bright stars near the target.
    median_arcmin = float(getattr(module, "GAIA_PROXY_MEDIAN_ARCMIN", 8.0))
    cols = "parallax"
    where = "(phot_g_mean_mag BETWEEN 6 AND 13) AND (parallax IS NOT NULL) AND (parallax > 0)"
    table = _gaia_query_cone(module, ra_deg, dec_deg, median_arcmin * 60.0, cols, where)
    if table is not None and len(table) > 0:
        try:
            values = [_safe_table_float(x) for x in table["parallax"]]
            values = sorted(x for x in values if x is not None and x > 0)
            if values:
                n = len(values)
                med = (
                    values[n // 2]
                    if n % 2
                    else 0.5 * (values[n // 2 - 1] + values[n // 2])
                )
                return {
                    "distance_pc": 1000.0 / med,
                    "distance_method": "Gaia proxy (median bright-star parallax)",
                    "gaia_median_parallax_mas": med,
                    "gaia_proxy_star_count": n,
                    "gaia_proxy_radius_arcmin": median_arcmin,
                }
        except Exception as exc:
            log_debug("astro_tools.fast_lookup Gaia median proxy parse skipped", exc)

    return {}


def _legacy_star_gaia_distance_pc(
    module: Any, ra_deg: Optional[float], dec_deg: Optional[float]
) -> Dict[str, Any]:
    """Gaia fallback for stars when SIMBAD/Sesame parallax is missing.

    This preserves the spirit of the original script's Gaia fallback, but uses a
    tighter nearest-source match for objects classified as stars before falling
    back to the broader proxy methods.
    """
    if ra_deg is None or dec_deg is None:
        return {}

    # A real star target should have a close Gaia source. Try this before the
    # broader association/proxy estimates used by the original script.
    cols = "source_id, ra, dec, phot_g_mean_mag, bp_rp, parallax, parallax_error"
    where = "(parallax IS NOT NULL) AND (parallax > 0)"
    table = _gaia_query_cone(module, ra_deg, dec_deg, 5.0, cols, where)
    if table is not None and len(table) > 0:
        try:
            # Sort by angular distance from the fast-resolved coordinates.
            rows = []
            for row in table:
                row_ra = _safe_table_float(row["ra"])
                row_dec = _safe_table_float(row["dec"])
                plx = _safe_table_float(row["parallax"])
                if row_ra is None or row_dec is None or plx is None or plx <= 0:
                    continue
                sep2 = (float(row_ra) - float(ra_deg)) ** 2 + (
                    float(row_dec) - float(dec_deg)
                ) ** 2
                rows.append((sep2, row))
            if rows:
                rows.sort(key=lambda item: item[0])
                row = rows[0][1]
                plx = _safe_table_float(row["parallax"])
                if plx is not None and plx > 0:
                    return {
                        "distance_pc": 1000.0 / plx,
                        "distance_method": "Gaia DR3 parallax",
                        "gaia_source_id": (
                            str(row["source_id"])
                            if "source_id" in table.colnames
                            else None
                        ),
                        "gaia_parallax_mas": plx,
                        "gaia_parallax_err_mas": (
                            _safe_table_float(row["parallax_error"])
                            if "parallax_error" in table.colnames
                            else None
                        ),
                        "gaia_G": (
                            _safe_table_float(row["phot_g_mean_mag"])
                            if "phot_g_mean_mag" in table.colnames
                            else None
                        ),
                        "gaia_bp_rp": (
                            _safe_table_float(row["bp_rp"])
                            if "bp_rp" in table.colnames
                            else None
                        ),
                    }
        except Exception as exc:
            log_debug("astro_tools.fast_lookup Gaia nearest-star parse skipped", exc)

    # Original proxy 1: brightest nearby blue/hot star.
    inner_arcmin = float(getattr(module, "GAIA_PROXY_INNER_ARCMIN", 12.0))
    cols = "source_id, ra, dec, phot_g_mean_mag, bp_rp, parallax, parallax_error"
    where = "(phot_g_mean_mag < 9) AND (bp_rp IS NOT NULL) AND (parallax IS NOT NULL) AND (parallax > 0) AND (bp_rp < 0.6)"
    table = _gaia_query_cone(module, ra_deg, dec_deg, inner_arcmin * 60.0, cols, where)
    if table is not None and len(table) > 0:
        try:
            table.sort("phot_g_mean_mag")
        except Exception:
            pass
        try:
            row = table[0]
            plx = _safe_table_float(row["parallax"])
            if plx is not None and plx > 0:
                return {
                    "distance_pc": 1000.0 / plx,
                    "distance_method": "Gaia proxy (hot-star parallax)",
                    "gaia_source_id": (
                        str(row["source_id"]) if "source_id" in table.colnames else None
                    ),
                    "gaia_parallax_mas": plx,
                    "gaia_parallax_err_mas": (
                        _safe_table_float(row["parallax_error"])
                        if "parallax_error" in table.colnames
                        else None
                    ),
                    "gaia_G": (
                        _safe_table_float(row["phot_g_mean_mag"])
                        if "phot_g_mean_mag" in table.colnames
                        else None
                    ),
                    "gaia_bp_rp": (
                        _safe_table_float(row["bp_rp"])
                        if "bp_rp" in table.colnames
                        else None
                    ),
                }
        except Exception as exc:
            log_debug("astro_tools.fast_lookup Gaia hot-star proxy parse skipped", exc)

    # Original proxy 2: median parallax of bright stars near the target.
    median_arcmin = float(getattr(module, "GAIA_PROXY_MEDIAN_ARCMIN", 8.0))
    cols = "parallax"
    where = "(phot_g_mean_mag BETWEEN 6 AND 13) AND (parallax IS NOT NULL) AND (parallax > 0)"
    table = _gaia_query_cone(module, ra_deg, dec_deg, median_arcmin * 60.0, cols, where)
    if table is not None and len(table) > 0:
        try:
            values = [_safe_table_float(x) for x in table["parallax"]]
            values = sorted(x for x in values if x is not None and x > 0)
            if values:
                n = len(values)
                med = (
                    values[n // 2]
                    if n % 2
                    else 0.5 * (values[n // 2 - 1] + values[n // 2])
                )
                return {
                    "distance_pc": 1000.0 / med,
                    "distance_method": "Gaia proxy (median bright-star parallax)",
                    "gaia_median_parallax_mas": med,
                    "gaia_proxy_star_count": n,
                    "gaia_proxy_radius_arcmin": median_arcmin,
                }
        except Exception as exc:
            log_debug("astro_tools.fast_lookup Gaia median proxy parse skipped", exc)

    return {}


def _legacy_distance_ladder_for_fast_info(
    query: str,
    info: Dict[str, Any],
    aliases: Iterable[Any],
) -> Dict[str, Any]:
    """Restore the original FZASTRO cosmic distance ladder for fast lookup.

    This does not run the full legacy script.  It reuses the old distance helpers
    after the fast resolver has already supplied object type, coordinates,
    redshift/radial velocity, and aliases.
    """
    if not _distance_ladder_enabled() or not info:
        return {}
    if info.get(
        "distance_pc"
    ) is not None and not _should_replace_fast_distance_with_ladder(info):
        return {}

    object_type = str(info.get("object_type") or "").strip()
    kind_norm = object_type.casefold()
    is_nebula_or_cluster = _is_nebula_or_cluster_type(object_type)
    names = _distance_ladder_names(query, info, aliases)
    if not names:
        return {}

    # Nebulae and clusters are not galaxies: do not send them to NED/Hubble.
    # The original script did allow a Gaia association-style proxy later, so we
    # preserve that behavior after special literature overrides are checked.

    ra_deg = _float_or_none(info.get("ra_deg"))
    dec_deg = _float_or_none(info.get("dec_deg"))
    redshift = _float_or_none(info.get("redshift"))
    radial_velocity = _float_or_none(info.get("radial_velocity_kms"))
    parallax_mas = _float_or_none(info.get("parallax_mas"))

    try:
        module = _fast_distance_ladder_module()
    except Exception as exc:
        log_debug("astro_tools.fast_lookup distance ladder helpers unavailable", exc)
        return {}

    # 1) Original special literature overrides: LMC / SMC / Sgr A*.
    try:
        sgr_pc, sgr_label = module._sgrA_override(names)
        if sgr_pc is not None:
            return {"distance_pc": float(sgr_pc), "distance_method": str(sgr_label)}
    except Exception:
        pass

    try:
        mc_pc, mc_label = module._magellanic_override(ra_deg, dec_deg, names)
        if mc_pc is not None:
            return {"distance_pc": float(mc_pc), "distance_method": str(mc_label)}
    except Exception:
        pass

    try:
        lit_pc = module._literature_distance_pc(
            str(info.get("display_name") or query), names
        )
        if lit_pc is not None:
            return {
                "distance_pc": float(lit_pc),
                "distance_method": "literature override",
            }
    except Exception:
        pass

    # Nebulae/clusters: preserve the original script behavior. They must not use
    # galaxy NED/Hubble distances. If SIMBAD already exposes a positive catalog
    # parallax for a local cluster/nebula association, use it directly; otherwise
    # fall back to the original Gaia proxy distance.
    if is_nebula_or_cluster:
        if parallax_mas is not None and parallax_mas > 0:
            return {"distance_pc": 1000.0 / parallax_mas, "distance_method": "parallax"}
        try:
            return _legacy_gaia_proxy_distance_pc(module, ra_deg, dec_deg)
        except Exception as exc:
            log_debug("astro_tools.fast_lookup Gaia nebula/cluster proxy skipped", exc)
            return {}

    # 2) Direct parallax for stars and other non-extragalactic local objects.
    if (
        parallax_mas is not None
        and parallax_mas > 0
        and not _is_extragalactic_distance_type(object_type)
    ):
        return {"distance_pc": 1000.0 / parallax_mas, "distance_method": "parallax"}

    # 2b) Stars with no SIMBAD/Sesame parallax still deserve the old Gaia treatment.
    # Try a tight Gaia DR3 source match first, then fall back to the original proxy methods.
    if kind_norm == "star":
        try:
            gaia_distance = _legacy_star_gaia_distance_pc(module, ra_deg, dec_deg)
        except Exception as exc:
            log_debug("astro_tools.fast_lookup Gaia stellar distance skipped", exc)
            gaia_distance = {}
        if gaia_distance.get("distance_pc") is not None:
            return gaia_distance

    # 3) Hubble-law first only for decent-redshift extragalactic objects.
    is_extragalactic = _is_extragalactic_distance_type(object_type)
    h0 = 70.0
    c_kms = 299_792.458
    if is_extragalactic and redshift is not None and redshift >= 0.005:
        return {
            "distance_pc": (c_kms * redshift / h0) * 1.0e6,
            "distance_method": "hubble(z)",
        }

    # 4) NED redshift-independent ladder for nearby galaxies.
    if kind_norm == "galaxy" and (redshift is None or redshift < 0.005):
        for label, getter in (
            (
                "NED-D (mean)",
                lambda: _legacy_ned_trimmed_mean_mpc(module, names, ra_deg, dec_deg),
            ),
            (
                "NED-D (median)",
                lambda: module.ned_redshift_independent_distance_mpc(
                    names, ra_deg, dec_deg
                ),
            ),
            ("NED-D (mean)", lambda: module._ned_fetch_mean_distance_via_html(names)),
            ("NED-D (median)", lambda: module._ned_ndistance_median_mpc(names)),
        ):
            try:
                mpc = getter()
            except Exception as exc:
                log_debug(
                    "astro_tools.fast_lookup NED ladder step skipped", f"{label}: {exc}"
                )
                mpc = None
            if mpc is not None:
                try:
                    mpc_value = float(mpc)
                    if math.isfinite(mpc_value) and mpc_value > 0:
                        return {
                            "distance_pc": mpc_value * 1.0e6,
                            "distance_method": label,
                        }
                except Exception:
                    pass

    # 5) Final Hubble fallback if the ladder had no redshift-independent result.
    if is_extragalactic:
        if redshift is not None and redshift > 0:
            return {
                "distance_pc": (c_kms * redshift / h0) * 1.0e6,
                "distance_method": "hubble(z)",
            }
        if radial_velocity is not None and radial_velocity > 0:
            return {
                "distance_pc": (radial_velocity / h0) * 1.0e6,
                "distance_method": "hubble(rv)",
            }

    return {}


def _enrich_fast_distance(
    info: Dict[str, Any],
    timeout: int = 5,
    *,
    query: str = "",
    aliases: Optional[Iterable[Any]] = None,
) -> Dict[str, Any]:
    """Return best-effort distance fields without making coordinate lookup fragile.

    Order:
    1. Keep an existing distance.
    2. Try SIMBAD mesDistance by oid through direct TAP.
    3. Use the original FZASTRO cosmic distance ladder for missing distances.
    4. Fall back to conservative direct parallax / Hubble estimates.
    """
    if not info:
        return {}
    if info.get(
        "distance_pc"
    ) is not None and not _should_replace_fast_distance_with_ladder(info):
        return {}

    oid = str(info.get("oid") or "").strip()
    if oid.isdigit():
        try:
            distance = _simbad_distance_for_oid_via_tap(
                oid, timeout=max(3, min(int(timeout), 5))
            )
            if distance.get("distance_pc") is not None:
                return distance
        except Exception as exc:
            log_debug("astro_tools.fast_lookup SIMBAD mesDistance skipped", exc)

    try:
        ladder = _legacy_distance_ladder_for_fast_info(query, info, aliases or [])
        if ladder.get("distance_pc") is not None:
            return ladder
    except Exception as exc:
        log_debug("astro_tools.fast_lookup distance ladder skipped", exc)

    return _derive_fast_distance_from_basic(info)


def _simbad_fast_lookup_via_tap(
    query: str, timeout: int = 18
) -> Tuple[Dict[str, Any], List[str]]:
    """Lookup object basics through direct SIMBAD TAP HTTP.

    This avoids astroquery's local package-data loaders. That matters for the
    frozen EXE because missing astroquery/astropy data files were causing
    Astropy to try obsolete astropy.org data URLs before the real SIMBAD lookup.
    """
    candidates = _simbad_identifier_candidates(query)
    if not candidates:
        raise RuntimeError("No object name supplied.")

    in_list = ", ".join(_adql_string(value) for value in candidates)
    adql = f"""
SELECT TOP 1
    basic.oid,
    basic.main_id,
    basic.otype,
    basic.ra,
    basic.dec,
    basic.pmra,
    basic.pmdec,
    basic.plx_value,
    basic.rvz_redshift,
    basic.rvz_radvel
FROM basic
JOIN ident ON oidref = oid
WHERE ident.id IN ({in_list})
   OR basic.main_id IN ({in_list})
""".strip()

    rows = _simbad_tap_csv(adql, timeout)
    if not rows:
        raise RuntimeError("No SIMBAD result returned.")

    row = rows[0]
    info: Dict[str, Any] = {
        "display_name": str(_row_value_any(row, "main_id") or query).strip(),
        "object_type": _friendly_type(_row_value_any(row, "otype")),
        "ra_deg": _float_or_none(_row_value_any(row, "ra", "RA")),
        "dec_deg": _float_or_none(_row_value_any(row, "dec", "DEC")),
        "pmra_masyr": _float_or_none(_row_value_any(row, "pmra", "PMRA")),
        "pmdec_masyr": _float_or_none(_row_value_any(row, "pmdec", "PMDEC")),
        "parallax_mas": _float_or_none(_row_value_any(row, "plx_value", "parallax")),
        "redshift": _float_or_none(
            _row_value_any(row, "rvz_redshift", "z_value", "redshift")
        ),
        "radial_velocity_kms": _float_or_none(
            _row_value_any(row, "rvz_radvel", "radvel", "radial_velocity")
        ),
    }

    aliases: List[str] = []
    oid = str(_row_value_any(row, "oid") or "").strip()
    if oid:
        info["oid"] = oid
        try:
            aliases = _fetch_simbad_aliases_for_oid(oid, timeout=timeout)
            info["_simbad_aliases_complete"] = True
        except Exception as exc:
            log_debug("astro_tools.fast_lookup aliases skipped", exc)

    info.update(
        _enrich_fast_distance(
            info, timeout=min(int(timeout), 5), query=query, aliases=aliases
        )
    )

    return info, aliases


def _lookup_pretty_type(value: object) -> str:
    """Human-friendly display label for compact SIMBAD object type codes."""
    raw = str(value or "").strip()
    if not raw:
        return "Object"
    compact = raw.upper().replace(" ", "")
    aliases = {
        "*": "Star",
        "STAR": "Star",
        "G": "Galaxy",
        "GALAXY": "Galaxy",
        "EMG": "Emission-line Galaxy",
        "IRG": "Infrared Galaxy",
        "RADIOG": "Radio Galaxy",
        "OPC": "Open Cluster",
        "OC": "Open Cluster",
        "GC": "Globular Cluster",
        "GLC": "Globular Cluster",
        "CL*": "Cluster",
        "CLUSTER": "Cluster",
        "PN": "Planetary Nebula",
        "PLANETARY": "Planetary Nebula",
        "HII": "HII Region",
        "SNR": "Supernova Remnant",
        "RNE": "Reflection Nebula",
        "EMN": "Emission Nebula",
        "DNE": "Dark Nebula",
        "BNE": "Bright Nebula",
        "NEB": "Nebula",
        "AGN": "AGN",
        "QSO": "Quasar",
        "BLLAC": "BL Lac Object",
        "GALAXYCLUS": "Galaxy Cluster",
        "GALAXYCLUSTER": "Galaxy Cluster",
    }
    return aliases.get(compact, raw)


def _lookup_fmt_float(value: object, digits: int = 3, signed: bool = False) -> str:
    if value is None:
        return ""
    try:
        fmt = f"{{:{'+' if signed else ''}.{digits}f}}"
        return fmt.format(float(value))
    except Exception:
        return str(value)


def _lookup_ra_hms(ra_deg: object) -> str:
    """Format ICRS right ascension as hours/minutes/seconds for observers."""
    try:
        ra = float(ra_deg) % 360.0
        total_seconds = ra / 15.0 * 3600.0
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds - hours * 3600) // 60)
        seconds = total_seconds - hours * 3600 - minutes * 60
        if seconds >= 59.995:
            seconds = 0.0
            minutes += 1
        if minutes >= 60:
            minutes = 0
            hours = (hours + 1) % 24
        return f"{hours:02d}h {minutes:02d}m {seconds:05.2f}s"
    except Exception:
        return ""


def _lookup_dec_dms(dec_deg: object) -> str:
    """Format ICRS declination as signed degrees/minutes/seconds."""
    try:
        dec = float(dec_deg)
        sign = "+" if dec >= 0 else "-"
        total_seconds = abs(dec) * 3600.0
        degrees = int(total_seconds // 3600)
        minutes = int((total_seconds - degrees * 3600) // 60)
        seconds = total_seconds - degrees * 3600 - minutes * 60
        if seconds >= 59.995:
            seconds = 0.0
            minutes += 1
        if minutes >= 60:
            minutes = 0
            degrees += 1
        return f"{sign}{degrees:02d}° {minutes:02d}' {seconds:05.2f}\""
    except Exception:
        return ""


def _lookup_galactic_coords(
    ra_deg: object, dec_deg: object
) -> Tuple[Optional[float], Optional[float]]:
    """Return galactic longitude/latitude when Astropy is available.

    The lookup UI must remain usable in stripped-down/frozen environments, so this
    helper is intentionally optional and never raises if coordinate transforms are
    unavailable.
    """
    try:
        from astropy import units as u  # type: ignore
        from astropy.coordinates import SkyCoord  # type: ignore

        coord = SkyCoord(float(ra_deg) * u.deg, float(dec_deg) * u.deg, frame="icrs")
        return float(coord.galactic.l.deg), float(coord.galactic.b.deg)
    except Exception as exc:
        log_debug("astro_tools.fast_lookup galactic coordinate transform skipped", exc)
        return None, None


def _lookup_distance_modulus(distance_pc: object) -> str:
    try:
        pc = float(distance_pc)
    except Exception:
        return ""
    if not math.isfinite(pc) or pc <= 0:
        return ""
    return f"{(5.0 * math.log10(pc) - 5.0):.2f} mag"


def _lookup_absolute_magnitude(apparent_mag: object, distance_pc: object) -> str:
    try:
        apparent = float(apparent_mag)
        pc = float(distance_pc)
    except Exception:
        return ""
    if not math.isfinite(apparent) or not math.isfinite(pc) or pc <= 0:
        return ""
    return f"{(apparent - (5.0 * math.log10(pc) - 5.0)):.2f} mag"


def _lookup_color_index(blue_mag: object, visual_mag: object) -> str:
    try:
        blue = float(blue_mag)
        visual = float(visual_mag)
    except Exception:
        return ""
    if not math.isfinite(blue) or not math.isfinite(visual):
        return ""
    return f"{(blue - visual):+.3f} mag"


def _lookup_distance_summary(distance_pc: object) -> str:
    if distance_pc is None:
        return ""
    try:
        pc = float(distance_pc)
    except Exception:
        return ""
    if not math.isfinite(pc) or pc <= 0:
        return ""
    ly = pc * 3.261563777
    if pc >= 1_000_000:
        pc_part = f"{pc / 1_000_000:.3g} Mpc"
    elif pc >= 1_000:
        pc_part = f"{pc / 1_000:.3g} kpc"
    else:
        pc_part = f"{pc:.3g} pc"
    if ly >= 1_000_000:
        ly_part = f"{ly / 1_000_000:.3g} Mly"
    elif ly >= 1_000:
        ly_part = f"{ly / 1_000:.3g} kly"
    else:
        ly_part = f"{ly:.3g} ly"
    return f"{pc_part} ({ly_part})"


def _lookup_inline_items(items: List[Tuple[str, object]]) -> str:
    """Render compact label/value pairs that wrap cleanly in Qt rich text."""
    clean: List[str] = []
    for label, value in items:
        if value is None or str(value).strip() == "":
            continue
        safe_label = html_escape(str(label or "").rstrip(":"))
        safe_value = html_escape(str(value))
        clean.append(
            '<span style="white-space:nowrap;margin-right:12px;display:inline-block;">'
            f'<span style="color:#9fb2c8;font-size:11px;font-weight:850;">{safe_label}:</span> '
            f'<span style="color:#f3f7fc;font-size:11px;font-weight:650;">{safe_value}</span>'
            "</span>"
        )
    if not clean:
        return ""
    return (
        '<div style="color:#d8e3ef;font-size:11px;line-height:1.35;">'
        + " &nbsp; ".join(clean)
        + "</div>"
    )


def _lookup_panel(title: str, inner_html: str) -> str:
    if not inner_html:
        return ""
    safe_title = html_escape(str(title), quote=True)
    return (
        f'<section class="lookup-panel" data-lookup-title="{safe_title}" '
        'style="margin:5px 0 0 0;padding:5px 0 0 0;border-top:1px solid #202a34;color:#e9eef5;">'
        f'<div class="lookup-panel-title" style="color:#eaf3ff;font-size:12px;font-weight:900;margin:0 0 4px 0;letter-spacing:.01em;">{html_escape(str(title))}</div>'
        f"{inner_html}"
        "</section>"
    )


def _lookup_imaging_setup_html(imaging_lines: List[str]) -> str:
    if not imaging_lines:
        return ""
    safe_line = "&nbsp;&nbsp;·&nbsp;&nbsp;".join(
        html_escape(str(line)) for line in imaging_lines if str(line).strip()
    )
    if not safe_line:
        return ""
    return _lookup_panel(
        "Imaging setup",
        f'<div style="color:#d9e2ee;font-size:11px;line-height:1.35;">{safe_line}</div>',
    )


def _lookup_link_row(label: str, url: str, note: str = "") -> str:
    clean_url = str(url or "").strip()
    if not clean_url:
        return ""
    note_html = (
        f'<span style="color:#8f9fb0;font-size:10px;"> — {html_escape(str(note))}</span>'
        if str(note or "").strip()
        else ""
    )
    return (
        '<div style="margin:2px 0;line-height:1.35;">'
        f'<a href="{html_escape(clean_url, quote=True)}" style="color:#8fc7ff;font-size:11px;font-weight:800;text-decoration:none;">'
        f"{html_escape(str(label))}</a>{note_html}"
        "</div>"
    )


def _lookup_external_links_html(
    clean_query: str, info: Dict[str, Any], aliases: List[str]
) -> str:
    """Build source links for the Links tab without fetching extra science data."""
    display_name = str(info.get("display_name") or clean_query or "").strip()
    primary_name = display_name or str(clean_query or "").strip()
    if not primary_name:
        return ""
    encoded_name = quote_plus(primary_name)
    rows: List[str] = []

    rows.append(
        _lookup_link_row(
            "SIMBAD object page",
            "https://simbad.cds.unistra.fr/simbad/sim-id?Ident=" + encoded_name,
            "identity, identifiers, bibliography, measurements",
        )
    )
    oid = str(info.get("oid") or "").strip().lstrip("@")
    if oid.isdigit():
        rows.append(
            _lookup_link_row(
                "SIMBAD TAP basic row by OID",
                "https://simbad.cds.unistra.fr/simbad/sim-tap/sync?REQUEST=doQuery&LANG=ADQL&FORMAT=HTML&QUERY="
                + quote_plus(f"SELECT TOP 1 * FROM basic WHERE oid = {oid}"),
                "raw SIMBAD basic table row",
            )
        )
    rows.append(
        _lookup_link_row(
            "CDS Sesame resolver",
            "https://cds.unistra.fr/cgi-bin/Sesame/-oxp/~?" + encoded_name,
            "name resolution and aliases",
        )
    )
    rows.append(
        _lookup_link_row(
            "VizieR catalog search",
            "https://vizier.cds.unistra.fr/viz-bin/VizieR?-source=all&-out.max=50&-out.form=HTML%20Table&-c="
            + encoded_name,
            "catalog/survey rows near the object",
        )
    )

    ra = _float_or_none(info.get("ra_deg"))
    dec = _float_or_none(info.get("dec_deg"))
    if ra is not None and dec is not None:
        coord = f"{ra:.7f} {dec:+.7f}"
        rows.append(
            _lookup_link_row(
                "Aladin Lite sky atlas",
                "https://aladin.cds.unistra.fr/AladinLite/?target="
                + quote(coord)
                + "&fov=0.5",
                "interactive sky image and survey overlays",
            )
        )
        rows.append(
            _lookup_link_row(
                "VizieR cone search at coordinates",
                "https://vizier.cds.unistra.fr/viz-bin/VizieR?-source=all&-out.max=50&-out.form=HTML%20Table&-c="
                + quote(coord)
                + "&-c.rs=5",
                "5 arcmin catalog cone",
            )
        )

    object_type = str(info.get("object_type") or "").casefold()
    if (
        _is_extragalactic_distance_type(str(info.get("object_type") or ""))
        or "galaxy" in object_type
    ):
        rows.append(
            _lookup_link_row(
                "NASA/IPAC NED by name",
                "https://ned.ipac.caltech.edu/byname?objname=" + encoded_name,
                "galaxy redshifts, distances, photometry, references",
            )
        )

    if _is_fzastro_horizons_target(primary_name) or _solar_system_reference_kind(
        primary_name, object_type
    ):
        rows.append(
            _lookup_link_row(
                "JPL Horizons",
                "https://ssd.jpl.nasa.gov/horizons/app.html#/",
                "live ephemerides for Solar System bodies",
            )
        )
        rows.append(
            _lookup_link_row(
                "NASA Images search",
                "https://images.nasa.gov/search-results?q=" + encoded_name,
                "real public-domain mission imagery",
            )
        )

    rows.append(
        _lookup_link_row(
            "Wikimedia Commons image search",
            "https://commons.wikimedia.org/w/index.php?search="
            + encoded_name
            + "&title=Special:MediaSearch&type=image",
            "reference imagery and diagrams",
        )
    )

    clean_rows = [row for row in rows if row]
    if not clean_rows:
        return ""
    alias_hint = ""
    clean_aliases = _clean_aliases(aliases or [])
    if clean_aliases:
        alias_hint = (
            '<div style="margin:0 0 5px 0;color:#93a3b3;font-size:10px;line-height:1.3;">'
            + html_escape(
                f"Search name: {primary_name} · aliases available: {len(clean_aliases)}"
            )
            + "</div>"
        )
    return alias_hint + "".join(clean_rows)


def _lookup_method_parts(method: object) -> Tuple[str, str]:
    """Split long method labels into source + method-list for a cleaner card."""
    text = str(method or "").strip()
    if not text:
        return "", ""
    m = re.search(r";\s*methods\s*:\s*", text, flags=re.IGNORECASE)
    if not m:
        return text, ""
    return text[: m.start()].strip(), text[m.end() :].strip()


def _lookup_distance_block(
    distance_pc: object, method: object, reference: object
) -> str:
    distance_text = _lookup_distance_summary(distance_pc)
    if not distance_text:
        return '<div style="color:#ffcc7a;font-size:11px;line-height:1.35;">Distance not available from fast lookup / distance ladder.</div>'

    source_method, method_list = _lookup_method_parts(method)
    rows = [
        '<div style="font-size:12px;line-height:1.25;color:#ffffff;font-weight:850;margin:0 0 4px 0;">'
        + html_escape(distance_text)
        + "</div>"
    ]
    detail_lines: List[str] = []
    if source_method:
        detail_lines.append(
            '<div style="margin:1px 0;line-height:1.28;">'
            '<span style="color:#9fb2c8;font-size:11px;font-weight:850;">Method:</span> '
            f'<span style="color:#f3f7fc;font-size:11px;font-weight:650;">{html_escape(source_method)}</span>'
            "</div>"
        )
    if method_list:
        detail_lines.append(
            '<div style="margin:1px 0;line-height:1.28;">'
            '<span style="color:#9fb2c8;font-size:11px;font-weight:850;">Indicators:</span> '
            f'<span style="color:#f3f7fc;font-size:11px;font-weight:650;">{html_escape(method_list)}</span>'
            "</div>"
        )
    if reference:
        detail_lines.append(
            '<div style="margin:1px 0;line-height:1.28;">'
            '<span style="color:#9fb2c8;font-size:11px;font-weight:850;">Reference:</span> '
            f'<span style="color:#f3f7fc;font-size:11px;font-weight:650;">{html_escape(str(reference))}</span>'
            "</div>"
        )
    if detail_lines:
        rows.append(
            '<div style="font-size:11px;color:#d8e3ef;">'
            + "".join(detail_lines)
            + "</div>"
        )
    return "".join(rows)

    source_method, method_list = _lookup_method_parts(method)
    rows = [
        '<div style="font-size:17px;line-height:1.35;color:#ffffff;font-weight:850;margin-bottom:4px;">'
        + html_escape(distance_text)
        + "</div>"
    ]
    detail_items: List[Tuple[str, object]] = []
    if source_method:
        detail_items.append(("Method:", source_method))
    if method_list:
        detail_items.append(("Methods:", method_list))
    if reference:
        detail_items.append(("Reference:", reference))
    if detail_items:
        rows.append(_lookup_inline_items(detail_items))
    return "".join(rows)


def _lookup_alias_line(aliases: List[str], max_visible: Optional[int] = None) -> str:
    """Render aliases in a Qt-safe way.

    QTextDocument does not reliably honor inline-block/margin CSS inside QLabel
    rich text, so chip spans can visually collapse into one long word.  Use
    explicit text separators instead; this renders consistently in the chat UI.

    By default this renders every alias. Pass a positive max_visible only for
    intentional previews; LOOKUP result cards should not hide SIMBAD aliases.
    """
    clean = _clean_aliases(aliases or [])
    if not clean:
        return ""
    limit = int(max_visible or 0)
    shown = clean[:limit] if limit > 0 else clean
    alias_bits = [
        '<span style="color:#dce7f4;font-size:11px;white-space:nowrap;">'
        + html_escape(str(a))
        + "</span>"
        for a in shown
        if str(a).strip()
    ]
    if limit > 0 and len(clean) > limit:
        alias_bits.append(
            '<span style="color:#9fc7ff;font-size:11px;font-weight:850;white-space:nowrap;">'
            + html_escape(f"+{len(clean) - limit} more")
            + "</span>"
        )
    sep = '<span style="color:#5f7489;font-size:11px;">&nbsp;·&nbsp;</span>'
    return (
        '<div style="font-size:11px;line-height:1.35;color:#dce7f4;">'
        + sep.join(alias_bits)
        + "</div>"
    )


def _lookup_field_label(raw: object) -> str:
    """Convert TAP column names into compact labels for the LOOKUP card."""
    text = str(raw or "").strip()
    if not text:
        return "Field"
    base = text.rsplit(".", 1)[-1]
    norm = re.sub(r"[^a-z0-9]+", "", base.casefold())
    known = {
        "oid": "SIMBAD OID",
        "oidref": "SIMBAD OID",
        "mainid": "Main ID",
        "otype": "Object type",
        "ra": "RA deg",
        "dec": "Dec deg",
        "pmra": "PM RA",
        "pmdec": "PM Dec",
        "plxvalue": "Parallax",
        "rvzredshift": "Redshift",
        "rvzradvel": "Radial velocity",
        "sptype": "Spectral type",
        "morphtype": "Morphology",
        "galdimmajaxis": "Major axis",
        "galdimminaxis": "Minor axis",
        "galdimangle": "Position angle",
        "bibcode": "Bibcode",
        "unit": "Unit",
        "method": "Method",
        "qual": "Quality",
        "quality": "Quality",
        "ref": "Reference",
        "id": "Identifier",
    }
    if norm in known:
        return known[norm]
    label = re.sub(r"[_\-]+", " ", base).strip()
    return label[:1].upper() + label[1:] if label else "Field"


def _lookup_generic_fields_html(fields: Dict[str, Any]) -> str:
    """Render all non-empty key/value fields returned by TAP."""
    items: List[Tuple[str, object]] = []
    for key, value in (fields or {}).items():
        clean_value = _lookup_clean_text_value(value)
        if not clean_value:
            continue
        items.append((_lookup_field_label(key), clean_value))
    return _lookup_inline_items(items)


def _lookup_measurement_rows_html(rows: List[Dict[str, Any]]) -> str:
    """Render all fetched SIMBAD measurement rows without hiding columns."""
    rendered: List[str] = []
    for idx, row in enumerate(rows or [], start=1):
        row_html = _lookup_generic_fields_html(row)
        if not row_html:
            continue
        rendered.append(
            '<div style="margin:3px 0 5px 0;padding:3px 0;border-bottom:1px solid #18212b;">'
            f'<div style="color:#9fb2c8;font-size:10px;font-weight:850;margin:0 0 2px 0;">Row {idx}</div>'
            f"{row_html}"
            "</div>"
        )
    return "".join(rendered)


def _lookup_measurement_tables_html(measurements: Dict[str, Dict[str, Any]]) -> str:
    """Render every fetched SIMBAD measurement table as display-only data.

    This function intentionally does not calculate or replace distance fields;
    the existing distance ladder remains the only source of the top distance
    summary.
    """
    blocks: List[str] = []
    for table_name in sorted((measurements or {}).keys()):
        table = measurements.get(table_name) or {}
        rows = table.get("rows") if isinstance(table, dict) else None
        if not isinstance(rows, list) or not rows:
            continue
        label = _lookup_clean_text_value(table.get("label") or table_name)
        row_limit = table.get("row_limit")
        count_text = f"{len(rows)} row(s)"
        if row_limit:
            count_text += f" · capped at {row_limit}"
        blocks.append(
            '<div style="margin:4px 0 7px 0;padding:5px 6px;border:1px solid #1e2a36;border-radius:6px;background:#071019;">'
            f'<div style="color:#dce7f4;font-size:12px;font-weight:900;margin:0 0 2px 0;">{html_escape(label)}</div>'
            f'<div style="color:#8fa0b3;font-size:10px;margin:0 0 4px 0;">{html_escape(str(table_name))} · {html_escape(count_text)}</div>'
            + _lookup_measurement_rows_html(rows)
            + "</div>"
        )
    if not blocks:
        return ""
    note = (
        '<div style="color:#9fb2c8;font-size:10px;line-height:1.35;margin:0 0 5px 0;">'
        "Raw SIMBAD TAP rows are display-only. Distance values shown here do not "
        "replace the FZAstro distance ladder summary above."
        "</div>"
    )
    return note + "".join(blocks)


def _lookup_parse_sectioned_text(output: str) -> Dict[str, List[str]]:
    """Parse original FZASTRO [ SECTION ] text into normalized rows."""
    sections: Dict[str, List[str]] = {}
    current: Optional[str] = None
    for raw_line in str(output or "").splitlines():
        line = str(raw_line or "").strip()
        if not line:
            continue
        match = re.match(r"^\[\s*(.+?)\s*\]$", line)
        if match:
            current = re.sub(r"\s+", " ", match.group(1).strip()).upper()
            sections.setdefault(current, [])
            continue
        if current:
            sections.setdefault(current, []).append(line)
    return sections


def _lookup_items_from_lines(lines: Iterable[str]) -> List[Tuple[str, object]]:
    """Turn legacy section lines into compact label/value pairs."""
    items: List[Tuple[str, object]] = []
    for raw_line in lines:
        line = re.sub(r"\s+", " ", str(raw_line or "").strip())
        if not line:
            continue
        if ":" in line:
            label, value = line.split(":", 1)
            label = label.strip()
            value = value.strip()
            if label and value:
                items.append((label, value))
            elif label:
                items.append((label, "—"))
        elif items:
            label, value = items[-1]
            suffix = line.strip()
            if suffix:
                items[-1] = (label, f"{value} {suffix}".strip())
        else:
            items.append(("", line))
    return items


def _lookup_header_html(display_name: str, object_type: str, source: str) -> str:
    safe_name = html_escape(str(display_name or "Object"))
    safe_type = html_escape(str(object_type or "Object"))
    safe_source = html_escape(str(source or "FZASTRO LOOKUP"))
    return (
        '<div class="lookup-header" style="margin:0 0 5px 0;padding:4px 0 2px 0;color:#e9eef5;">'
        f'<div style="font-size:16px;font-weight:900;color:#ffffff;line-height:1.15;margin:0 0 3px 0;">{safe_name}</div>'
        '<div style="color:#d4deea;font-size:11px;line-height:1.3;">'
        f'<span style="color:#9fb2c8;font-size:11px;font-weight:850;">Type:</span> {safe_type}'
        f'&nbsp;&nbsp;·&nbsp;&nbsp;<span style="color:#9fb2c8;font-size:11px;font-weight:850;">Source:</span> {safe_source}'
        "</div>"
        "</div>"
    )


def _format_legacy_lookup_html(
    clean_query: str, output: str, source: str = "embedded FZASTRO lookup"
) -> str:
    """Render planets, moons, comets, spacecraft, and legacy script output in
    the same compact card format used by fast SIMBAD lookup results.
    """
    sections = _lookup_parse_sectioned_text(output)
    if not sections:
        return ""

    object_items = dict(_lookup_items_from_lines(sections.get("OBJECT", [])))
    display_name = str(
        object_items.get("Main ID")
        or object_items.get("Name")
        or object_items.get("Object")
        or clean_query
        or "Object"
    ).strip()
    object_type = str(object_items.get("Type") or "Object").strip()

    html_parts: List[str] = [_lookup_header_html(display_name, object_type, source)]

    for section_name, title in (
        ("POSITION", "Position"),
        ("DISTANCE", "Distance"),
        ("PHOTOMETRY", "Photometry"),
        ("MORPHOLOGY", "Morphology"),
        ("EPHEMERIS DATA", "Ephemeris data"),
    ):
        inner = _lookup_inline_items(
            _lookup_items_from_lines(sections.get(section_name, []))
        )
        if inner:
            html_parts.append(_lookup_panel(title, inner))

    aliases = [line for line in sections.get("ALIASES", []) if str(line).strip()]
    alias_html = _lookup_alias_line(aliases)
    if alias_html:
        html_parts.append(_lookup_panel("Aliases", alias_html))

    # Preserve any uncommon section produced by future FZASTRO categories with
    # the same compact format instead of falling back to a monospace block.
    known = {
        "OBJECT",
        "POSITION",
        "DISTANCE",
        "PHOTOMETRY",
        "MORPHOLOGY",
        "EPHEMERIS DATA",
        "ALIASES",
    }
    for section_name, lines in sections.items():
        if section_name in known:
            continue
        inner = _lookup_inline_items(_lookup_items_from_lines(lines))
        if inner:
            pretty = section_name.title().replace("/", " / ")
            html_parts.append(_lookup_panel(pretty, inner))

    return "\n".join(part for part in html_parts if part).strip()


def _format_fast_lookup_html(
    clean_query: str, info: Dict[str, Any], aliases: List[str], lookup_source: str
) -> str:
    """Render fast lookup output as compact HTML without changing lookup science.

    Keep the science/data-fetch path stable, but surface the details already
    present in the structured lookup payload so the desktop result panel is more
    useful than a coordinate-only card.
    """
    display_name = str(info.get("display_name") or clean_query or "Object").strip()
    pretty_type = _lookup_pretty_type(info.get("object_type") or "Object")
    source = str(lookup_source or "fast lookup").strip()

    html_parts: List[str] = [_lookup_header_html(display_name, pretty_type, source)]

    ra_deg = float(info["ra_deg"])
    dec_deg = float(info["dec_deg"])
    gal_l, gal_b = _lookup_galactic_coords(ra_deg, dec_deg)
    coord_items: List[Tuple[str, object]] = [
        ("RA deg", f"{ra_deg:.6f}°"),
        ("Dec deg", f"{dec_deg:+.6f}°"),
        ("RA HMS", _lookup_ra_hms(ra_deg)),
        ("Dec DMS", _lookup_dec_dms(dec_deg)),
    ]
    if gal_l is not None and gal_b is not None:
        coord_items.extend(
            [
                ("Galactic l", f"{gal_l:.4f}°"),
                ("Galactic b", f"{gal_b:+.4f}°"),
            ]
        )
    html_parts.append(_lookup_panel("Coordinates", _lookup_inline_items(coord_items)))

    motion_items: List[Tuple[str, object]] = []
    if info.get("parallax_mas") is not None:
        motion_items.append(("Parallax", f"{float(info['parallax_mas']):.3f} mas"))
    pmra = info.get("pmra_masyr")
    pmdec = info.get("pmdec_masyr")
    if pmra is not None or pmdec is not None:
        sra = f"{float(pmra):.2f}" if pmra is not None else "n/a"
        sdc = f"{float(pmdec):.2f}" if pmdec is not None else "n/a"
        motion_items.append(("Proper motion", f"RA {sra}, Dec {sdc} mas/yr"))
    redshift_value = info.get("redshift")
    radial_velocity = info.get("radial_velocity_kms")
    if redshift_value is not None and radial_velocity is None:
        try:
            radial_velocity = float(redshift_value) * 299792.458
        except Exception:
            radial_velocity = None
    if redshift_value is not None:
        motion_items.append(("Redshift", f"{float(redshift_value):.6f}"))
    if radial_velocity is not None:
        motion_items.append(("Radial velocity", f"{float(radial_velocity):.1f} km/s"))
    if motion_items:
        html_parts.append(
            _lookup_panel("Motion / velocity", _lookup_inline_items(motion_items))
        )

    physical_items: List[Tuple[str, object]] = [("Object type", pretty_type)]
    if info.get("morphology"):
        physical_items.append(("Morphology", str(info.get("morphology"))))
    if info.get("distance_pc") is not None:
        distance_modulus = _lookup_distance_modulus(info.get("distance_pc"))
        if distance_modulus:
            physical_items.append(("Distance modulus", distance_modulus))
    if info.get("oid") is not None:
        physical_items.append(("SIMBAD OID", str(info.get("oid"))))
    html_parts.append(
        _lookup_panel("Physical details", _lookup_inline_items(physical_items))
    )

    html_parts.append(
        _lookup_panel(
            "Distance",
            _lookup_distance_block(
                info.get("distance_pc"),
                info.get("distance_method"),
                info.get("distance_reference"),
            ),
        )
    )

    distance_pc = info.get("distance_pc")
    phot_items: List[Tuple[str, object]] = []
    for label, key in (("B", "mag_B"), ("V", "mag_V"), ("G", "mag_G")):
        if info.get(key) is not None:
            phot_items.append((label, f"{float(info[key]):.3f} mag"))
    color_bv = _lookup_color_index(info.get("mag_B"), info.get("mag_V"))
    if color_bv:
        phot_items.append(("Color B-V", color_bv))
    for label, key in (("Abs V", "mag_V"), ("Abs G", "mag_G")):
        absolute_mag = _lookup_absolute_magnitude(info.get(key), distance_pc)
        if absolute_mag:
            phot_items.append((label, absolute_mag))
    if phot_items:
        html_parts.append(_lookup_panel("Photometry", _lookup_inline_items(phot_items)))

    catalog_items: List[Tuple[str, object]] = []
    if info.get("oid") is not None:
        catalog_items.append(("SIMBAD OID", str(info.get("oid"))))
    clean_aliases = _clean_aliases(aliases or [])
    if clean_aliases:
        catalog_items.append(("Alias count", str(len(clean_aliases))))
    if catalog_items:
        html_parts.append(
            _lookup_panel("Catalog IDs", _lookup_inline_items(catalog_items))
        )

    links_html = _lookup_external_links_html(clean_query, info, clean_aliases)
    if links_html:
        html_parts.append(_lookup_panel("Links", links_html))

    alias_html = _lookup_alias_line(clean_aliases)
    if alias_html:
        html_parts.append(_lookup_panel("Aliases", alias_html))

    basic_fields_html = _lookup_generic_fields_html(
        info.get("simbad_basic_fields") or {}
    )
    if basic_fields_html:
        html_parts.append(
            _lookup_panel("SIMBAD basic row · all fields", basic_fields_html)
        )

    measurements_html = _lookup_measurement_tables_html(
        info.get("simbad_measurements") or {}
    )
    if measurements_html:
        html_parts.append(
            _lookup_panel(
                "SIMBAD measurement tables · all fetched rows", measurements_html
            )
        )

    return "\n".join(part for part in html_parts if part).strip()


def _fast_lookup_object_text(
    query: str, timeout: int = 18
) -> Tuple[str, Dict[str, Any]]:
    """Fast desktop object lookup.

    This intentionally avoids the embedded deep lookup path because that path can
    call slow NED/Gaia/IRAS services. For the AI desktop app, ASTRO should return
    object coordinates and an image quickly; deep distance/morphology enrichment
    can be a separate optional tool later.
    """
    _check_cancelled()
    clean_query = str(query or "").strip()
    use_local_fallbacks = os.environ.get("FZASTRO_USE_LOCAL_OBJECT_FALLBACKS") == "1"
    fallback = _catalog_fallback_for_query(clean_query) if use_local_fallbacks else None
    start = time.perf_counter()

    info: Dict[str, Any] = {}
    aliases: List[str] = []
    simbad_error: Optional[str] = None
    lookup_source = "none"

    cached = _load_fast_lookup_cache(clean_query, max_age_days=30)
    if cached:
        info, aliases, lookup_source = cached

    if not info:
        try:
            # First choice: CDS Sesame.  It is designed as a fast name resolver
            # and avoids long TAP joins when the CDS TAP endpoint is busy.
            info, aliases = _simbad_fast_lookup_via_sesame(
                clean_query, timeout=min(int(timeout), 6)
            )
            lookup_source = "CDS Sesame"
            _check_cancelled()
        except Exception as exc:
            simbad_error = str(exc)
            log_warning(
                "astro_tools.fast_lookup Sesame failed",
                f"query={clean_query}; error={exc}",
            )

    if not info:
        try:
            # Fallback only: TAP gives richer fields but can stall, so keep its
            # timeout short and let _simbad_tap_csv try both Strasbourg hosts.
            info, aliases = _simbad_fast_lookup_via_tap(
                clean_query, timeout=min(int(timeout), 6)
            )
            lookup_source = "SIMBAD TAP"
            _check_cancelled()
        except Exception as exc:
            simbad_error = str(exc)
            log_warning(
                "astro_tools.fast_lookup SIMBAD TAP failed",
                f"query={clean_query}; error={exc}",
            )

    if not info:
        stale = _load_fast_lookup_cache(clean_query, allow_stale=True)
        if stale:
            info, aliases, lookup_source = stale
            lookup_source = f"stale {lookup_source}"

    if fallback:
        # Use literature fallback for known common objects when SIMBAD did not
        # return a given field. This avoids slow Gaia/NED calls for nearby
        # galaxies like M82 and M101.
        for key, value in fallback.items():
            if key == "aliases":
                continue
            if info.get(key) in (None, "", "Object"):
                info[key] = value
        aliases = _clean_aliases([*aliases, *fallback.get("aliases", [])])

    if info.get("ra_deg") is None or info.get("dec_deg") is None:
        if fallback:
            info.update(fallback)
            aliases = _clean_aliases(fallback.get("aliases", []))
        else:
            raise RuntimeError(simbad_error or "No fast SIMBAD result returned.")

    if not aliases:
        aliases = _clean_aliases([clean_query, info.get("display_name")])

    # Refresh cached/Sesame results with the same core details the original
    # astroquery path printed: proper motion and the complete SIMBAD alias list.
    # Older caches may already have `_simbad_details_enriched` but only contain
    # the previous preview alias subset, so also check `_simbad_aliases_complete`.
    if (
        not info.get("_simbad_details_enriched")
        or (info.get("oid") is not None and not info.get("_simbad_aliases_complete"))
        or (info.get("oid") is not None and not info.get("_simbad_research_enriched"))
    ):
        info, aliases = _enrich_fast_object_details_via_tap(
            info, aliases, timeout=min(int(timeout), 6)
        )

    if info.get("distance_pc") is None:
        info.update(
            _enrich_fast_distance(
                info, timeout=min(int(timeout), 5), query=clean_query, aliases=aliases
            )
        )

    if lookup_source and not lookup_source.startswith("stale"):
        _store_fast_lookup_cache(clean_query, info, aliases, lookup_source)

    text_output = _format_fast_lookup_html(clean_query, info, aliases, lookup_source)
    metadata = {
        "elapsed": max(0.0, time.perf_counter() - start),
        "ra_deg": float(info["ra_deg"]),
        "dec_deg": float(info["dec_deg"]),
        "object_type": str(info.get("object_type") or ""),
        "display_name": str(info.get("display_name") or clean_query),
        "fast_lookup": True,
        "fzastro_script": False,
        "lookup_source": lookup_source,
    }
    if info.get("oid") is not None:
        metadata["simbad_oid"] = str(info.get("oid"))
    if info.get("pmra_masyr") is not None:
        metadata["pmra_masyr"] = float(info.get("pmra_masyr"))
    if info.get("pmdec_masyr") is not None:
        metadata["pmdec_masyr"] = float(info.get("pmdec_masyr"))
    clean_metadata_aliases = _clean_aliases(aliases or [])
    if clean_metadata_aliases:
        metadata["alias_count"] = len(clean_metadata_aliases)
        metadata["aliases"] = clean_metadata_aliases
    if info.get("distance_pc") is not None:
        metadata["distance_pc"] = float(info.get("distance_pc"))
        metadata["distance_method"] = str(info.get("distance_method") or "")
    if info.get("morphology"):
        metadata["morphology"] = str(info.get("morphology") or "")
    if info.get("redshift") is not None:
        metadata["redshift"] = float(info.get("redshift"))
    if info.get("radial_velocity_kms") is not None:
        metadata["radial_velocity_kms"] = float(info.get("radial_velocity_kms"))
    for band in ("B", "V", "G"):
        key = f"mag_{band}"
        if info.get(key) is not None:
            metadata[key] = float(info.get(key))
    if info.get("simbad_basic_fields"):
        metadata["simbad_basic_fields"] = dict(info.get("simbad_basic_fields") or {})
    if info.get("simbad_measurements"):
        metadata["simbad_measurements"] = dict(info.get("simbad_measurements") or {})
    return text_output.rstrip() + "\n", metadata


def fetch_sky_image(
    ra: float,
    dec: float,
    fov_deg: float = 2.337,
    width: int = 1536,
    height: int = 1024,
    survey: Optional[str] = None,
    rotation_angle: float = 270.0,
) -> AstroToolResult:
    """Fetch a sky survey image using the migrated HIPS2FITS logic."""
    try:
        imagefetch = _imagefetch_module()
        path, _url_path, used = imagefetch.fetch_image(
            ra=float(ra),
            dec=float(dec),
            fov_deg=float(fov_deg),
            w=int(width),
            h=int(height),
            survey=survey,
            rotation_angle=float(rotation_angle),
        )
    except Exception as exc:
        log_exception("astro_tools.fetch_sky_image", exc)
        return AstroToolResult(
            title="Sky image failed",
            text=f"Sky image fetch failed: {exc}",
            success=False,
        )

    if not path or not Path(path).exists():
        log_warning(
            "astro_tools.fetch_sky_image returned no file",
            f"ra={ra}; dec={dec}; fov={fov_deg}; survey={survey}",
        )
        return AstroToolResult(
            title="Sky image unavailable",
            text="No sky image was returned by the HIPS2FITS service for these coordinates.",
            success=False,
        )

    credit = imagefetch.image_credit_for(used)
    text = (
        "**Sky image retrieved.**\n\n"
        f"RA: {float(ra):.6f}°\n\n"
        f"Dec: {float(dec):+.6f}°\n\n"
        f"FOV: {float(fov_deg):.3f}°\n\n"
        f"Survey: {used or survey or 'default'}\n\n"
        f"Credit: {credit}"
    )
    return AstroToolResult(
        title="Sky image",
        text=text,
        files=[str(path)],
        success=True,
        metadata={
            "ra_deg": float(ra),
            "dec_deg": float(dec),
            "fov_deg": float(fov_deg),
            "survey": used,
        },
    )


def lookup_object(
    query: str,
    with_image: bool = True,
    fov_deg: float = 2.337,
    width: int = 1536,
    height: int = 1024,
    rotation_angle: float = 270.0,
    survey: Optional[str] = None,
    camera_name: Optional[str] = None,
    focal_mm: Optional[float] = None,
    fov_y_deg: Optional[float] = None,
) -> AstroToolResult:
    """Fast migrated FZASTRO object lookup and optional sky-image attachment.

    The original web app's script.py performs deep enrichment through several
    remote services. That is good for research mode, but bad for a desktop UI:
    Gaia/NED/IRAS can hang and block normal ASTRO lookups. The Version 1 release-candidate
    path now uses a fast Sesame/SIMBAD resolver, then restores the original
    cosmic distance ladder only when distance is missing. Deep full-script
    lookup remains available only when explicitly enabled with
    FZASTRO_USE_DEEP_LOOKUP=1.
    """
    clean_query = str(query or "").strip()

    if not clean_query:
        return AstroToolResult(
            title="Astro lookup", text="No object name was provided.", success=False
        )

    use_deep_lookup = str(
        os.environ.get("FZASTRO_USE_DEEP_LOOKUP", "0")
    ).strip().lower() in {"1", "true", "yes", "on"}
    force_fzastro_horizons = _is_fzastro_horizons_target(clean_query)
    output = ""
    metadata: Dict[str, Any] = {}
    fast_error: Optional[str] = None

    # Deep-sky/stars/catalog IDs use the fast SIMBAD path.
    # Solar System bodies, moons, comets, and spacecraft must bypass SIMBAD and
    # go directly to the original FZASTRO/Horizons resolver.
    if not use_deep_lookup and not force_fzastro_horizons:
        try:
            output, metadata = _fast_lookup_object_text(clean_query, timeout=18)
        except AstroToolCancelled:
            raise
        except Exception as exc:
            log_warning(
                "astro_tools.lookup_object fast path failed",
                f"query={clean_query}; error={exc}",
            )
            fast_error = str(exc)

    if not output and not use_deep_lookup and not force_fzastro_horizons:
        return AstroToolResult(
            title=f"Astro lookup: {clean_query}",
            text=(
                f"Fast astro lookup failed for `{clean_query}`.\n\n"
                f"Reason: {fast_error or 'No fast SIMBAD result returned.'}\n\n"
                "Deep legacy lookup was not started automatically, to avoid the old "
                "60-second UI timeout path. Set FZASTRO_USE_DEEP_LOOKUP=1 only "
                "when you deliberately want the slow legacy enrichment script."
            ),
            success=False,
            metadata={
                "fast_lookup": True,
                "fzastro_script": False,
                "fast_error": fast_error,
            },
        )

    if use_deep_lookup or force_fzastro_horizons or not output:
        if not SCRIPT_FILE.exists():
            return _script_error(SCRIPT_FILE)
        try:
            return_code, stdout, stderr, elapsed = _run_script(
                SCRIPT_FILE, [clean_query], timeout=60
            )
        except AstroToolCancelled:
            raise
        except Exception as exc:
            log_exception("astro_tools.lookup_object embedded FZASTRO path", exc)
            return AstroToolResult(
                title=f"Astro lookup: {clean_query}",
                text=f"Astro lookup failed: {exc}"
                + (f"\n\nFast path: {fast_error}" if fast_error else ""),
                success=False,
            )

        output = _decode(stdout)
        error_text = _decode(stderr)

        if return_code != 0 or not output or "No result found" in output:
            details = error_text or output or fast_error or "No result found."
            _log_script_failure(
                "lookup_object", return_code, output, error_text, elapsed, [clean_query]
            )
            return AstroToolResult(
                title=f"Astro lookup: {clean_query}",
                text=f"No result found for `{clean_query}`.\n\n{details}".strip(),
                success=False,
                metadata={"elapsed": elapsed, "fzastro_script": True},
            )
        metadata = {
            "elapsed": elapsed,
            "fzastro_script": True,
            "lookup_source": (
                "FZASTRO Horizons"
                if force_fzastro_horizons
                else "embedded FZASTRO lookup"
            ),
        }

    files: List[str] = []
    metadata = dict(metadata or {})

    # Fast lookup now returns an HTML card.  RA/Dec can no longer be parsed
    # reliably from the rendered HTML, so use the structured metadata produced
    # by _fast_lookup_object_text first.  Fall back to parsing only for legacy
    # plain-text script output.  This is what keeps the sky image attached after
    # the lookup layout renderer changed from text to HTML.
    def _metadata_float(key: str) -> Optional[float]:
        try:
            value = metadata.get(key)
            if value is None or value == "":
                return None
            return float(value)
        except Exception:
            return None

    ra = _metadata_float("ra_deg")
    dec = _metadata_float("dec_deg")
    if ra is None or dec is None:
        parsed_ra, parsed_dec = _parse_ra_dec(output)
        if ra is None:
            ra = parsed_ra
        if dec is None:
            dec = parsed_dec

    obj_type = str(
        metadata.get("object_type")
        or metadata.get("simbad_type")
        or _parse_object_type(output)
        or ""
    ).casefold()

    if ra is not None and dec is not None:
        metadata.update({"ra_deg": float(ra), "dec_deg": float(dec)})
    if str(survey or "").strip():
        metadata["survey_requested"] = str(survey).strip()

    reference_note_html = ""
    if with_image and _solar_system_reference_kind(clean_query, obj_type):
        reference_result = _generate_solar_system_reference_image(
            clean_query, width=int(width), height=int(height)
        )
        if reference_result.files:
            files.extend(reference_result.files)
            metadata.update(
                {
                    "image_status": "solar_system_reference_attached",
                    **(reference_result.metadata or {}),
                }
            )
            reference_note_html = _lookup_panel(
                "Reference image",
                _lookup_inline_items(
                    [
                        ("Image", "Generated local reference disk for planets/moons"),
                        (
                            "Use",
                            "Visual reference only; ephemeris values remain from FZASTRO/Horizons",
                        ),
                    ]
                ),
            )
        elif reference_result.text:
            metadata["reference_image_status"] = str(reference_result.text)

    if (
        with_image
        and ra is not None
        and dec is not None
        and not force_fzastro_horizons
        and not any(
            token in obj_type
            for token in ("planet", "moon", "star", "comet", "spacecraft")
        )
    ):
        image_result = fetch_sky_image(
            ra,
            dec,
            fov_deg=fov_deg,
            width=int(width),
            height=int(height),
            survey=survey,
            rotation_angle=float(rotation_angle),
        )

        if image_result.files:
            files.extend(image_result.files)
            metadata.update({"image_status": "attached", **image_result.metadata})
        else:
            metadata["image_status"] = image_result.text

    header = f"**Astro lookup: {clean_query}**\n\n"
    imaging_lines = []
    if with_image and ra is not None and dec is not None:
        imaging_lines.append(
            f"FOV: {float(fov_deg):.3f}°"
            + (f" × {float(fov_y_deg):.3f}°" if fov_y_deg is not None else "")
        )
        imaging_lines.append(
            f"Image: {int(width)} × {int(height)} px, rotation {float(rotation_angle):.0f}°"
        )
        if str(survey or "").strip():
            imaging_lines.append(f"Survey: {str(survey).strip()}")
        if camera_name or focal_mm is not None:
            label = str(camera_name or "Camera")
            if focal_mm is not None:
                label += f" at {float(focal_mm):.1f} mm"
            imaging_lines.append(label)
    imaging_note = ""
    if imaging_lines:
        imaging_note = "\n\n**Imaging setup**\n" + "\n".join(
            f"- {line}" for line in imaging_lines
        )
    lookup_mode = (
        "fast SIMBAD/local catalog path"
        if metadata.get("fast_lookup")
        else "embedded FZASTRO lookup"
    )
    if metadata.get("fast_lookup"):
        source_label = "Migrated FZASTRO LOOKUP tool"
    else:
        source_label = "Embedded FZASTRO LOOKUP tool"
    note = imaging_note + f"\n\n_Source: {source_label}._"

    # Fast lookup can now return pre-rendered HTML cards. Do not wrap those in
    # a fenced text block, otherwise the chat renderer shows the HTML source
    # literally with a "Copy code" button. Legacy script output remains plain
    # text and is still safely displayed in a monospace block.
    output_stripped = output.rstrip()
    output_is_html = (
        output_stripped.lstrip()
        .lower()
        .startswith(("<div", "<table", "<section", "<article"))
    )

    if output_is_html:
        rendered_text = (
            output_stripped
            + reference_note_html
            + _lookup_imaging_setup_html(imaging_lines)
        )
    else:
        legacy_html = _format_legacy_lookup_html(
            clean_query,
            output_stripped,
            "FZASTRO Horizons" if force_fzastro_horizons else "embedded FZASTRO lookup",
        )
        if legacy_html:
            rendered_text = (
                legacy_html
                + reference_note_html
                + _lookup_imaging_setup_html(imaging_lines)
            )
        else:
            rendered_text = header + "```text\n" + output_stripped + "\n```" + note

    return AstroToolResult(
        title=f"Astro lookup: {clean_query}",
        text=rendered_text,
        files=files,
        success=True,
        metadata=metadata,
    )


def _resolve_timezone(lat: float, lon: float, fallback: str = "UTC") -> str:
    """Resolve a timezone without making timezonefinder a hard dependency.

    `timezonefinder` is useful, but on some Windows systems pip tries to
    compile it and fails without Microsoft C++ Build Tools. The migrated astro
    tools only need a valid IANA timezone string, so we keep a small practical
    fallback layer and let callers pass `tz` explicitly when precision matters.
    """
    try:
        from timezonefinder import TimezoneFinder

        tz = TimezoneFinder(in_memory=True).timezone_at(lat=float(lat), lng=float(lon))

        if tz:
            return tz
    except Exception as exc:
        log_debug("astro_tools._resolve_timezone timezonefinder fallback", exc)

    # Practical built-in fallbacks for the default development locations.
    # These avoid the Windows C++ compiler requirement during first migration.
    if 34.0 <= float(lat) <= 42.5 and 19.0 <= float(lon) <= 30.5:
        return "Europe/Athens"
    if 48.0 <= float(lat) <= 55.5 and 13.0 <= float(lon) <= 24.5:
        return "Europe/Warsaw"

    return fallback


def _format_seeing_forecast_html(
    output: str,
    lat: float,
    lon: float,
    elev: float,
    tz: str,
) -> Optional[str]:
    """Render migrated see.py output as compact HTML.

    The underlying see.py calculations stay unchanged; this only reshapes the
    terminal-style report so the chat pane does not waste vertical space.
    """
    import html as _html

    raw = str(output or "").strip()
    if not raw:
        return None

    lines = [line.rstrip() for line in raw.splitlines()]
    score_line = next(
        (line.strip() for line in lines if line.strip().startswith("Score ≥")), ""
    )

    segments: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    in_table = False

    row_re = re.compile(
        r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s+"
        r"(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+"
        r"(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$"
    )

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("Timezone:"):
            if current and (current.get("darkness") or current.get("rows")):
                segments.append(current)
            current = {
                "timezone": stripped.split(":", 1)[1].strip(),
                "site": "",
                "darkness": "",
                "moon": "",
                "rows": [],
            }
            in_table = False
            continue

        if current is None:
            continue

        if stripped.startswith("Site:"):
            current["site"] = stripped.split(":", 1)[1].strip()
            continue
        if stripped.startswith("Astronomical darkness:"):
            current["darkness"] = stripped.split(":", 1)[1].strip()
            continue
        if stripped.startswith("Moon Phase:"):
            current["moon"] = (
                stripped.split(":", 1)[1]
                .strip()
                .replace("  •  ", " · ")
                .replace(" • ", " · ")
            )
            continue
        if stripped.startswith("Local Time"):
            in_table = True
            continue
        if set(stripped) == {"-"}:
            continue
        if stripped.startswith("Score ≥"):
            continue

        if in_table:
            match = row_re.match(stripped)
            if match:
                current["rows"].append(match.groups())

    if current and (current.get("darkness") or current.get("rows")):
        segments.append(current)

    if not segments:
        return None

    def esc(value: Any) -> str:
        return _html.escape(str(value or ""), quote=True)

    def score_badge(score: str) -> str:
        try:
            val = int(float(score))
        except Exception:
            val = 0
        bg = "#17351f" if val >= 80 else "#3a3116" if val >= 50 else "#3a1c1c"
        fg = "#9df0b0" if val >= 80 else "#ffd66b" if val >= 50 else "#ff9b9b"
        return (
            f'<span style="display:inline-block; min-width:34px; text-align:center; '
            f"padding:2px 7px; border-radius:999px; background:{bg}; color:{fg}; "
            f'font-weight:700;">{esc(score)}</span>'
        )

    # Compact, single-row header. Keep this simple because Qt's markdown/HTML
    # renderer can collapse complex chip/card CSS into cramped text.
    top = (
        '<div style="margin:0 0 8px 0; padding:10px 12px; border:1px solid #26313d; '
        'border-radius:10px; background:#0f141a; color:#dce7f4;">'
        '<div style="font-size:16px; font-weight:800; color:#ffffff; margin-bottom:6px;">Night meteorology forecast</div>'
        f'<div style="font-size:13px; line-height:1.45;">'
        f'<b>Location:</b> {esc(f"{float(lat):.4f}°, {float(lon):.4f}°")} &nbsp; · &nbsp; '
        f'<b>Elevation:</b> {esc(f"{float(elev):.0f} m")} &nbsp; · &nbsp; '
        f"<b>Timezone:</b> {esc(tz)}"
        f"</div>"
        "</div>"
    )

    score_clean = (
        score_line.replace(" - Score breakdown:", " · Breakdown:")
        if score_line
        else "Score ≥80 = Good · 50–79 = OK · <50 = Poor"
    )

    table_header = (
        "<tr>"
        '<th style="text-align:left;">Time</th>'
        "<th>Score</th>"
        "<th>Cloud</th>"
        "<th>Low</th>"
        "<th>Mid</th>"
        "<th>High</th>"
        "<th>Moon</th>"
        "<th>Temp</th>"
        "<th>Dew</th>"
        "<th>RH</th>"
        "<th>Wind</th>"
        "<th>Gust</th>"
        "<th>Dir</th>"
        "<th>MSLP</th>"
        "</tr>"
    )

    segment_html: List[str] = []
    for idx, seg in enumerate(segments, start=1):
        darkness = esc(seg.get("darkness") or "Astronomical darkness unavailable")
        moon = esc(seg.get("moon") or "Moon data unavailable")
        site = esc(
            seg.get("site")
            or f"lat {float(lat):.2f}°, lon {float(lon):.2f}°, elevation {float(elev):.0f} meters"
        )
        rows_html = []
        for row in seg.get("rows", []):
            (
                local_time,
                score,
                cloud,
                low,
                mid,
                high,
                moon_pct,
                temp,
                dew,
                rh,
                wind,
                gust,
                direction,
                pressure,
            ) = row
            short_time = local_time[11:16] if len(local_time) >= 16 else local_time
            rows_html.append(
                "<tr>"
                f'<td style="text-align:left; white-space:nowrap; color:#dce7f4;">{esc(short_time)}</td>'
                f"<td>{score_badge(score)}</td>"
                f"<td>{esc(cloud)}%</td>"
                f"<td>{esc(low)}%</td>"
                f"<td>{esc(mid)}%</td>"
                f"<td>{esc(high)}%</td>"
                f"<td>{esc(moon_pct)}%</td>"
                f"<td>{esc(temp)}°</td>"
                f"<td>{esc(dew)}°</td>"
                f"<td>{esc(rh)}%</td>"
                f"<td>{esc(wind)}</td>"
                f"<td>{esc(gust)}</td>"
                f"<td>{esc(direction)}°</td>"
                f"<td>{esc(pressure)}</td>"
                "</tr>"
            )

        if not rows_html:
            rows_html.append(
                '<tr><td colspan="14" style="text-align:left; color:#ffcc7a;">No hourly rows parsed from see.py output.</td></tr>'
            )

        segment_html.append(
            '<div style="margin:10px 0 14px 0; padding:12px 14px; border:1px solid #26313d; '
            'border-radius:12px; background:#0f141a;">'
            f'<div style="font-size:15px; font-weight:800; color:#ffffff; margin-bottom:7px;">Night {idx} · {darkness}</div>'
            '<div style="margin-bottom:8px; color:#b9c7d6;">'
            f"<b>Site:</b> {site} &nbsp; · &nbsp; <b>Moon:</b> {moon}"
            "</div>"
            '<div style="margin-bottom:8px; color:#aebdcc; font-size:13px;">'
            f"{esc(score_clean)}"
            "</div>"
            '<div style="overflow-x:auto;">'
            '<table style="border-collapse:collapse; width:100%; font-family:Segoe UI, Arial, sans-serif; font-size:13px;">'
            '<thead style="background:#17202a; color:#ffffff;">'
            f"{table_header}"
            "</thead>"
            '<tbody style="color:#e8edf3;">'
            + "".join(rows_html)
            + "</tbody></table></div></div>"
        )

    hint = '<div style="margin-top:6px; color:#9fb2c7; font-size:13px;">Cloud/low/mid/high/moon are percentages · wind/gust in m/s · pressure in hPa.</div>'
    return top + "".join(segment_html) + hint


def observing_forecast(
    lat: float,
    lon: float,
    elev: float = 0.0,
    tz: Optional[str] = None,
    nights: int = 4,
) -> AstroToolResult:
    """Run migrated FZASTRO see.py.

    This is the night-ahead meteorology/observing forecast tool: astro-dark
    windows, cloud layers, moon illumination, temperature, dew point, humidity,
    wind, gusts, direction, pressure, and an imaging score.
    """
    if not SEE_FILE.exists():
        return _script_error(SEE_FILE)

    lat = max(-90.0, min(90.0, float(lat)))
    lon = max(-180.0, min(180.0, float(lon)))
    nights = max(1, min(4, int(nights)))
    tz = str(tz or "").strip() or _resolve_timezone(lat, lon, "UTC")

    args = [
        "--lat",
        f"{lat:.6f}",
        "--lon",
        f"{lon:.6f}",
        "--elev",
        f"{float(elev):.1f}",
        "--tz",
        tz,
        "--nights",
        str(nights),
    ]

    try:
        return_code, stdout, stderr, elapsed = _run_script(SEE_FILE, args, timeout=180)
    except AstroToolCancelled:
        raise
    except Exception as exc:
        log_exception("astro_tools.observing_forecast", exc)
        return AstroToolResult(
            title="Night meteorology forecast",
            text=f"Night meteorology forecast failed: {exc}",
            success=False,
        )

    output = _decode(stdout)
    error_text = _decode(stderr)

    if return_code != 0:
        _log_script_failure(
            "observing_forecast", return_code, output, error_text, elapsed, args
        )
        return AstroToolResult(
            title="Night meteorology forecast",
            text=(error_text or output or "Night meteorology forecast failed."),
            success=False,
        )

    formatted = _format_seeing_forecast_html(output, lat, lon, float(elev), tz)
    if formatted:
        # The formatted HTML already contains the title and location header.
        # Avoid adding a duplicate markdown title above it.
        text = formatted
    else:
        text = (
            f"**Night meteorology forecast**\n\n"
            f"Location: {lat:.4f}, {lon:.4f} · Elevation: {float(elev):.0f} m · Timezone: {tz}\n\n"
            "```text\n" + output.rstrip() + "\n```"
        )
    return AstroToolResult(
        title="Night meteorology forecast",
        text=text,
        success=True,
        metadata={
            "elapsed": elapsed,
            "lat": lat,
            "lon": lon,
            "tz": tz,
            "fzastro_script": "see.py",
            "formatted_html": bool(formatted),
        },
    )


def _best_target_lookup_url(name: str) -> str:
    return "fzastro://lookup?object=" + quote_plus(str(name or "").strip())


def _target_cell_style(kind: str = "text") -> str:
    base = (
        "padding:8px 12px;"
        "border-bottom:1px solid #303844;"
        "background:#12171d;"
        "color:#e9eef5;"
        "white-space:nowrap;"
        "font-family:'Cascadia Code','JetBrains Mono',Consolas,monospace;"
        "font-size:13px;"
        "line-height:1.35;"
    )
    if kind == "header":
        return (
            base
            + "background:#1d242d;"
            + "color:#ffffff;"
            + "font-weight:700;"
            + "border-top:1px solid #34404d;"
        )
    if kind == "num":
        return base + "text-align:right;"
    if kind == "name":
        return base + "min-width:92px;"
    if kind == "type":
        return base + "min-width:122px;"
    if kind == "date":
        return base + "min-width:154px;"
    return base


def _target_pretty_type(value: str) -> str:
    text = str(value or "").strip()
    aliases = {
        "Galaxy Clus": "Galaxy Cluster",
        "Gal Clus": "Galaxy Cluster",
        "Globular": "Globular",
        "Open": "Open",
        "Planetary": "Planetary",
    }
    return aliases.get(text, text)


def _target_html_cell(value: object, kind: str = "text") -> str:
    return f'<td style="{_target_cell_style(kind)}">{html_escape(str(value or "").strip())}</td>'


def _target_html_header(value: object, kind: str = "text") -> str:
    return f'<th style="{_target_cell_style("header")}{"text-align:right;" if kind == "num" else ""}">{html_escape(str(value or "").strip())}</th>'


def _target_panel_style() -> str:
    return (
        "border:1px solid #303844;"
        "background:#12171d;"
        "border-radius:8px;"
        "padding:12px 14px;"
        "margin:8px 0 12px 0;"
        "color:#e9eef5;"
    )


def _target_label_style() -> str:
    return "color:#9aa7b8;font-size:12px;margin-bottom:3px;"


def _target_value_style() -> str:
    return "color:#f2f6fb;font-size:14px;font-weight:650;"


def _target_metric(label: str, value: object) -> str:
    return (
        '<div style="min-width:160px;padding:8px 10px;border:1px solid #27313d;'
        'border-radius:7px;background:#0f141a;">'
        f'<div style="{_target_label_style()}">{html_escape(str(label))}</div>'
        f'<div style="{_target_value_style()}">{html_escape(str(value or "—"))}</div>'
        "</div>"
    )


def _target_info_line(label: str, value: object, accent: bool = False) -> str:
    border = "#3a4655" if accent else "#27313d"
    bg = "#151b23" if accent else "#0f141a"
    return (
        f'<div style="padding:9px 10px;margin-top:8px;border:1px solid {border};'
        f'border-radius:7px;background:{bg};">'
        f'<span style="color:#9aa7b8;font-size:12px;font-weight:650;text-transform:uppercase;letter-spacing:.02em;">{html_escape(str(label))}</span>'
        f'<div style="margin-top:4px;color:#eef3f9;font-size:13px;line-height:1.35;">{html_escape(str(value or "—"))}</div>'
        "</div>"
    )


def _clean_target_note(line: str) -> str:
    text = str(line or "").strip()
    while text.startswith("-"):
        text = text[1:].strip()
    return text


def _extract_target_prefix(lines: list[str], prefix: str) -> str:
    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith(prefix.lower()):
            return stripped.split(":", 1)[1].strip() if ":" in stripped else ""
    return ""


def _format_best_targets_header(
    lat: float, lon: float, elev: float, min_alt: float
) -> str:
    """Render the target planner heading as a compact two-line summary."""
    summary = (
        f"Location: {lat:.4f}°, {lon:.4f}°"
        f" · Elevation {float(elev):.0f} m"
        f" · Min altitude {float(min_alt):.0f}°"
    )
    return (
        '<div style="margin:0 0 8px 0;">'
        '<div style="font-size:18px;font-weight:800;color:#ffffff;margin-bottom:4px;">Best astrophotography targets</div>'
        '<div style="color:#cdd6e1;font-size:13px;line-height:1.35;">'
        f"{html_escape(summary)}"
        "</div>"
        "</div>"
    )


def _target_compact_line(label: str, value: object) -> str:
    return (
        '<div style="margin:2px 0;color:#cdd6e1;font-size:13px;line-height:1.35;">'
        f'<span style="color:#9fb2c8;font-weight:700;">{html_escape(str(label))}:</span> '
        f'{html_escape(str(value or "—"))}'
        "</div>"
    )


def _format_best_targets_intro(before: str) -> str:
    """Render the target.py pre-table notes as a compact summary.

    The previous card layout was readable but too tall. Keep the useful
    observing context, but compress it into a few single-line rows so the
    target table appears quickly.
    """
    raw_lines = str(before or "").splitlines()
    lines = [line.strip() for line in raw_lines if line.strip()]
    if not lines:
        return ""

    timezone = _extract_target_prefix(lines, "Timezone:")
    site = _extract_target_prefix(lines, "Site:")
    darkness = _extract_target_prefix(lines, "Astronomical darkness:")
    moon_phase = _extract_target_prefix(lines, "Moon Phase:")

    moon_notes = []
    score_line = ""
    score_breakdown = ""
    for line in lines:
        note = _clean_target_note(line)
        if not note:
            continue
        low = note.lower()
        if low.startswith(
            (
                "new moon",
                "full moon",
                "first quarter",
                "last quarter",
                "waxing",
                "waning",
                "rise",
                "set",
            )
        ):
            moon_notes.append(note)
        elif (
            note.startswith("Score ≥")
            or note.startswith("Score >=")
            or note.startswith("Score >")
        ):
            score_line = note
        elif low.startswith("score breakdown"):
            score_breakdown = note

    if not any(
        [timezone, site, darkness, moon_phase, moon_notes, score_line, score_breakdown]
    ):
        return (
            '<pre style="margin:0 0 8px 0;color:#cfd7e3;background:transparent;'
            "font-family:'Cascadia Code','JetBrains Mono',Consolas,monospace;font-size:13px;line-height:1.35;\">"
            + html_escape(before)
            + "</pre>"
        )

    moon_summary_parts = []
    if moon_phase:
        moon_summary_parts.append(f"Phase {moon_phase}")
    moon_summary_parts.extend(moon_notes)
    moon_summary = " · ".join(moon_summary_parts) if moon_summary_parts else "—"

    context_bits = []
    if timezone:
        context_bits.append(f"Timezone {timezone}")
    if site:
        context_bits.append(site)

    score = score_line
    if score_breakdown:
        score = (score + " · " if score else "") + score_breakdown

    parts = [
        '<div style="border:1px solid #28313d;background:#10161d;border-radius:8px;'
        'padding:8px 10px;margin:4px 0 8px 0;color:#e9eef5;">'
    ]
    if context_bits:
        parts.append(_target_compact_line("Site", " · ".join(context_bits)))
    if darkness:
        parts.append(_target_compact_line("Darkness", darkness))
    if moon_summary and moon_summary != "—":
        parts.append(_target_compact_line("Moon", moon_summary))
    if score:
        parts.append(_target_compact_line("Scoring", score))
    parts.append("</div>")
    return "".join(parts)


def _format_best_targets_after(after: str) -> str:
    """Compact the verbose selection-filter notes printed after the table."""
    lines = [line.strip() for line in str(after or "").splitlines() if line.strip()]
    if not lines:
        return ""

    # Compress the standard Selection filters block into one short line. The
    # explanatory bullets are useful in terminal mode but too tall in the chat UI.
    if any(line.lower().startswith("selection filters") for line in lines):
        values = []
        mapping = {
            "MIN_ALT": "Min alt",
            "MIN_DURATION_MIN": "Duration",
            "MAX_AIRMASS": "Airmass",
            "EDGE_GUARD_MIN": "Edge guard",
            "REF_HOUR_LOCAL": "Ref hour",
            "DEC_MAX_N": "Dec cap",
            "DIURNAL_SWING_MIN": "Swing",
        }
        for line in lines:
            note = _clean_target_note(line)
            if " = " not in note:
                continue
            key, value = note.split(" = ", 1)
            key = key.strip()
            label = mapping.get(key, key.replace("_", " ").title())
            values.append(f"{label} {value.strip()}")
        if values:
            return (
                '<div style="margin:6px 0 8px 0;color:#aeb8c7;font-size:12px;line-height:1.35;">'
                '<span style="color:#9fb2c8;font-weight:700;">Filters:</span> '
                + html_escape(" · ".join(values))
                + "</div>"
            )

    return (
        '<pre style="margin:8px 0 0 0;color:#cfd7e3;background:transparent;'
        "font-family:'Cascadia Code','JetBrains Mono',Consolas,monospace;font-size:13px;line-height:1.35;\">"
        + html_escape(after)
        + "</pre>"
    )


def _format_best_targets_output(output: str) -> str:
    """Convert the fixed-width target.py table into a polished clickable table.

    The target planner still produces the original terminal table. For the chat
    UI we parse only that table and render stable HTML instead of a Markdown
    table. QTextBrowser renders Markdown tables unevenly at wide widths; this
    hand-rendered version keeps the grid consistent while preserving local
    fzastro:// lookup links on object names.
    """
    raw = str(output or "").rstrip()
    if not raw:
        return ""

    lines = raw.splitlines()
    header_idx = None
    for index, line in enumerate(lines):
        if re.match(r"^\s*Grade\s+Name\s+Type\s+Const\s+Wdeg\s+Hdeg\s+MaxAlt", line):
            header_idx = index
            break

    if header_idx is None or header_idx + 1 >= len(lines):
        return "```text\n" + raw + "\n```"

    header = lines[header_idx]
    separator = lines[header_idx + 1]
    if not re.match(r"^\s*-{12,}\s*$", separator):
        return "```text\n" + raw + "\n```"

    column_names = [
        "Grade",
        "Name",
        "Type",
        "Const",
        "Wdeg",
        "Hdeg",
        "MaxAlt°",
        "Airmass↓",
        "Vis",
        "Best Local",
    ]
    source_column_names = [
        "Grade",
        "Name",
        "Type",
        "Const",
        "Wdeg",
        "Hdeg",
        "MaxAlt",
        "Airmass",
        "Vis",
        "Best Local",
    ]
    starts = []
    for name in source_column_names:
        pos = header.find(name)
        if pos < 0:
            return "```text\n" + raw + "\n```"
        starts.append(pos)
    ends = starts[1:] + [None]

    rows = []
    end_idx = header_idx + 2
    for index in range(header_idx + 2, len(lines)):
        line = lines[index]
        if re.match(r"^\s*-{12,}\s*$", line):
            end_idx = index
            break
        if not line.strip():
            end_idx = index
            break
        cells = []
        for start, end in zip(starts, ends):
            cells.append(
                line[start:end].strip() if end is not None else line[start:].strip()
            )
        if len(cells) == len(column_names) and cells[0].strip():
            rows.append(cells)
        end_idx = index + 1

    if not rows:
        return "```text\n" + raw + "\n```"

    before = "\n".join(lines[:header_idx]).strip()
    after_lines = (
        lines[end_idx + 1 :]
        if end_idx < len(lines) and re.match(r"^\s*-{12,}\s*$", lines[end_idx])
        else lines[end_idx:]
    )
    after = "\n".join(after_lines).strip()

    blocks = []
    if before:
        intro = _format_best_targets_intro(before)
        if intro:
            blocks.append(intro)

    blocks.append(
        '<div style="margin:4px 0 10px 0;color:#aeb8c7;font-size:13px;">'
        "Click a target name to open lookup details and the sky image."
        "</div>"
    )

    table_parts = [
        '<table cellspacing="0" cellpadding="0" style="border-collapse:separate;border-spacing:0;margin:6px 0 12px 0;max-width:100%;">',
        "<thead><tr>",
    ]
    numeric_cols = {0, 4, 5, 6, 7, 8}
    kind_by_index = {
        0: "num",
        1: "name",
        2: "type",
        4: "num",
        5: "num",
        6: "num",
        7: "num",
        8: "num",
        9: "date",
    }
    for i, name in enumerate(column_names):
        table_parts.append(
            _target_html_header(name, "num" if i in numeric_cols else "text")
        )
    table_parts.append("</tr></thead><tbody>")

    for cells in rows:
        grade, name, obj_type, const, wdeg, hdeg, max_alt, airmass, vis, best_local = (
            cells
        )
        lookup_url = html_escape(_best_target_lookup_url(name), quote=True)
        safe_name = html_escape(name)
        link = (
            f"<a href=\"{lookup_url}\" style=\"color:#78b7ff;text-decoration:none;font-weight:650;font-family:'Cascadia Code','JetBrains Mono',Consolas,monospace;\">{safe_name}</a>"
            if name
            else ""
        )
        table_parts.append("<tr>")
        table_parts.append(_target_html_cell(grade, kind_by_index.get(0, "text")))
        table_parts.append(f'<td style="{_target_cell_style("name")}">{link}</td>')
        table_parts.append(
            _target_html_cell(
                _target_pretty_type(obj_type), kind_by_index.get(2, "text")
            )
        )
        table_parts.append(_target_html_cell(const, kind_by_index.get(3, "text")))
        table_parts.append(_target_html_cell(wdeg, kind_by_index.get(4, "text")))
        table_parts.append(_target_html_cell(hdeg, kind_by_index.get(5, "text")))
        table_parts.append(_target_html_cell(max_alt, kind_by_index.get(6, "text")))
        table_parts.append(_target_html_cell(airmass, kind_by_index.get(7, "text")))
        table_parts.append(_target_html_cell(vis, kind_by_index.get(8, "text")))
        table_parts.append(_target_html_cell(best_local, kind_by_index.get(9, "text")))
        table_parts.append("</tr>")

    table_parts.append("</tbody></table>")
    blocks.append("".join(table_parts))

    if after:
        after_html = _format_best_targets_after(after)
        if after_html:
            blocks.append(after_html)

    return "\n".join(blocks).strip()


def best_targets(
    lat: float,
    lon: float,
    elev: float = 0.0,
    date: Optional[str] = None,
    limit: int = 10,
    min_alt: float = 45.0,
    tz: Optional[str] = None,
) -> AstroToolResult:
    """Run the migrated target planner."""
    if not TARGET_FILE.exists():
        return _script_error(TARGET_FILE)

    lat = max(-90.0, min(90.0, float(lat)))
    lon = max(-180.0, min(180.0, float(lon)))
    limit = max(1, min(50, int(limit)))
    min_alt = max(0.0, min(89.0, float(min_alt)))
    tz = str(tz or "").strip() or _resolve_timezone(lat, lon, "UTC")

    args = [
        "--lat",
        f"{lat:.6f}",
        "--lon",
        f"{lon:.6f}",
        "--elev",
        f"{float(elev):.1f}",
        "--tz",
        tz,
        "--limit",
        str(limit),
        "--min_alt",
        f"{min_alt:.1f}",
    ]

    if date:
        args.extend(["--date", str(date)])

    try:
        return_code, stdout, stderr, elapsed = _run_script(
            TARGET_FILE, args, timeout=180
        )
    except AstroToolCancelled:
        raise
    except Exception as exc:
        log_exception("astro_tools.best_targets", exc)
        return AstroToolResult(
            title="Best targets", text=f"Target planner failed: {exc}", success=False
        )

    output = _decode(stdout)
    error_text = _decode(stderr)

    if return_code != 0:
        _log_script_failure(
            "best_targets", return_code, output, error_text, elapsed, args
        )
        return AstroToolResult(
            title="Best targets",
            text=(error_text or output or "Target planner failed."),
            success=False,
        )

    formatted_output = _format_best_targets_output(output)
    text = _format_best_targets_header(lat, lon, elev, min_alt) + (
        formatted_output or "Target planner finished with no output."
    )
    return AstroToolResult(
        title="Best targets",
        text=text,
        success=True,
        metadata={"elapsed": elapsed, "lat": lat, "lon": lon, "tz": tz},
    )


def _format_solar_system_map_html(
    dt_label: str,
    size: int,
    orbits: str,
    dist: str,
    elapsed: Optional[float] = None,
) -> str:
    """Render the solar-system map metadata as a compact Qt-safe HTML card."""
    time_text = str(dt_label or "current time").strip() or "current time"
    orbits_text = "shown" if str(orbits).lower() == "yes" else "hidden"
    dist_text = "shown" if str(dist).lower() == "yes" else "hidden"
    elapsed_text = (
        f" · Rendered in {float(elapsed):.2f}s" if elapsed is not None else ""
    )

    return (
        '<div style="margin:0 0 6px 0;padding:8px 0 2px 0;color:#e9eef5;">'
        '<div style="font-size:21px;font-weight:950;color:#ffffff;line-height:1.18;margin:0 0 6px 0;">'
        "Solar-system map"
        "</div>"
        '<div style="font-size:14px;line-height:1.55;color:#dce7f4;">'
        '<span style="color:#9fb2c8;font-size:11px;font-weight:850;">Time:</span> '
        f"{html_escape(time_text)}"
        "&nbsp;&nbsp;·&nbsp;&nbsp;"
        '<span style="color:#9fb2c8;font-size:11px;font-weight:850;">Image:</span> '
        f"{int(size)} × {int(size)} px"
        "&nbsp;&nbsp;·&nbsp;&nbsp;"
        '<span style="color:#9fb2c8;font-size:11px;font-weight:850;">Orbits:</span> '
        f"{html_escape(orbits_text)}"
        "&nbsp;&nbsp;·&nbsp;&nbsp;"
        '<span style="color:#9fb2c8;font-size:11px;font-weight:850;">Distance labels:</span> '
        f"{html_escape(dist_text)}"
        "</div>"
        '<div style="margin-top:4px;font-size:13px;line-height:1.45;color:#aeb8c7;">'
        "Source: migrated FZASTRO solar-system renderer · Skyfield ephemerides"
        f"{html_escape(elapsed_text)}"
        "</div>"
        "</div>"
    )


def solar_system_map(
    dt: Optional[str] = None, size: int = 2000, orbits: str = "yes", dist: str = "no"
) -> AstroToolResult:
    """Render a migrated solar-system map and save it as an attached PNG."""
    if not SOLAR_FILE.exists():
        return _script_error(SOLAR_FILE)

    size = max(600, min(3000, int(size)))
    orbits = "no" if str(orbits).lower().strip() in {"no", "false", "0"} else "yes"
    dist = "yes" if str(dist).lower().strip() in {"yes", "true", "1"} else "no"

    args = ["--size", str(size), "--orbits", orbits, "--dist", dist]

    if dt:
        args.extend(["--dt", str(dt)])

    try:
        return_code, stdout, stderr, elapsed = _run_script(
            SOLAR_FILE, args, timeout=210, binary=True
        )
    except AstroToolCancelled:
        raise
    except Exception as exc:
        log_exception("astro_tools.solar_system_map", exc)
        return AstroToolResult(
            title="Solar-system map",
            text=f"Solar-system map failed: {exc}",
            success=False,
        )

    error_text = _decode(stderr)

    if return_code != 0 or not stdout:
        _log_script_failure(
            "solar_system_map",
            return_code,
            "<binary stdout>" if stdout else "",
            error_text,
            elapsed,
            args,
        )
        return AstroToolResult(
            title="Solar-system map",
            text=(error_text or "Solar-system map failed."),
            success=False,
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = _safe_slug(dt or "now")
    output_path = ASTRO_OUTPUT_DIR / f"solar_system_{slug}_{timestamp}.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(stdout)

    label_dt = dt or "current time"
    text = _format_solar_system_map_html(label_dt, size, orbits, dist, elapsed)
    return AstroToolResult(
        title="Solar-system map",
        text=text,
        files=[str(output_path)],
        success=True,
        metadata={"elapsed": elapsed, "size": size, "orbits": orbits, "dist": dist},
    )
