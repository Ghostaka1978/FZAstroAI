from __future__ import annotations

import math
import os
import sys
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import APP_DIR

AU_LIGHT_MINUTES = 8.316746397269274
PACKAGE_SKYFIELD_DIR = Path(__file__).resolve().parent / "fzastro" / ".skyfield"
EPHEMERIS_FILE = "de440s.bsp"


class _NullTextStream:
    """Tiny text stream used when Windows GUI builds expose no stdout/stderr."""

    def write(self, _text: object) -> int:
        return 0

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return False


@contextmanager
def _safe_skyfield_stdio():
    """Protect Skyfield downloads from PyInstaller windowed-mode null stdio.

    Windows GUI executables commonly run with ``sys.stdout``/``sys.stderr`` set
    to ``None``. Some Skyfield download paths still call ``flush()`` on those
    streams while fetching an ephemeris, which turns a normal download into the
    user-facing ``'NoneType' object has no attribute 'flush'`` Solar Map error.
    Use a local null stream only for the ephemeris load/download window.
    """

    previous_stdout = sys.stdout
    previous_stderr = sys.stderr
    null_stream = _NullTextStream()
    changed_stdout = previous_stdout is None
    changed_stderr = previous_stderr is None
    if changed_stdout:
        sys.stdout = null_stream  # type: ignore[assignment]
    if changed_stderr:
        sys.stderr = null_stream  # type: ignore[assignment]
    try:
        yield
    finally:
        if changed_stdout:
            sys.stdout = previous_stdout  # type: ignore[assignment]
        if changed_stderr:
            sys.stderr = previous_stderr  # type: ignore[assignment]


@dataclass(frozen=True)
class SolarBodyDefinition:
    name: str
    ephemeris_key: str
    color: str
    marker_radius: float
    semi_major_au: float
    eccentricity: float
    category: str


SOLAR_BODIES: tuple[SolarBodyDefinition, ...] = (
    SolarBodyDefinition(
        "Mercury", "mercury barycenter", "#c9c9c9", 4.8, 0.387098, 0.2056, "inner"
    ),
    SolarBodyDefinition(
        "Venus", "venus barycenter", "#eac14d", 6.6, 0.723332, 0.0068, "inner"
    ),
    SolarBodyDefinition(
        "Earth", "earth barycenter", "#0094ff", 7.0, 1.000000, 0.0167, "inner"
    ),
    SolarBodyDefinition(
        "Mars", "mars barycenter", "#e74c3c", 5.6, 1.523679, 0.0934, "inner"
    ),
    SolarBodyDefinition(
        "Jupiter", "jupiter barycenter", "#d2a679", 12.8, 5.20260, 0.0489, "outer"
    ),
    SolarBodyDefinition(
        "Saturn", "saturn barycenter", "#f5c982", 11.8, 9.5549, 0.0565, "outer"
    ),
    SolarBodyDefinition(
        "Uranus", "uranus barycenter", "#8ed7e9", 9.0, 19.2184, 0.0463, "outer"
    ),
    SolarBodyDefinition(
        "Neptune", "neptune barycenter", "#4f75ff", 9.0, 30.1104, 0.0097, "outer"
    ),
)


@dataclass(frozen=True)
class SolarBodyPosition:
    name: str
    category: str
    color: str
    marker_radius: float
    x_au: float
    y_au: float
    z_au: float
    sun_distance_au: float
    earth_distance_au: float
    earth_light_minutes: float
    ecliptic_lon_deg: float
    ecliptic_lat_deg: float
    semi_major_au: float
    eccentricity: float


def _skyfield_data_dir() -> Path:
    configured = os.environ.get("FZASTRO_SKYFIELD_DIR")
    if configured:
        return Path(configured)

    app_cache = APP_DIR / "skyfield"
    if (app_cache / EPHEMERIS_FILE).exists():
        return app_cache
    if (PACKAGE_SKYFIELD_DIR / EPHEMERIS_FILE).exists():
        return PACKAGE_SKYFIELD_DIR
    return app_cache


def _parse_datetime_utc(value: str | None) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        return datetime.now(timezone.utc).replace(microsecond=0)

    try:
        if raw.endswith("Z"):
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        else:
            parsed = datetime.fromisoformat(raw)
    except Exception:
        return datetime.now(timezone.utc).replace(microsecond=0)

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def _orbit_samples_for_body(
    body: SolarBodyDefinition,
    current_x_au: float,
    current_y_au: float,
    samples: int = 360,
) -> list[tuple[float, float]]:
    """Return focus-at-Sun 2D orbit samples rotated through the current body angle."""
    sma = float(body.semi_major_au)
    ecc = float(body.eccentricity)
    current_radius = max(math.hypot(current_x_au, current_y_au), 1e-9)
    current_angle = math.atan2(current_y_au, current_x_au)

    if ecc > 1e-6:
        cos_true = (sma * (1.0 - ecc * ecc) / current_radius - 1.0) / ecc
        cos_true = max(-1.0, min(1.0, cos_true))
        true_anomaly = math.acos(cos_true)
        if math.copysign(1.0, math.sin(current_angle) or 1.0) != math.copysign(
            1.0, math.sin(true_anomaly) or 1.0
        ):
            true_anomaly = -true_anomaly
        rotation = current_angle - true_anomaly
    else:
        rotation = current_angle

    points: list[tuple[float, float]] = []
    for index in range(samples + 1):
        theta = 2.0 * math.pi * (index / max(samples, 1))
        radius = sma * (1.0 - ecc * ecc) / (1.0 + ecc * math.cos(theta))
        points.append(
            (radius * math.cos(theta + rotation), radius * math.sin(theta + rotation))
        )
    return points


def _load_skyfield_snapshot(dt_utc: datetime) -> dict[str, Any]:
    from skyfield.api import Loader
    from skyfield.framelib import ecliptic_frame

    data_dir = _skyfield_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    loader = Loader(str(data_dir), verbose=False)
    with _safe_skyfield_stdio():
        timescale = loader.timescale()
        time = timescale.from_datetime(dt_utc)
        ephemeris = loader(EPHEMERIS_FILE)
    sun = ephemeris["sun"]
    earth = ephemeris["earth barycenter"]

    bodies: list[SolarBodyPosition] = []
    orbits: dict[str, list[tuple[float, float]]] = {}

    for body in SOLAR_BODIES:
        heliocentric = (ephemeris[body.ephemeris_key] - sun).at(time)
        x_au, y_au, z_au = heliocentric.frame_xyz(ecliptic_frame).au
        x = float(x_au)
        y = float(y_au)
        z = float(z_au)

        geocentric = (ephemeris[body.ephemeris_key] - earth).at(time)
        gx_au, gy_au, gz_au = geocentric.frame_xyz(ecliptic_frame).au
        earth_distance = math.sqrt(
            float(gx_au) ** 2 + float(gy_au) ** 2 + float(gz_au) ** 2
        )
        sun_distance = math.sqrt(x * x + y * y + z * z)
        lon = math.degrees(math.atan2(y, x)) % 360.0
        lat = math.degrees(math.atan2(z, max(math.hypot(x, y), 1e-12)))

        bodies.append(
            SolarBodyPosition(
                name=body.name,
                category=body.category,
                color=body.color,
                marker_radius=body.marker_radius,
                x_au=x,
                y_au=y,
                z_au=z,
                sun_distance_au=sun_distance,
                earth_distance_au=earth_distance,
                earth_light_minutes=earth_distance * AU_LIGHT_MINUTES,
                ecliptic_lon_deg=lon,
                ecliptic_lat_deg=lat,
                semi_major_au=body.semi_major_au,
                eccentricity=body.eccentricity,
            )
        )
        orbits[body.name] = _orbit_samples_for_body(body, x, y)

    return {
        "timestamp_utc": dt_utc.isoformat().replace("+00:00", "Z"),
        "generated_at_utc": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "source": "Skyfield de440s.bsp",
        "units": "AU",
        "data_dir": str(data_dir),
        "bodies": [asdict(body) for body in bodies],
        "orbits": {
            name: [[float(x), float(y)] for x, y in points]
            for name, points in orbits.items()
        },
    }


def load_solar_map_snapshot(dt_iso: str | None = None) -> dict[str, Any]:
    """Calculate current heliocentric planet positions for the native Qt solar map."""
    dt_utc = _parse_datetime_utc(dt_iso)
    return _load_skyfield_snapshot(dt_utc)
