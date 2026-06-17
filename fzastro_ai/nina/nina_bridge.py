from __future__ import annotations

import hashlib
import json
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
    """Return the app root for source mode or frozen EXE mode.

    In PyInstaller one-file builds, __file__ points inside the temporary
    _MEI extraction folder. External bundled apps must be resolved beside
    FZAstroAI.exe instead, not inside _MEI.
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
