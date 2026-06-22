from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from PySide6.QtCore import QThread, Signal

from ..config import APP_DIR
from ..json_store import atomic_write_json
from ..logging_utils import log_debug, log_exception, log_warning
from ..network_utils import get_limited_json, get_limited_response

SUN_NOW_CACHE_DIR = APP_DIR / "sun_now"
SDO_LATEST_BASE_URL = "https://sdo.gsfc.nasa.gov/assets/img/latest"
HELIOVIEWER_CLOSEST_IMAGE_URL = "https://api.helioviewer.org/v1/getClosestImage/"
REQUEST_HEADERS = {
    "User-Agent": "FZAstroAI/1.0 SUN-NOW (+https://github.com/Ghostaka1978/FZAstroAI)",
}


@dataclass(frozen=True)
class SunNowChannel:
    key: str
    label: str
    image_code: str
    observatory: str
    instrument: str
    detector: str
    measurement: str
    description: str
    interpretation: str

    def image_url(self, resolution: int) -> str:
        safe_resolution = max(512, min(4096, int(resolution)))
        return f"{SDO_LATEST_BASE_URL}/latest_{safe_resolution}_{self.image_code}.jpg"


SUN_NOW_CHANNELS: tuple[SunNowChannel, ...] = (
    SunNowChannel(
        key="aia_0171",
        label="AIA 171 Å · corona loops",
        image_code="0171",
        observatory="SDO",
        instrument="AIA",
        detector="AIA",
        measurement="171",
        description="Extreme ultraviolet view of the quiet corona and magnetic loops.",
        interpretation="Best for coronal loops, active-region structure, and quiet corona context.",
    ),
    SunNowChannel(
        key="aia_0193",
        label="AIA 193 Å · corona / flares",
        image_code="0193",
        observatory="SDO",
        instrument="AIA",
        detector="AIA",
        measurement="193",
        description="Extreme ultraviolet view of hot coronal plasma and active regions.",
        interpretation="Good default for coronal holes, active regions, and flare-hot plasma context.",
    ),
    SunNowChannel(
        key="aia_0211",
        label="AIA 211 Å · active regions",
        image_code="0211",
        observatory="SDO",
        instrument="AIA",
        detector="AIA",
        measurement="211",
        description="Extreme ultraviolet view of warmer coronal plasma.",
        interpretation="Useful for bright active-region arcades and coronal-hole contrast.",
    ),
    SunNowChannel(
        key="aia_0304",
        label="AIA 304 Å · prominences",
        image_code="0304",
        observatory="SDO",
        instrument="AIA",
        detector="AIA",
        measurement="304",
        description="Extreme ultraviolet chromosphere and transition-region view.",
        interpretation="Best for prominences, filaments, limb activity, and eruptive material.",
    ),
    SunNowChannel(
        key="aia_0335",
        label="AIA 335 Å · hot corona",
        image_code="0335",
        observatory="SDO",
        instrument="AIA",
        detector="AIA",
        measurement="335",
        description="Extreme ultraviolet hot-corona channel.",
        interpretation="Useful for hot active-region loops and post-flare coronal structure.",
    ),
    SunNowChannel(
        key="aia_0094",
        label="AIA 94 Å · flare plasma",
        image_code="0094",
        observatory="SDO",
        instrument="AIA",
        detector="AIA",
        measurement="94",
        description="Extreme ultraviolet high-temperature flare-sensitive channel.",
        interpretation="Best for very hot flare plasma and compact active-region cores.",
    ),
    SunNowChannel(
        key="aia_0131",
        label="AIA 131 Å · flares",
        image_code="0131",
        observatory="SDO",
        instrument="AIA",
        detector="AIA",
        measurement="131",
        description="Extreme ultraviolet flare-sensitive channel.",
        interpretation="Useful for flare loops, eruptions, and very hot coronal plasma.",
    ),
    SunNowChannel(
        key="aia_1600",
        label="AIA 1600 Å · lower atmosphere",
        image_code="1600",
        observatory="SDO",
        instrument="AIA",
        detector="AIA",
        measurement="1600",
        description="Ultraviolet lower-atmosphere and transition-region view.",
        interpretation="Useful for flare ribbons and photosphere/chromosphere transition context.",
    ),
    SunNowChannel(
        key="hmi_mag",
        label="HMI magnetogram · magnetic field",
        image_code="HMIB",
        observatory="SDO",
        instrument="HMI",
        detector="HMI",
        measurement="magnetogram",
        description="Photospheric line-of-sight magnetic-field quick-look map.",
        interpretation="White/black polarity patterns show magnetic complexity around active regions.",
    ),
    SunNowChannel(
        key="hmi_mag_color",
        label="HMI color magnetogram",
        image_code="HMIBC",
        observatory="SDO",
        instrument="HMI",
        detector="HMI",
        measurement="magnetogram",
        description="Colorized quick-look photospheric magnetic-field map.",
        interpretation="Color helps separate strong positive and negative magnetic polarity zones.",
    ),
    SunNowChannel(
        key="hmi_continuum",
        label="HMI continuum · sunspots",
        image_code="HMII",
        observatory="SDO",
        instrument="HMI",
        detector="HMI",
        measurement="continuum",
        description="Visible-light photosphere quick-look image.",
        interpretation="Best for sunspot groups and white-light photospheric structure.",
    ),
    SunNowChannel(
        key="hmi_doppler",
        label="HMI dopplergram",
        image_code="HMID",
        observatory="SDO",
        instrument="HMI",
        detector="HMI",
        measurement="dopplergram",
        description="Photospheric Doppler velocity quick-look map.",
        interpretation="Shows line-of-sight motion patterns across the solar photosphere.",
    ),
)

SUN_NOW_CHANNEL_BY_KEY = {channel.key: channel for channel in SUN_NOW_CHANNELS}
SUN_NOW_RESOLUTIONS = (1024, 2048, 512)


def normalise_sun_channel(value: str | None) -> SunNowChannel:
    key = str(value or "").strip()
    return SUN_NOW_CHANNEL_BY_KEY.get(key, SUN_NOW_CHANNELS[0])


def normalise_sun_resolution(value: Any) -> int:
    try:
        resolution = int(value)
    except Exception:
        resolution = 1024
    if resolution not in SUN_NOW_RESOLUTIONS:
        resolution = 1024
    return resolution


def _safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "")).strip("_") or "sun"


def _header_timestamp(headers: Any) -> str:
    for key in ("Last-Modified", "Date"):
        value = str(headers.get(key, "") or "").strip()
        if value:
            return value
    return ""


def _utc_now_for_helioviewer() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _cached_image_path(channel: SunNowChannel, resolution: int) -> Path:
    return SUN_NOW_CACHE_DIR / f"{_safe_filename(channel.key)}_{int(resolution)}.jpg"


def _metadata_path(channel: SunNowChannel, resolution: int) -> Path:
    return SUN_NOW_CACHE_DIR / f"{_safe_filename(channel.key)}_{int(resolution)}.json"


def _load_cached_metadata(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return data
    except Exception as exc:
        log_debug("SunNowWorker cache metadata load skipped", exc)
    return {}


def _write_json(path: Path, payload: dict[str, Any]):
    atomic_write_json(path, payload, indent=2)


def _fetch_helioviewer_metadata(channel: SunNowChannel) -> dict[str, Any]:
    query = urlencode(
        {
            "date": _utc_now_for_helioviewer(),
            "observatory": channel.observatory,
            "instrument": channel.instrument,
            "detector": channel.detector,
            "measurement": channel.measurement,
        }
    )
    url = f"{HELIOVIEWER_CLOSEST_IMAGE_URL}?{query}"
    try:
        payload = get_limited_json(
            url,
            max_bytes=128 * 1024,
            timeout=12,
            headers=REQUEST_HEADERS,
        )
        if isinstance(payload, dict):
            return payload
    except Exception as exc:
        log_debug("SunNowWorker Helioviewer metadata unavailable", exc)
    return {}


def load_sun_now_image(
    channel_key: str | None = None, resolution: Any = 1024
) -> dict[str, Any]:
    channel = normalise_sun_channel(channel_key)
    image_resolution = normalise_sun_resolution(resolution)
    image_url = channel.image_url(image_resolution)
    cache_path = _cached_image_path(channel, image_resolution)
    metadata_file = _metadata_path(channel, image_resolution)
    cache_metadata = _load_cached_metadata(metadata_file)

    result: dict[str, Any] = {
        "channel_key": channel.key,
        "label": channel.label,
        "observatory": channel.observatory,
        "instrument": channel.instrument,
        "detector": channel.detector,
        "measurement": channel.measurement,
        "description": channel.description,
        "interpretation": channel.interpretation,
        "resolution": image_resolution,
        "source": "NASA/SDO latest image",
        "source_url": image_url,
        "image_path": str(cache_path),
        "cache_used": False,
        "bytes": 0,
        "last_modified": "",
        "helioviewer_date": "",
        "helioviewer_id": "",
        "status_note": "",
    }

    helioviewer_payload = _fetch_helioviewer_metadata(channel)
    if helioviewer_payload:
        result["helioviewer_date"] = str(helioviewer_payload.get("date") or "")
        result["helioviewer_id"] = str(helioviewer_payload.get("id") or "")

    try:
        response, body = get_limited_response(
            image_url,
            max_bytes=20 * 1024 * 1024,
            timeout=25,
            headers=REQUEST_HEADERS,
        )
        if not body:
            raise ValueError("NASA/SDO returned an empty image")

        SUN_NOW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
        tmp_path.write_bytes(body)
        tmp_path.replace(cache_path)

        result["bytes"] = len(body)
        result["last_modified"] = _header_timestamp(response.headers)
        if not result["last_modified"]:
            result["last_modified"] = cache_metadata.get("last_modified", "")
        result["status_note"] = "Fresh NASA/SDO image loaded."
        _write_json(metadata_file, result)
        return result
    except Exception as exc:
        log_warning("SunNowWorker NASA/SDO image fetch failed", exc)
        if cache_path.exists() and cache_path.stat().st_size > 0:
            result.update(cache_metadata)
            result["image_path"] = str(cache_path)
            result["source_url"] = image_url
            result["cache_used"] = True
            result["status_note"] = (
                f"Using cached SUN NOW image because live download failed: {exc}"
            )
            return result
        raise


class SunNowWorker(QThread):
    """Load latest NASA/SDO solar imagery away from the Qt UI thread."""

    finished_sun_now = Signal(dict, float, bool)
    error_received = Signal(str)

    def __init__(self, channel_key: str | None = None, resolution: Any = 1024):
        super().__init__()
        self.channel_key = str(channel_key or "").strip()
        self.resolution = resolution
        self.stop_requested = False

    def stop(self):
        self.stop_requested = True
        try:
            self.requestInterruption()
        except Exception:
            pass

    def should_stop(self) -> bool:
        return bool(self.stop_requested or self.isInterruptionRequested())

    def run(self):
        start = time.perf_counter()
        try:
            if self.should_stop():
                return
            result = load_sun_now_image(self.channel_key, self.resolution)
            if self.should_stop():
                return
            elapsed = max(0.0, time.perf_counter() - start)
            self.finished_sun_now.emit(result, elapsed, True)
        except Exception as error:
            if self.should_stop():
                return
            log_exception("SunNowWorker.run", error)
            self.error_received.emit(str(error))
