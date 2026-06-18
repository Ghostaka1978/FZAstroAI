from __future__ import annotations

import hashlib
import json
from datetime import datetime
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import APP_DIR
from ..logging_utils import log_exception, log_warning

SETTINGS_FILE = APP_DIR / "nina_integration.json"
UPDATE_DOWNLOAD_DIR = APP_DIR / "downloads" / "fzastro_imaging"

# Empty by default so the bundled/FZAstro-branded update channel can be chosen
# without hardcoding a temporary or unofficial feed into production builds.
DEFAULT_UPDATE_MANIFEST_URL = ""

DEFAULT_SETTINGS: dict[str, Any] = {
    "executable_path": "",
    "bundle_dir": "bundled_apps/FZAstroImaging",
    "api_host": "127.0.0.1",
    "api_port": 1888,
    "installed_version": "",
    "update_manifest_url": DEFAULT_UPDATE_MANIFEST_URL,
    "auto_check_updates": True,
    # Do not silently replace equipment-control software.  This setting allows
    # automatic download after a user-visible check; install remains manual.
    "auto_download_updates": False,
    "last_update_check": "",
    "last_available_version": "",
    "last_download_path": "",
    "last_session_report_dir": "",
    "nina_sequence_import_dir": "",
    "last_api_sequence_name": "",
    "nina_image_dir": "",
    "equipment_prep_template_path": "",
}


@dataclass(frozen=True)
class NinaUpdateInfo:
    """Normalized update metadata from a manifest or GitHub release response."""

    version: str
    download_url: str = ""
    release_notes: str = ""
    sha256: str = ""
    published_at: str = ""
    source_url: str = ""
    is_newer: bool = False
    current_version: str = ""

    @property
    def has_download(self) -> bool:
        return bool(self.download_url.strip())


@dataclass(frozen=True)
class NinaSequenceOpenResult:
    """Result for a safe launch/open request for a generated sequence file."""

    sequence_path: str
    executable_path: str
    launched: bool
    open_attempted: bool
    message: str = ""


@dataclass(frozen=True)
class NinaApiResponse:
    """Normalized response from christian-photo/ninaAPI v2.

    The plugin returns HTTP 200 even for some failed operations, so callers must
    check the JSON ``Success`` field instead of relying only on transport success.
    """

    success: bool
    status_code: int
    response: Any = None
    error: str = ""
    type: str = "API"
    raw: dict[str, Any] | None = None

    @property
    def message(self) -> str:
        if self.success:
            return str(self.response or "OK")
        return str(self.error or self.response or "N.I.N.A. API request failed")


@dataclass(frozen=True)
class NinaApiLoadResult:
    """Result for loading a confirmed sequence into N.I.N.A. through the API."""

    success: bool
    sequence_path: str
    sequence_name: str = ""
    method: str = ""
    message: str = ""
    state: dict[str, Any] | None = None


def _settings_from_mapping(data: dict[str, Any] | None) -> dict[str, Any]:
    settings = dict(DEFAULT_SETTINGS)
    if isinstance(data, dict):
        for key in DEFAULT_SETTINGS:
            if key in data:
                settings[key] = data[key]
    settings["api_port"] = _safe_int(settings.get("api_port"), 1888)
    settings["auto_check_updates"] = bool(settings.get("auto_check_updates"))
    settings["auto_download_updates"] = bool(settings.get("auto_download_updates"))
    return settings


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


IMAGE_FILE_EXTENSIONS = {
    ".fit",
    ".fits",
    ".fts",
    ".xisf",
    ".tif",
    ".tiff",
    ".jpg",
    ".jpeg",
    ".png",
}


def _configured_folder(settings: dict[str, Any] | None, key: str) -> Path | None:
    data = _settings_from_mapping(settings)
    raw = str(data.get(key) or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    try:
        if path.exists() and path.is_dir():
            return path
    except Exception:
        return None
    return None


def iter_nina_image_files(settings: dict[str, Any] | None = None):
    """Yield configured N.I.N.A. image files for status/report fallback counts.

    N.I.N.A. setups often save into dated subfolders, so this scans below the
    configured root.  Missing/unconfigured folders simply yield nothing.
    """

    folder = _configured_folder(settings, "nina_image_dir")
    if folder is None:
        return
    try:
        for path in folder.rglob("*"):
            try:
                if path.is_file() and path.suffix.lower() in IMAGE_FILE_EXTENSIONS:
                    yield path
            except Exception:
                continue
    except Exception as exc:
        log_warning(f"nina_bridge.iter_nina_image_files failed: {exc}")


_FILENAME_TIMESTAMP_PATTERNS = (
    re.compile(r"(?P<date>\d{4}-\d{2}-\d{2})[_ -](?P<time>\d{2}[-:]\d{2}[-:]\d{2})"),
    re.compile(r"(?P<date>\d{8})[_ -](?P<time>\d{6})"),
)
_FRAME_INDEX_PATTERN = re.compile(r"(?:^|[_ -])(?P<index>\d{3,6})(?=\.[^.]+$)")
_FOLDER_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_IMAGE_SESSION_TOLERANCE_SECONDS = 300.0
_IMAGE_RUN_GAP_SECONDS = 900.0
_EXPOSURE_SECONDS_PATTERN = re.compile(
    r"(?:^|[_ -])(?P<exposure>\d+(?:\.\d+)?)s(?:[_ -]|$)", re.IGNORECASE
)


def _safe_file_mtime(path: Path) -> float:
    try:
        return float(path.stat().st_mtime)
    except Exception:
        return 0.0


def _local_epoch_from_datetime(value: datetime) -> float | None:
    try:
        return float(value.timestamp())
    except Exception:
        return None


def _parse_nina_filename_epoch(path: Path) -> float | None:
    """Return an epoch parsed from N.I.N.A.'s filename timestamp when present.

    Dropbox can refresh modified times on older files.  N.I.N.A. filenames are a
    stronger signal for the actual capture order, for example
    ``2026-06-18_01-48-01__60.00s_0000.fits``.
    """

    name = path.name
    for pattern in _FILENAME_TIMESTAMP_PATTERNS:
        match = pattern.search(name)
        if not match:
            continue
        date_text = match.group("date")
        time_text = match.group("time")
        try:
            if len(date_text) == 8:
                parsed = datetime.strptime(date_text + time_text, "%Y%m%d%H%M%S")
            else:
                parsed = datetime.strptime(
                    f"{date_text} {time_text.replace(':', '-')}",
                    "%Y-%m-%d %H-%M-%S",
                )
        except Exception:
            continue
        return _local_epoch_from_datetime(parsed)
    return None


def _parse_nina_folder_epoch(path: Path) -> float | None:
    """Return an epoch from a dated N.I.N.A. parent folder when available."""

    for parent in path.parents:
        name = parent.name.strip()
        if not _FOLDER_DATE_PATTERN.match(name):
            continue
        try:
            return _local_epoch_from_datetime(datetime.strptime(name, "%Y-%m-%d"))
        except Exception:
            continue
    return None


def nina_filename_frame_count(path: Path | str | None) -> int | None:
    """Return frame-count hint from a N.I.N.A. filename counter.

    ``..._0003.fits`` means N.I.N.A. has reached frame index 3, so the
    sequence has produced at least four numbered frames.  This is only a hint;
    callers should prefer real saved-file counts when available because users
    can delete or cloud-sync only part of a session folder.
    """

    if path is None:
        return None
    name = Path(path).name
    match = _FRAME_INDEX_PATTERN.search(name)
    if not match:
        return None
    try:
        return max(0, int(match.group("index"))) + 1
    except Exception:
        return None


def _nina_image_event_epoch(path: Path) -> float:
    """Return the best available capture-order timestamp for a saved image."""

    return (
        _parse_nina_filename_epoch(path)
        or _parse_nina_folder_epoch(path)
        or _safe_file_mtime(path)
    )


def _nina_image_sort_key(path: Path) -> tuple[float, float, str]:
    """Sort by capture timestamp first, modified time second.

    This prevents an old March calibration frame from winning just because
    Dropbox refreshed its filesystem modified time during sync.
    """

    return (_nina_image_event_epoch(path), _safe_file_mtime(path), str(path).casefold())


def _image_is_in_session(path: Path, since_epoch: float | None) -> bool:
    if since_epoch is None:
        return True
    try:
        threshold = float(since_epoch) - _IMAGE_SESSION_TOLERANCE_SECONDS
    except Exception:
        return True
    return _nina_image_event_epoch(path) >= threshold


def _parse_nina_exposure_seconds(path: Path) -> str | None:
    """Return the exposure token embedded in common N.I.N.A. filenames."""

    match = _EXPOSURE_SECONDS_PATTERN.search(path.name)
    if not match:
        return None
    try:
        return f"{float(match.group('exposure')):.3f}"
    except Exception:
        return match.group("exposure")


def _same_capture_run_signature(path: Path, reference: Path) -> bool:
    """Return whether ``path`` looks like the same N.I.N.A. image run.

    N.I.N.A. file patterns do not always include the target name.  The safest
    folder fallback is therefore the latest image's concrete folder plus stable
    filename traits such as extension and exposure length.  This prevents an old
    LIGHT folder with hundreds of unrelated frames from becoming the live count.
    """

    if path.parent != reference.parent:
        return False
    if path.suffix.lower() != reference.suffix.lower():
        return False
    reference_exposure = _parse_nina_exposure_seconds(reference)
    if reference_exposure is None:
        return True
    return _parse_nina_exposure_seconds(path) == reference_exposure


def latest_nina_image_session_files(
    settings: dict[str, Any] | None = None,
    since_epoch: float | None = None,
) -> list[Path]:
    """Return image files that best match the active/latest N.I.N.A. session.

    The user may point FZAstro at a large N.I.N.A. root such as
    ``D:/Dropbox/N.I.N.A`` containing many dated folders and old target runs.
    When a FZAstro-started session time is known, files from that window win.
    If the dialog was opened or rebuilt mid-session and the strict time filter
    finds nothing, this falls back to the newest image's own folder and trims the
    result to the most recent contiguous capture run.
    """

    folder = _configured_folder(settings, "nina_image_dir")
    if folder is None:
        return []

    latest = latest_nina_image_file(settings, since_epoch)
    strict_session = latest is not None and since_epoch is not None
    if latest is None and since_epoch is not None:
        latest = latest_nina_image_file(settings)
    if latest is None:
        return []

    try:
        siblings = sorted(
            (
                path
                for path in latest.parent.iterdir()
                if path.is_file()
                and path.suffix.lower() in IMAGE_FILE_EXTENSIONS
                and _same_capture_run_signature(path, latest)
            ),
            key=_nina_image_sort_key,
        )
    except Exception:
        return [latest]

    if strict_session and since_epoch is not None:
        filtered = [
            path for path in siblings if _image_is_in_session(path, since_epoch)
        ]
        if filtered:
            return filtered

    if not siblings:
        return [latest]

    latest_epoch = _nina_image_event_epoch(latest)
    run: list[Path] = []
    previous_epoch = latest_epoch
    for path in reversed(siblings):
        epoch = _nina_image_event_epoch(path)
        if epoch > latest_epoch + 1.0:
            continue
        if run and previous_epoch - epoch > _IMAGE_RUN_GAP_SECONDS:
            break
        run.append(path)
        previous_epoch = epoch
        if nina_filename_frame_count(path) == 1 and len(run) > 1:
            break

    return list(reversed(run)) if run else [latest]


def latest_nina_image_file(
    settings: dict[str, Any] | None = None,
    since_epoch: float | None = None,
) -> Path | None:
    """Return the newest image in the configured N.I.N.A. save folder.

    If ``since_epoch`` is supplied, only images that belong to the current
    session window are considered.  N.I.N.A. filename timestamps are preferred
    over filesystem modified times because cloud-sync folders can update old
    files during sync and make them look newest.
    """

    candidates = [
        path
        for path in (iter_nina_image_files(settings) or [])
        if _image_is_in_session(path, since_epoch)
    ]
    if not candidates:
        return None
    return max(candidates, key=_nina_image_sort_key)


def count_nina_image_files_since(
    settings: dict[str, Any] | None = None,
    since_epoch: float | None = None,
) -> int | None:
    """Count saved images, optionally only those newer than session start.

    The comparison uses N.I.N.A. filename timestamps when available and falls
    back to filesystem modified time.  A small tolerance avoids missing the
    first frame when N.I.N.A. creates the file while FZAstro is still marking
    the session start.
    """

    folder = _configured_folder(settings, "nina_image_dir")
    if folder is None:
        return None
    count = 0
    for path in iter_nina_image_files(settings) or []:
        try:
            if _image_is_in_session(path, since_epoch):
                count += 1
        except Exception:
            continue
    return count


def latest_nina_image_session_count(
    settings: dict[str, Any] | None = None,
    since_epoch: float | None = None,
) -> int | None:
    """Count real image files in the active/latest N.I.N.A. image run."""

    folder = _configured_folder(settings, "nina_image_dir")
    if folder is None:
        return None
    return len(latest_nina_image_session_files(settings, since_epoch))


def load_settings(path: Path | None = None) -> dict[str, Any]:
    settings_path = Path(path or SETTINGS_FILE)
    try:
        if settings_path.exists():
            return _settings_from_mapping(
                json.loads(settings_path.read_text(encoding="utf-8"))
            )
    except Exception as exc:
        log_exception("nina_bridge.load_settings", exc)
    return _settings_from_mapping(None)


def save_settings(settings: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    normalized = _settings_from_mapping(settings)
    settings_path = Path(path or SETTINGS_FILE)
    try:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(
            json.dumps(normalized, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except Exception as exc:
        log_exception("nina_bridge.save_settings", exc)
    return normalized


def project_root() -> Path:
    """Return app root in source mode or frozen EXE mode.

    PyInstaller one-file builds put module __file__ inside the temporary _MEI
    folder.  External bundled apps must resolve beside FZAstroAI.exe instead.
    """

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    return Path(__file__).resolve().parents[2]


def bundle_root(settings: dict[str, Any] | None = None) -> Path:
    data = _settings_from_mapping(settings)
    raw_bundle_dir = str(
        data.get("bundle_dir") or DEFAULT_SETTINGS["bundle_dir"]
    ).strip()
    path = Path(raw_bundle_dir).expanduser()
    if not path.is_absolute():
        path = project_root() / path
    return path


def _candidate_executable_paths(settings: dict[str, Any] | None = None) -> list[Path]:
    data = _settings_from_mapping(settings)
    candidates: list[Path] = []

    stored_path = str(data.get("executable_path") or "").strip()
    if stored_path:
        candidates.append(Path(stored_path).expanduser())

    root = bundle_root(data)
    candidates.extend(
        [
            root / "FZAstroImaging.exe",
            root / "FZAstro Imaging Control.exe",
        ]
    )

    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        key = str(candidate).lower()
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def find_default_executable(settings: dict[str, Any] | None = None) -> str:
    for candidate in _candidate_executable_paths(settings):
        try:
            if candidate.exists() and candidate.is_file():
                return str(candidate.resolve())
        except Exception:
            continue
    return ""


def launch_executable(executable_path: str | Path) -> subprocess.Popen:
    path = Path(str(executable_path or "").strip()).expanduser()
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"FZAstro Imaging executable not found: {path}")
    return subprocess.Popen([str(path)], cwd=str(path.parent))


def launch_sequence_file(
    sequence_path: str | Path,
    settings: dict[str, Any] | None = None,
    *,
    executable_path: str | Path | None = None,
) -> NinaSequenceOpenResult:
    """Launch FZAstro Imaging and ask it to open a generated sequence file.

    This is intentionally only an open/import request.  It never starts a
    sequence, slews the mount, starts guiding, cools the camera, or captures.
    N.I.N.A. builds may or may not accept a sequence path on the command line;
    the caller should still show the generated file path for manual Advanced
    Sequencer review.
    """

    sequence = Path(str(sequence_path or "").strip()).expanduser()
    if not sequence.exists() or not sequence.is_file():
        raise FileNotFoundError(f"N.I.N.A. sequence file not found: {sequence}")

    data = _settings_from_mapping(settings or load_settings())
    raw_executable = str(executable_path or find_default_executable(data)).strip()
    if not raw_executable:
        raise FileNotFoundError(
            "FZAstro Imaging executable was not found. Build/copy bundled_apps/FZAstroImaging/FZAstroImaging.exe or set it in FZAstro Imaging Control."
        )

    executable = Path(raw_executable).expanduser()
    if not executable.exists() or not executable.is_file():
        raise FileNotFoundError(f"FZAstro Imaging executable not found: {executable}")

    subprocess.Popen([str(executable), str(sequence)], cwd=str(executable.parent))
    return NinaSequenceOpenResult(
        sequence_path=str(sequence),
        executable_path=str(executable),
        launched=True,
        open_attempted=True,
        message=(
            "Launch/open request sent. Review the sequence in N.I.N.A. before starting any hardware action."
        ),
    )


def latest_sequence_file(plan_dir: str | Path | None = None) -> Path | None:
    """Return the newest generated N.I.N.A. sequence file, if any."""

    root = (
        Path(plan_dir).expanduser()
        if plan_dir
        else Path.home() / "Documents" / "FZAstroAI" / "Imaging Plans"
    )
    try:
        if not root.exists():
            return None
        candidates = list(root.rglob("*.nina-sequence.json"))
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.stat().st_mtime)
    except Exception as exc:
        log_warning("nina_bridge.latest_sequence_file", exc)
        return None


def is_process_running(
    process_names: tuple[str, ...] = (
        "FZAstroImaging.exe",
        "FZAstro Imaging Control.exe",
        "NINA.exe",
    )
) -> bool:
    if os.name != "nt":
        return False
    try:
        output = subprocess.check_output(
            ["tasklist", "/FO", "CSV", "/NH"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        lower = output.lower()
        return any(name.lower() in lower for name in process_names)
    except Exception:
        return False


def nina_api_base_url(settings: dict[str, Any] | None = None) -> str:
    """Return the christian-photo/ninaAPI v2 base URL from settings."""

    data = _settings_from_mapping(settings or load_settings())
    host = str(data.get("api_host") or "127.0.0.1").strip() or "127.0.0.1"
    port = _safe_int(data.get("api_port"), 1888)
    if host.startswith("http://") or host.startswith("https://"):
        base = host.rstrip("/")
    else:
        base = f"http://{host}:{port}"
    if not base.rstrip("/").endswith("/v2/api"):
        base = base.rstrip("/") + "/v2/api"
    return base.rstrip("/")


def nina_api_request(
    endpoint: str,
    settings: dict[str, Any] | None = None,
    *,
    method: str = "GET",
    body: str | bytes | None = None,
    content_type: str = "application/json",
    timeout: float = 8.0,
) -> NinaApiResponse:
    """Call christian-photo/ninaAPI and normalize its standard response envelope."""

    base = nina_api_base_url(settings)
    endpoint_text = str(endpoint or "").strip()
    if not endpoint_text.startswith("/"):
        endpoint_text = "/" + endpoint_text
    url = base + endpoint_text
    data = body.encode("utf-8") if isinstance(body, str) else body
    request = urllib.request.Request(
        url, data=data, method=str(method or "GET").upper()
    )
    request.add_header("Accept", "application/json")
    request.add_header("User-Agent", "FZAstroAI-NINA-API/1.0")
    if data is not None:
        request.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(
            request, timeout=timeout
        ) as response:  # noqa: S310 - user-configured local N.I.N.A. API
            payload = response.read(20_000_000)
            http_status = int(getattr(response, "status", 200) or 200)
    except urllib.error.HTTPError as exc:
        payload = exc.read() if hasattr(exc, "read") else b""
        try:
            raw = json.loads(payload.decode("utf-8")) if payload else {}
        except Exception:
            raw = {}
        return NinaApiResponse(
            success=False,
            status_code=int(getattr(exc, "code", 0) or 0),
            response=raw.get("Response") if isinstance(raw, dict) else None,
            error=(
                str(raw.get("Error") or exc.reason or exc)
                if isinstance(raw, dict)
                else str(exc)
            ),
            type=str(raw.get("Type") or "API") if isinstance(raw, dict) else "API",
            raw=raw if isinstance(raw, dict) else None,
        )
    except Exception as exc:
        return NinaApiResponse(success=False, status_code=0, error=str(exc), raw=None)
    try:
        raw = json.loads(payload.decode("utf-8")) if payload else {}
    except Exception as exc:
        return NinaApiResponse(
            success=False,
            status_code=http_status,
            error=f"Invalid API JSON response: {exc}",
            raw=None,
        )
    if not isinstance(raw, dict):
        return NinaApiResponse(
            success=False,
            status_code=http_status,
            response=raw,
            error="API response was not an object",
            raw=None,
        )
    success = bool(raw.get("Success"))
    return NinaApiResponse(
        success=success,
        status_code=int(raw.get("StatusCode") or http_status),
        response=raw.get("Response"),
        error=str(raw.get("Error") or ""),
        type=str(raw.get("Type") or "API"),
        raw=raw,
    )


def test_nina_api(settings: dict[str, Any] | None = None) -> NinaApiResponse:
    """Return the N.I.N.A. API plugin version if the API is reachable."""

    return nina_api_request("/version", settings=settings)


def ensure_nina_api_ready(
    settings: dict[str, Any] | None = None,
    *,
    launch_if_needed: bool = True,
    wait_seconds: float = 45.0,
) -> NinaApiResponse:
    """Return a ready N.I.N.A. API response, launching FZAstro Imaging if needed.

    The streamlined handoff button should not require the user to open N.I.N.A.
    manually.  If the API is already reachable this returns immediately.  If not,
    FZAstro launches the configured/bundled FZAstro Imaging executable and waits
    for the ninaAPI plugin to answer /version before continuing.
    """

    data = _settings_from_mapping(settings or load_settings())
    first = test_nina_api(data)
    if first.success:
        return first
    if not launch_if_needed:
        return first

    executable = find_default_executable(data)
    if not executable:
        return NinaApiResponse(
            success=False,
            status_code=first.status_code,
            response=first.response,
            error=(
                "N.I.N.A. API is not reachable and FZAstro Imaging executable was not found. "
                "Open FZAstro Imaging/N.I.N.A. manually or set the executable path in CONFIG."
            ),
            raw=first.raw,
        )

    try:
        if not is_process_running():
            launch_executable(executable)
    except Exception as exc:
        return NinaApiResponse(
            success=False,
            status_code=first.status_code,
            response=first.response,
            error=f"N.I.N.A. API is not reachable and FZAstro Imaging could not be launched: {exc}",
            raw=first.raw,
        )

    deadline = time.time() + max(3.0, float(wait_seconds))
    last = first
    while time.time() < deadline:
        time.sleep(1.0)
        last = test_nina_api(data)
        if last.success:
            return last

    return NinaApiResponse(
        success=False,
        status_code=last.status_code,
        response=last.response,
        error=(
            "FZAstro Imaging was launched, but the N.I.N.A. API did not become ready. "
            "Check that the ninaAPI plugin is enabled and listening on the configured host/port."
        ),
        raw=last.raw,
    )


def list_available_sequences(settings: dict[str, Any] | None = None) -> NinaApiResponse:
    """List sequence names visible to N.I.N.A.'s default Advanced Sequencer folder."""

    return nina_api_request("/sequence/list-available", settings=settings)


def get_sequence_state(settings: dict[str, Any] | None = None) -> NinaApiResponse:
    """Read current Advanced Sequencer state through the N.I.N.A. API."""

    return nina_api_request("/sequence/state", settings=settings, timeout=12.0)


def load_sequence_by_name(
    sequence_name: str, settings: dict[str, Any] | None = None
) -> NinaApiResponse:
    """Load a sequence known to N.I.N.A. using the discovered sequenceName parameter."""

    name = str(sequence_name or "").strip()
    if not name:
        return NinaApiResponse(
            success=False, status_code=0, error="No sequence name was supplied."
        )
    return nina_api_request(
        "/sequence/load?sequenceName=" + urllib.parse.quote(name, safe=""),
        settings=settings,
        timeout=20.0,
    )


def _api_message_is_transient_initialization(message: str) -> bool:
    """Return True for N.I.N.A. startup/load timing messages worth retrying."""

    lower = str(message or "").casefold()
    return any(
        fragment in lower
        for fragment in (
            "sequence is not initialized",
            "not initialized",
            "sequence not initialized",
            "not ready",
            "busy",
        )
    )


def _sleep_between_api_retries(attempt: int) -> None:
    time.sleep(min(2.0, 0.75 + (attempt * 0.25)))


def start_sequence_via_api(settings: dict[str, Any] | None = None) -> NinaApiResponse:
    """Request N.I.N.A. to start the loaded sequence. This is a real hardware action.

    christian-photo/ninaAPI exposes this endpoint as a GET request in the
    tested v2 API path.  POST/PUT return 405 Method Not Allowed.
    """

    return nina_api_request("/sequence/start", settings=settings, method="GET")


def stop_sequence_via_api(settings: dict[str, Any] | None = None) -> NinaApiResponse:
    """Request N.I.N.A. to stop/abort sequence execution if supported by the API."""

    attempts = [
        nina_api_request("/sequence/stop", settings=settings, method="GET"),
        nina_api_request(
            "/sequence/abort", settings=settings, method="GET", timeout=10.0
        ),
        nina_api_request("/sequence/stop", settings=settings, method="GET"),
        nina_api_request(
            "/sequence/abort", settings=settings, method="POST", timeout=10.0
        ),
    ]
    for response in attempts:
        if response.success:
            return response
    return attempts[0]


def _sequence_api_name_from_path(path: Path) -> str:
    name = path.name
    lower = name.lower()
    for suffix in (".nina-sequence.json", ".json", ".template"):
        if lower.endswith(suffix):
            return name[: -len(suffix)]
    return path.stem


def _safe_sequence_import_name(sequence: Path) -> str:
    """Return a plain JSON filename that N.I.N.A. will expose by sequenceName.

    FZAstro stores confirmed review artifacts as ``*.nina-sequence.json``.  The
    christian-photo/ninaAPI loader reliably loads files that live in N.I.N.A.'s
    own Advanced Sequencer folder as normal ``*.json`` files, then identifies
    them by their stem in ``/sequence/list-available``.
    """

    base = sequence.name
    lower = base.lower()
    if lower.endswith(".nina-sequence.json"):
        base = base[: -len(".nina-sequence.json")]
    elif lower.endswith(".json"):
        base = base[: -len(".json")]
    else:
        base = sequence.stem
    base = re.sub(r"[^A-Za-z0-9_. -]+", "_", base).strip(" ._")
    return (base or "FZAstro_Sequence") + ".json"


def _copy_sequence_to_import_dir(
    sequence: Path, settings: dict[str, Any]
) -> tuple[Path | None, str]:
    raw_dir = str(settings.get("nina_sequence_import_dir") or "").strip()
    if not raw_dir:
        return (
            None,
            "N.I.N.A. sequence folder is not configured. Set it in CONFIG to the folder N.I.N.A. Advanced Sequencer uses for saved sequences.",
        )
    import_dir = Path(raw_dir).expanduser()
    if not import_dir.exists() or not import_dir.is_dir():
        return None, f"N.I.N.A. sequence folder does not exist: {import_dir}"
    target = import_dir / _safe_sequence_import_name(sequence)
    target.write_text(sequence.read_text(encoding="utf-8"), encoding="utf-8")
    return target, ""


def load_confirmed_sequence_via_api(
    sequence_path: str | Path,
    settings: dict[str, Any] | None = None,
) -> NinaApiLoadResult:
    """Load a confirmed FZAstro sequence into N.I.N.A. through christian-photo/ninaAPI.

    The reliable route discovered by testing is GET /sequence/load?sequenceName=...
    against a sequence that N.I.N.A. can see in its default sequence folder.  POSTing
    arbitrary JSON may return a 500, so this function copies the confirmed sequence
    into the configured N.I.N.A. sequence folder first, then loads by sequenceName.
    """

    data = _settings_from_mapping(settings or load_settings())
    sequence = Path(str(sequence_path or "")).expanduser()
    if not sequence.exists() or not sequence.is_file():
        return NinaApiLoadResult(
            False,
            str(sequence),
            message=f"Confirmed sequence file not found: {sequence}",
        )

    version = ensure_nina_api_ready(data, launch_if_needed=True, wait_seconds=45.0)
    if not version.success:
        return NinaApiLoadResult(
            False,
            str(sequence),
            message=f"N.I.N.A. API is not ready: {version.message}",
        )

    copied_path, copy_error = _copy_sequence_to_import_dir(sequence, data)
    if copy_error:
        return NinaApiLoadResult(False, str(sequence), message=copy_error)
    load_name = _sequence_api_name_from_path(copied_path or sequence)

    available = None
    matched_name = ""
    candidates = [
        load_name,
        (copied_path.name if copied_path else sequence.name),
        (copied_path.stem if copied_path else sequence.stem),
        _sequence_api_name_from_path(sequence),
    ]
    names: list[str] = []
    for attempt in range(10):
        available = list_available_sequences(data)
        if available.success and isinstance(available.response, list):
            names = [str(item) for item in available.response]
            # N.I.N.A. usually lists JSON sequences by stem and templates with their path.
            matched_name = next(
                (candidate for candidate in candidates if candidate in names), ""
            )
            if matched_name:
                break
        _sleep_between_api_retries(attempt)

    if matched_name:
        load_name = matched_name
    elif available and available.success:
        preview = ", ".join(names[:12]) or "none"
        return NinaApiLoadResult(
            False,
            str(sequence),
            sequence_name=load_name,
            method="GET /sequence/load?sequenceName=...",
            message=(
                f"Copied sequence to {copied_path}, but N.I.N.A. API does not list it yet. "
                f"Set CONFIG → N.I.N.A. sequence folder to the same folder used by N.I.N.A. Advanced Sequencer. "
                f"Visible sequences: {preview}"
            ),
        )
    elif available and not available.success:
        return NinaApiLoadResult(
            False,
            str(sequence),
            sequence_name=load_name,
            method="GET /sequence/load?sequenceName=...",
            message=f"Could not read N.I.N.A. API sequence list after copying the plan: {available.message}",
        )

    loaded = None
    for attempt in range(12):
        loaded = load_sequence_by_name(load_name, data)
        if loaded.success:
            break
        if not _api_message_is_transient_initialization(loaded.message):
            break
        _sleep_between_api_retries(attempt)
    if not loaded or not loaded.success:
        return NinaApiLoadResult(
            False,
            str(sequence),
            sequence_name=load_name,
            method="GET /sequence/load?sequenceName=...",
            message=f"N.I.N.A. API load failed after waiting for initialization: {loaded.message if loaded else 'no response'}",
        )

    state = None
    for attempt in range(8):
        state = get_sequence_state(data)
        if state.success:
            break
        if not _api_message_is_transient_initialization(state.message):
            break
        _sleep_between_api_retries(attempt)
    return NinaApiLoadResult(
        bool(state and state.success),
        str(sequence),
        sequence_name=load_name,
        method="GET /sequence/load?sequenceName=...",
        message=(
            "Sequence loaded into N.I.N.A. API."
            if state and state.success
            else f"Loaded response succeeded, but state check failed after waiting: {state.message if state else 'no response'}"
        ),
        state=state.raw if state else None,
    )


def _normalize_version_parts(version: str) -> tuple[int, ...]:
    raw = str(version or "").strip().lower().lstrip("v")
    parts = [int(part) for part in re.findall(r"\d+", raw)[:4]]
    return tuple(parts or [0])


def is_newer_version(candidate: str, current: str) -> bool:
    if not str(current or "").strip():
        return bool(str(candidate or "").strip())
    return _normalize_version_parts(candidate) > _normalize_version_parts(current)


def _read_url_json(url: str, timeout: float = 10.0) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "FZAstroAI-Imaging-Updater/1.0",
        },
    )
    with urllib.request.urlopen(
        request, timeout=timeout
    ) as response:  # noqa: S310 - user-configured URL
        payload = response.read(5_000_000)
    data = json.loads(payload.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Update feed did not return a JSON object.")
    return data


def _asset_download_url(assets: list[Any]) -> str:
    preferred_extensions = (".exe", ".msi", ".zip")
    for extension in preferred_extensions:
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name") or "").lower()
            if name.endswith(extension):
                return str(asset.get("browser_download_url") or "").strip()
    return ""


def _update_info_from_json(
    data: dict[str, Any], *, source_url: str, current_version: str
) -> NinaUpdateInfo:
    version = str(
        data.get("version")
        or data.get("tag_name")
        or data.get("name")
        or data.get("release")
        or ""
    ).strip()
    assets = data.get("assets") if isinstance(data.get("assets"), list) else []
    download_url = str(
        data.get("download_url")
        or data.get("installer_url")
        or data.get("asset_url")
        or _asset_download_url(assets)
        or ""
    ).strip()
    release_notes = str(
        data.get("release_notes") or data.get("body") or data.get("notes") or ""
    ).strip()
    sha256 = str(data.get("sha256") or data.get("checksum") or "").strip()
    published_at = str(data.get("published_at") or data.get("date") or "").strip()
    return NinaUpdateInfo(
        version=version,
        download_url=download_url,
        release_notes=release_notes,
        sha256=sha256,
        published_at=published_at,
        source_url=source_url,
        current_version=current_version,
        is_newer=is_newer_version(version, current_version),
    )


def check_for_update(
    settings: dict[str, Any] | None = None,
    *,
    manifest_url: str | None = None,
    current_version: str | None = None,
    timeout: float = 10.0,
) -> NinaUpdateInfo | None:
    data = _settings_from_mapping(settings)
    feed_url = str(
        manifest_url
        if manifest_url is not None
        else data.get("update_manifest_url") or ""
    ).strip()
    if not feed_url:
        return None
    installed_version = str(
        current_version
        if current_version is not None
        else data.get("installed_version") or ""
    ).strip()
    try:
        payload = _read_url_json(feed_url, timeout=timeout)
        return _update_info_from_json(
            payload,
            source_url=feed_url,
            current_version=installed_version,
        )
    except (
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        log_warning("nina_bridge.check_for_update", exc)
        raise
    except Exception as exc:
        log_exception("nina_bridge.check_for_update", exc)
        raise


def _filename_from_url(url: str) -> str:
    name = Path(urllib.parse.urlparse(url).path).name
    if not name:
        name = f"FZAstroImagingUpdate-{int(time.time())}.download"
    return re.sub(r"[^A-Za-z0-9._ -]", "_", name)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_update(
    info: NinaUpdateInfo,
    destination_dir: Path | None = None,
    *,
    timeout: float = 60.0,
) -> Path:
    if not info.download_url:
        raise ValueError("No download URL is available for this update.")
    target_dir = Path(destination_dir or UPDATE_DOWNLOAD_DIR)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / _filename_from_url(info.download_url)
    request = urllib.request.Request(
        info.download_url,
        headers={"User-Agent": "FZAstroAI-Imaging-Updater/1.0"},
    )
    with urllib.request.urlopen(
        request, timeout=timeout
    ) as response:  # noqa: S310 - user-confirmed URL
        with target_path.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
    if info.sha256:
        actual = _sha256(target_path).lower()
        expected = info.sha256.strip().lower()
        if actual != expected:
            try:
                target_path.unlink()
            except Exception:
                pass
            raise ValueError("Downloaded update checksum did not match the manifest.")
    return target_path
