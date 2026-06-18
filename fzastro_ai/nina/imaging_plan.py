from __future__ import annotations

import csv
import json
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..astro_tools.seeing_data import fetch_7timer_astro_forecast, score_label
from ..astro_tools.target_catalog import load_catalog_rows
from ..config import APP_DIR

from .nina_sequence_template import NinaSequencePlan, save_filled_sequence


def _default_imaging_plan_dir() -> Path:
    """Return a user-visible folder for generated imaging review plans.

    The plan files are intentionally not stored in temp folders or hidden build
    folders.  Documents is easier for users to inspect and for N.I.N.A./FZAstro
    Imaging import/review workflows.
    """

    documents = Path.home() / "Documents"
    try:
        return documents / "FZAstroAI" / "Imaging Plans"
    except Exception:
        return APP_DIR / "imaging_plans"


IMAGING_PLAN_DIR = _default_imaging_plan_dir()
DEFAULT_EXPOSURE_SECONDS = 60
DEFAULT_GAIN = 200
DEFAULT_MIN_ALT_DEG = 45.0
DEFAULT_NINA_MIN_ALT_DEG = 30.0
DEFAULT_TARGET_LIMIT = 12

_SAFE_NATURAL_COMMANDS = {
    "what target should i image next",
    "what target should i image tonight",
    "what target for next time period",
    "what target for the next time period",
    "best target for next time period",
    "best target tonight",
    "plan best target into nina",
    "make a nina plan for best target",
    "create nina plan for best target",
    "create nina plan for next target",
    "make a plan into nina",
    "make imaging plan into nina",
}

_COMMAND_PREFIX_RE = re.compile(
    r"^/(?:nina-plan|nina plan|imaging-plan|imaging plan|astro-plan|astro plan|plan-imaging)\b(?P<body>.*)$",
    re.IGNORECASE,
)

_CATALOG_TARGET_RE = re.compile(
    r"\b(?:(M|MESSIER)\s*([0-9]{1,3})|(NGC|IC)\s*([0-9]{1,5})|BARNARD\s*([0-9]{1,4}))\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PredefinedImagingCommand:
    """A safe, fixed-grammar imaging command parsed from the composer."""

    raw_text: str
    mode: str = "next_best"
    target: str = ""
    exposure_seconds: int = DEFAULT_EXPOSURE_SECONDS
    gain: int = DEFAULT_GAIN
    frames: int = 0
    period: str = "next"
    auto_start_requested: bool = False


@dataclass(frozen=True)
class ImagingWindow:
    start_iso: str
    end_iso: str
    start_label: str
    end_label: str
    score: int
    score_label: str
    cloud_pct: int | None = None
    cloud_text: str = ""
    seeing_text: str = ""
    transparency_text: str = ""
    moon_text: str = ""
    astro_dark: bool = False


@dataclass(frozen=True)
class ImagingPlanResult:
    plan_id: str
    target_name: str
    target_type: str
    ra: str
    dec: str
    magnitude: str
    size: str
    target_grade: int
    exposure_seconds: int
    gain: int
    frames: int
    estimated_total_minutes: int
    window: ImagingWindow
    location: dict[str, Any]
    imaging: dict[str, Any]
    plan_json_path: str
    plan_text_path: str
    nina_review_path: str
    nina_xml_path: str
    nina_csv_path: str
    nina_sequence_path: str
    framing: dict[str, Any] | None = None
    auto_start_requested: bool = False
    review_required: bool = True
    nina_sequence_confirmed: bool = False


def _normalise_text(text: str) -> str:
    clean = str(text or "").casefold().strip()
    clean = clean.replace("-", " ").replace("_", " ")
    clean = re.sub(r"[^a-z0-9/\s]", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def _normalise_target_name(text: str) -> str:
    raw = str(text or "").strip()
    match = _CATALOG_TARGET_RE.search(raw)
    if match:
        if match.group(1):
            return f"M{int(match.group(2))}"
        if match.group(3):
            return f"{match.group(3).upper()} {int(match.group(4))}"
        if match.group(5):
            return f"Barnard {int(match.group(5))}"
    clean = re.sub(r"\s+", " ", raw).strip()
    return clean


def _extract_target(body: str) -> str:
    explicit = re.search(
        r"\btarget\s+(?P<target>.+?)(?=\s+\b(?:gain|frames|subs|lights|exposure|exp|start|tonight|next|tomorrow)\b|\s+\d+\s*(?:s|sec|secs|second|seconds)\b|$)",
        body,
        flags=re.IGNORECASE,
    )
    if explicit:
        return _normalise_target_name(explicit.group("target"))

    catalog_match = _CATALOG_TARGET_RE.search(body)
    if catalog_match:
        return _normalise_target_name(catalog_match.group(0))

    # Accept `/nina-plan Andromeda gain 200` but keep this conservative: only
    # the leading free-text token span before known parameters is treated as a target.
    body_clean = str(body or "").strip()
    body_clean = re.sub(r"^for\s+", "", body_clean, flags=re.IGNORECASE).strip()
    body_clean = re.split(
        r"\s+\b(?:gain|frames|subs|lights|exposure|exp|start|tonight|next|tomorrow|auto|run|schedule)\b|\s+\d+\s*(?:s|sec|secs|second|seconds)\b",
        body_clean,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    if body_clean.casefold() in {"", "next", "tonight", "best", "best target"}:
        return ""
    if len(body_clean.split()) <= 4:
        return _normalise_target_name(body_clean)
    return ""


def parse_predefined_imaging_command(text: str) -> PredefinedImagingCommand | None:
    """Parse only fixed, safe imaging-plan commands.

    The parser deliberately does not understand arbitrary automation language.
    It creates review-only plans and records if the user asked for auto-start so
    the UI can explicitly refuse silent hardware execution.
    """

    raw = str(text or "").strip()
    if not raw:
        return None

    prefix_match = _COMMAND_PREFIX_RE.match(raw)
    clean = _normalise_text(raw)

    if prefix_match:
        body = prefix_match.group("body").strip()
    elif clean in _SAFE_NATURAL_COMMANDS:
        body = clean
    else:
        return None

    lower_body = body.casefold()
    exposure = DEFAULT_EXPOSURE_SECONDS
    exposure_match = re.search(
        r"(?:\bexposure\b|\bexp\b)?\s*(?P<seconds>\d{1,5})\s*(?:s|sec|secs|second|seconds)\b",
        body,
        flags=re.IGNORECASE,
    )
    if exposure_match:
        exposure = max(1, min(24 * 3600, int(exposure_match.group("seconds"))))

    gain = DEFAULT_GAIN
    gain_match = re.search(r"\bgain\s*(?P<gain>\d{1,5})\b", body, re.IGNORECASE)
    if gain_match:
        gain = max(0, min(10000, int(gain_match.group("gain"))))

    frames = 0
    frames_match = re.search(
        r"\b(?:frames|subs|lights)\s*(?P<frames>\d{1,5})\b",
        body,
        flags=re.IGNORECASE,
    )
    if frames_match:
        frames = max(1, min(10000, int(frames_match.group("frames"))))

    target = _extract_target(body)
    period = "tomorrow" if "tomorrow" in lower_body else "tonight"
    if "next" in lower_body or not target:
        period = "next"

    auto_start_requested = bool(
        re.search(r"\b(auto|automatic|automatically|run|start|schedule)\b", body, re.I)
    )

    mode = "target" if target else "next_best"
    return PredefinedImagingCommand(
        raw_text=raw,
        mode=mode,
        target=target,
        exposure_seconds=exposure,
        gain=gain,
        frames=frames,
        period=period,
        auto_start_requested=auto_start_requested,
    )


def is_predefined_imaging_command(text: str) -> bool:
    return parse_predefined_imaging_command(text) is not None


def _safe_zone(tz_name: Any) -> ZoneInfo:
    try:
        return ZoneInfo(str(tz_name or "UTC").strip() or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def _parse_dt(value: Any, tz_name: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_safe_zone(tz_name))
        return parsed.astimezone(_safe_zone(tz_name))
    except Exception:
        return None


def _float_value(value: Any, default: float = 90.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _is_twilight_window_row(row: dict[str, Any]) -> bool:
    if row.get("astro_dark") is True:
        return False
    return _float_value(row.get("sun_altitude_deg"), 90.0) < -6.0


def choose_best_seeing_window(
    forecast: dict[str, Any], *, now: datetime | None = None
) -> ImagingWindow:
    rows = forecast.get("rows") if isinstance(forecast, dict) else []
    if not isinstance(rows, list) or not rows:
        raise ValueError("SEEING forecast has no usable rows.")

    tz_name = str(forecast.get("tz") or "UTC")
    zone = _safe_zone(tz_name)
    now_local = (now or datetime.now(zone)).astimezone(zone)

    parsed_rows: list[tuple[dict[str, Any], datetime]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        local_dt = _parse_dt(row.get("local_iso") or row.get("local_label"), tz_name)
        if local_dt is None:
            continue
        parsed_rows.append((row, local_dt))

    if not parsed_rows:
        raise ValueError("SEEING forecast rows did not contain usable times.")

    future_rows = [
        (row, dt) for row, dt in parsed_rows if dt >= now_local - timedelta(minutes=30)
    ]
    candidates = future_rows or parsed_rows
    dark_candidates = [
        (row, dt) for row, dt in candidates if row.get("astro_dark") is True
    ]
    twilight_candidates = [
        (row, dt) for row, dt in candidates if _is_twilight_window_row(row)
    ]
    candidates = dark_candidates or twilight_candidates or candidates

    row, start = max(
        candidates,
        key=lambda item: (
            int(item[0].get("score") or 0),
            bool(item[0].get("astro_dark") is True),
            -abs((item[1] - now_local).total_seconds()) / 3600.0,
        ),
    )

    later_times = sorted(dt for _row, dt in parsed_rows if dt > start)
    end = later_times[0] if later_times else start + timedelta(hours=3)
    if end <= start:
        end = start + timedelta(hours=3)

    cloud_pct = row.get("cloud_mid_pct")
    try:
        cloud_pct_value = int(cloud_pct) if cloud_pct is not None else None
    except Exception:
        cloud_pct_value = None

    score = int(row.get("score") or 0)
    return ImagingWindow(
        start_iso=start.isoformat(),
        end_iso=end.isoformat(),
        start_label=start.strftime("%Y-%m-%d %H:%M"),
        end_label=end.strftime("%Y-%m-%d %H:%M"),
        score=score,
        score_label=str(row.get("score_label") or score_label(score)),
        cloud_pct=cloud_pct_value,
        cloud_text=str(row.get("cloud_text") or ""),
        seeing_text=str(row.get("seeing_text") or ""),
        transparency_text=str(row.get("transparency_text") or ""),
        moon_text=str(row.get("moon_text") or ""),
        astro_dark=bool(row.get("astro_dark") is True),
    )


def _target_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _catalog_target(query: str) -> dict[str, Any]:
    wanted = _target_key(_normalise_target_name(query))
    if not wanted:
        return {}
    for row in load_catalog_rows(source="auto"):
        name = str(row[0] or "")
        if _target_key(name) == wanted:
            return {
                "name": name,
                "type": str(row[1] or ""),
                "const": str(row[2] or ""),
                "ra": str(row[3] or ""),
                "dec": str(row[4] or ""),
                "mag": "" if row[5] is None else str(row[5]),
                "size": str(row[6] or ""),
                "grade": 0,
            }
    return {
        "name": _normalise_target_name(query),
        "type": "Manual target",
        "const": "",
        "ra": "",
        "dec": "",
        "mag": "",
        "size": "",
        "grade": 0,
    }


def _selected_target_from_pick(pick: dict[str, Any]) -> dict[str, Any]:
    """Normalize a TARGETS row selected by the user for imaging-plan generation.

    The TARGETS -> Imaging Control workflow must not re-query or re-rank the
    target catalog after the user has selected a row.  This preserves the exact
    object the user reviewed in TARGETS, while the planner still evaluates the
    best structured SEEING window for that confirmed target.
    """

    data = dict(pick or {})
    name = str(data.get("name") or data.get("target_name") or "").strip()
    if not name:
        raise ValueError("Selected TARGETS handoff did not include a target name.")
    return {
        "name": name,
        "type": str(data.get("type") or data.get("target_type") or ""),
        "const": str(data.get("const") or data.get("constellation") or ""),
        "ra": str(data.get("ra") or data.get("ra_text") or ""),
        "dec": str(data.get("dec") or data.get("dec_text") or ""),
        "mag": "" if data.get("mag") is None else str(data.get("mag")),
        "size": str(data.get("size") or data.get("apparent_size") or ""),
        "grade": int(data.get("grade") or 0),
    }


_PRACTICAL_TARGET_TYPES = {
    "galaxy": 22,
    "galaxies": 22,
    "globular": 24,
    "globularcluster": 24,
    "globularclusterinmilkyway": 24,
    "opencluster": 18,
    "cluster": 16,
    "nebula": 22,
    "emissionnebula": 24,
    "reflectionnebula": 20,
    "darknebula": 16,
    "planetarynebula": 18,
    "supernovaremnant": 16,
}

_LOW_VALUE_TARGET_TYPES = {
    "other",
    "unknown",
    "star",
    "stars",
    "doublestar",
    "asterism",
    "associationofstars",
}


def _compact_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _catalog_name_bonus(name: Any) -> int:
    text = str(name or "").strip().upper()
    if re.match(r"^M\s*\d+\b", text) or re.match(r"^MESSIER\s+\d+\b", text):
        return 18
    if re.match(r"^NGC\s*\d+\b", text):
        return 9
    if re.match(r"^IC\s*\d+\b", text):
        return 2
    if re.match(r"^BARNARD\s*\d+\b", text):
        return 4
    return 0


def _parse_magnitude(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except Exception:
        return None


def _parse_size_arcmin(value: Any) -> float | None:
    text = (
        str(value or "").strip().replace("′", "'").replace("’", "'").replace("″", '"')
    )
    if not text:
        return None
    match = re.search(
        r"(\d+(?:\.\d+)?)\s*(°|deg|d|'|arcmin|m|\"|arcsec|s)?", text, re.I
    )
    if not match:
        return None
    try:
        amount = float(match.group(1))
    except Exception:
        return None
    unit = (match.group(2) or "").casefold()
    if unit in {"°", "deg", "d"}:
        return amount * 60.0
    if unit in {'"', "arcsec", "s"}:
        return amount / 60.0
    return amount


def _practical_target_bonus(pick: dict[str, Any]) -> int:
    """Score how useful a target is for an automatic imaging recommendation.

    The TARGETS planner should still use the AUTO catalog source, but AUTO can
    contain many tiny or poorly classified OpenNGC/IC objects.  This bonus keeps
    the big catalog available while making `/nina-plan next` prefer practical
    astrophotography targets over obscure `Other` entries when the geometric
    grades are similar.
    """

    bonus = _catalog_name_bonus(pick.get("name"))
    compact_type = _compact_text(pick.get("type"))

    if compact_type in _PRACTICAL_TARGET_TYPES:
        bonus += _PRACTICAL_TARGET_TYPES[compact_type]
    elif compact_type in _LOW_VALUE_TARGET_TYPES or not compact_type:
        bonus -= 35
    elif any(word in compact_type for word in ("galaxy", "nebula", "cluster")):
        bonus += 14
    else:
        bonus -= 10

    size_arcmin = _parse_size_arcmin(pick.get("size"))
    if size_arcmin is None:
        bonus -= 4
    elif size_arcmin < 2.0:
        bonus -= 16
    elif size_arcmin < 5.0:
        bonus -= 6
    elif size_arcmin <= 120.0:
        bonus += 8
    else:
        bonus += 3

    mag = _parse_magnitude(pick.get("mag"))
    if mag is not None:
        if mag <= 8.0:
            bonus += 8
        elif mag <= 11.5:
            bonus += 3
        elif mag > 14.0:
            bonus -= 10

    return bonus


def _choose_target(
    command: PredefinedImagingCommand,
    targets_result: dict[str, Any],
    window: ImagingWindow,
) -> dict[str, Any]:
    if command.target:
        return _catalog_target(command.target)

    picks = targets_result.get("picks") if isinstance(targets_result, dict) else []
    if not isinstance(picks, list) or not picks:
        raise ValueError("TARGETS planner returned no usable target picks.")

    tz_name = str(targets_result.get("location", {}).get("tz") or "UTC")
    window_start = _parse_dt(window.start_iso, tz_name)

    def rank(pick: dict[str, Any]) -> tuple[int, int, float]:
        grade = int(pick.get("grade") or 0)
        practical_bonus = _practical_target_bonus(pick)
        best = _parse_dt(pick.get("best_time_local"), tz_name)
        if window_start is not None and best is not None:
            delta = abs((best - window_start).total_seconds()) / 60.0
        else:
            delta = 99999.0

        # Primary sort is a practical imaging score.  Keep the original TARGETS
        # grade as the second key so AUTO still benefits from precise visibility
        # calculations, but does not blindly choose tiny/unknown catalog entries.
        practical_score = grade + practical_bonus
        return (practical_score, grade, -delta)

    usable_picks = [p for p in picks if isinstance(p, dict)]
    best_pick = max(usable_picks, key=rank)
    return {
        "name": str(best_pick.get("name") or "Best target"),
        "type": str(best_pick.get("type") or ""),
        "const": str(best_pick.get("const") or ""),
        "ra": str(best_pick.get("ra") or ""),
        "dec": str(best_pick.get("dec") or ""),
        "mag": "" if best_pick.get("mag") is None else str(best_pick.get("mag")),
        "size": str(best_pick.get("size") or ""),
        "grade": int(best_pick.get("grade") or 0),
    }


def _float_from_mapping(
    data: dict[str, Any], keys: tuple[str, ...], default: float
) -> float:
    for key in keys:
        try:
            value = data.get(key)
        except Exception:
            continue
        if value in (None, ""):
            continue
        try:
            return float(value)
        except Exception:
            continue
    return float(default)


def _camera_sensor_dimensions(
    imaging: dict[str, Any],
) -> tuple[float, float, int, int, float]:
    sensor_width = _float_from_mapping(
        imaging, ("sensor_width_mm", "sensor_width"), 11.2
    )
    native_width = int(_float_from_mapping(imaging, ("native_width", "width"), 3840.0))
    native_height = int(
        _float_from_mapping(imaging, ("native_height", "height"), 2160.0)
    )
    aspect = native_height / max(1, native_width)
    sensor_height = _float_from_mapping(
        imaging,
        ("sensor_height_mm", "sensor_height"),
        sensor_width * aspect,
    )
    pixel_size_um = _float_from_mapping(
        imaging,
        ("pixel_size_um", "pixel_um", "pixel_size"),
        sensor_width * 1000.0 / max(1, native_width),
    )
    return sensor_width, sensor_height, native_width, native_height, pixel_size_um


def _fit_label(
    target_width_arcmin: float | None, fov_width_deg: float, fov_height_deg: float
) -> str:
    if target_width_arcmin is None or target_width_arcmin <= 0:
        return "unknown"
    smallest_fov_arcmin = min(fov_width_deg, fov_height_deg) * 60.0
    largest_fov_arcmin = max(fov_width_deg, fov_height_deg) * 60.0
    if target_width_arcmin > largest_fov_arcmin * 1.12:
        return "too large"
    if target_width_arcmin > smallest_fov_arcmin * 0.78:
        return "tight"
    if target_width_arcmin < smallest_fov_arcmin * 0.08:
        return "small"
    return "good"


def calculate_framing_details(
    *,
    target_size: Any,
    imaging: dict[str, Any],
    exposure_seconds: int,
    gain: int,
    frames: int,
) -> dict[str, Any]:
    """Calculate safe framing/capture metadata for review before N.I.N.A. export.

    This uses structured TARGETS/LOOKUP metadata plus the IMAGING profile.  It
    deliberately does not parse rendered lookup HTML or SEEING dialog HTML.
    """

    imaging = dict(imaging or {})
    sensor_width, sensor_height, native_width, native_height, pixel_size_um = (
        _camera_sensor_dimensions(imaging)
    )
    focal_mm = _float_from_mapping(imaging, ("focal_mm", "focal_length_mm"), 700.0)
    reducer_factor = _float_from_mapping(
        imaging, ("reducer_factor", "reducer", "barlow_factor"), 1.0
    )
    reducer_factor = max(0.05, min(10.0, reducer_factor))
    effective_focal_mm = max(1.0, focal_mm * reducer_factor)
    fov_width_deg = (
        2.0 * math.atan((sensor_width / 2.0) / effective_focal_mm) * 180.0 / math.pi
    )
    fov_height_deg = (
        2.0 * math.atan((sensor_height / 2.0) / effective_focal_mm) * 180.0 / math.pi
    )
    image_scale = 206.265 * pixel_size_um / effective_focal_mm
    target_arcmin = _parse_size_arcmin(target_size)
    total_minutes = max(1, int((max(1, frames) * max(1, exposure_seconds)) // 60))
    return {
        "camera_model": str(
            imaging.get("preset_name")
            or imaging.get("camera_name")
            or imaging.get("preset")
            or "Camera"
        ),
        "sensor_width_mm": round(sensor_width, 3),
        "sensor_height_mm": round(sensor_height, 3),
        "native_width": int(native_width),
        "native_height": int(native_height),
        "pixel_size_um": round(pixel_size_um, 3),
        "focal_length_mm": round(focal_mm, 2),
        "reducer_factor": round(reducer_factor, 3),
        "effective_focal_length_mm": round(effective_focal_mm, 2),
        "fov_width_deg": round(fov_width_deg, 4),
        "fov_height_deg": round(fov_height_deg, 4),
        "image_scale_arcsec_px": round(image_scale, 3),
        "target_size_arcmin": (
            None if target_arcmin is None else round(target_arcmin, 3)
        ),
        "target_fit": _fit_label(target_arcmin, fov_width_deg, fov_height_deg),
        "exposure_seconds": int(exposure_seconds),
        "gain": int(gain),
        "frames": int(frames),
        "estimated_total_minutes": int(total_minutes),
    }


def _frames_for_window(
    command: PredefinedImagingCommand, window: ImagingWindow
) -> tuple[int, int]:
    start = _parse_dt(window.start_iso, "UTC")
    end = _parse_dt(window.end_iso, "UTC")
    duration_minutes = 180
    if start is not None and end is not None:
        duration_minutes = max(1, int((end - start).total_seconds() // 60))
    if command.frames > 0:
        return command.frames, duration_minutes
    usable_seconds = max(0, duration_minutes * 60 - 10 * 60)
    frames = max(1, int(usable_seconds // max(1, command.exposure_seconds)))
    return min(frames, 500), duration_minutes


def _safe_plan_id(target_name: str, created: datetime) -> str:
    clean_target = re.sub(r"[^A-Za-z0-9_.-]+", "_", target_name).strip("_") or "target"
    return f"{created.strftime('%Y%m%d_%H%M%S')}_{clean_target}"


def _set_xml_child(parent: ET.Element, tag: str, values: dict[str, Any]) -> ET.Element:
    child = ET.SubElement(parent, tag)
    for key, value in values.items():
        child.set(str(key), "" if value is None else str(value))
    return child


def _write_nina_review_xml(path: Path, result: ImagingPlanResult) -> None:
    """Write a N.I.N.A.-friendly XML review/export file.

    This is deliberately a review/import helper, not an instruction to start
    hardware.  It gives FZAstro Imaging/N.I.N.A. users a structured XML file
    with target, sequence, and condition details while preserving the safety
    boundary around slewing/capture.
    """

    root = ET.Element(
        "FZAstroImagingPlan",
        {
            "schema": "fzastro_nina_review_plan_v1",
            "safe_mode": "true",
            "review_required": "true",
            "auto_start": "false",
        },
    )
    _set_xml_child(
        root,
        "Target",
        {
            "name": result.target_name,
            "type": result.target_type,
            "ra": result.ra,
            "dec": result.dec,
            "magnitude": result.magnitude,
            "size": result.size,
            "grade": result.target_grade,
        },
    )
    _set_xml_child(
        root,
        "Sequence",
        {
            "start_time": result.window.start_iso,
            "end_time": result.window.end_iso,
            "exposure_seconds": result.exposure_seconds,
            "gain": result.gain,
            "frames": result.frames,
            "estimated_light_minutes": result.estimated_total_minutes,
        },
    )
    _set_xml_child(
        root,
        "Conditions",
        {
            "seeing_score": result.window.score,
            "seeing_label": result.window.score_label,
            "cloud_pct": result.window.cloud_pct,
            "cloud_text": result.window.cloud_text,
            "seeing_text": result.window.seeing_text,
            "transparency_text": result.window.transparency_text,
            "moon_text": result.window.moon_text,
            "astro_dark": result.window.astro_dark,
        },
    )
    _set_xml_child(
        root,
        "Safety",
        {
            "hardware_actions_executed": "false",
            "note": "Review-only plan. Confirm in FZAstro Imaging/N.I.N.A. before slewing, guiding, capture, or sequence start.",
        },
    )
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)


def _write_nina_review_csv(path: Path, result: ImagingPlanResult) -> None:
    """Write a simple CSV target/sequence review file for spreadsheet/N.I.N.A. workflows."""

    headers = [
        "Name",
        "RA",
        "Dec",
        "Type",
        "Magnitude",
        "Size",
        "Grade",
        "StartTime",
        "EndTime",
        "ExposureSeconds",
        "Gain",
        "Frames",
        "EstimatedLightMinutes",
        "SeeingScore",
        "CloudPct",
        "Moon",
        "Safety",
    ]
    row = {
        "Name": result.target_name,
        "RA": result.ra,
        "Dec": result.dec,
        "Type": result.target_type,
        "Magnitude": result.magnitude,
        "Size": result.size,
        "Grade": result.target_grade,
        "StartTime": result.window.start_iso,
        "EndTime": result.window.end_iso,
        "ExposureSeconds": result.exposure_seconds,
        "Gain": result.gain,
        "Frames": result.frames,
        "EstimatedLightMinutes": result.estimated_total_minutes,
        "SeeingScore": result.window.score,
        "CloudPct": "" if result.window.cloud_pct is None else result.window.cloud_pct,
        "Moon": result.window.moon_text,
        "Safety": "Review-only; no hardware action executed",
    }
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerow(row)


def _write_nina_sequence_json(path: Path, result: ImagingPlanResult) -> None:
    """Write a real N.I.N.A. Advanced Sequencer JSON file from the OSC template."""

    save_filled_sequence(
        path,
        NinaSequencePlan(
            target_name=result.target_name,
            ra=result.ra,
            dec=result.dec,
            start_iso=result.window.start_iso,
            end_iso=result.window.end_iso,
            exposure_seconds=result.exposure_seconds,
            gain=result.gain,
            frames=result.frames,
            min_altitude_deg=DEFAULT_NINA_MIN_ALT_DEG,
            note=(
                "Review the generated sequence in FZAstro Imaging/N.I.N.A. "
                "before slewing, guiding, capture, or automatic execution."
            ),
        ),
    )


def _write_plan_files(
    result: ImagingPlanResult, payload: dict[str, Any]
) -> ImagingPlanResult:
    out_dir = Path(result.plan_json_path).parent
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = Path(result.plan_json_path)
    text_path = Path(result.plan_text_path)
    review_path = Path(result.nina_review_path)
    xml_path = Path(result.nina_xml_path)
    csv_path = Path(result.nina_csv_path)
    sequence_path = Path(result.nina_sequence_path)

    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )

    text_path.write_text(format_imaging_plan_markdown(result), encoding="utf-8")

    review_payload = {
        "format": "FZAstro NINA review plan v1",
        "safe_mode": True,
        "review_required": True,
        "auto_start": False,
        "note": "This file is a review/export plan for FZAstro Imaging. It does not move equipment or start a N.I.N.A. sequence by itself.",
        "target": {
            "name": result.target_name,
            "ra": result.ra,
            "dec": result.dec,
            "type": result.target_type,
        },
        "sequence": {
            "start_time": result.window.start_iso,
            "end_time": result.window.end_iso,
            "exposure_seconds": result.exposure_seconds,
            "gain": result.gain,
            "frames": result.frames,
            "nina_sequence_confirmed": bool(result.nina_sequence_confirmed),
            "nina_sequence_path": (
                result.nina_sequence_path if result.nina_sequence_confirmed else ""
            ),
        },
        "framing": dict(result.framing or {}),
        "conditions": asdict(result.window),
    }
    review_path.write_text(
        json.dumps(review_payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    _write_nina_review_xml(xml_path, result)
    _write_nina_review_csv(csv_path, result)
    # Do not create the N.I.N.A. Advanced Sequencer JSON at draft time.
    # It is generated only after the user confirms target, framing, focal length,
    # exposure, gain, and frame count in FZASTRO IMAGING CONTROL.
    try:
        if sequence_path.exists():
            sequence_path.unlink()
    except Exception:
        pass
    return result


def build_imaging_plan_from_results(
    *,
    command: PredefinedImagingCommand,
    location: dict[str, Any],
    imaging: dict[str, Any],
    forecast: dict[str, Any],
    targets_result: dict[str, Any],
    output_dir: str | Path | None = None,
    created_at: datetime | None = None,
    selected_target: dict[str, Any] | None = None,
) -> ImagingPlanResult:
    created = created_at or datetime.now(timezone.utc)
    window = choose_best_seeing_window(forecast, now=created)
    target = (
        _selected_target_from_pick(selected_target)
        if isinstance(selected_target, dict) and selected_target
        else _choose_target(command, targets_result, window)
    )
    frames, duration_minutes = _frames_for_window(command, window)
    total_minutes = max(1, int((frames * command.exposure_seconds) // 60))
    plan_id = _safe_plan_id(str(target.get("name") or "target"), created)
    base_out_dir = Path(output_dir or IMAGING_PLAN_DIR)
    out_dir = base_out_dir / plan_id

    framing = calculate_framing_details(
        target_size=target.get("size"),
        imaging=imaging,
        exposure_seconds=int(command.exposure_seconds),
        gain=int(command.gain),
        frames=int(frames),
    )

    result = ImagingPlanResult(
        plan_id=plan_id,
        target_name=str(target.get("name") or "Target"),
        target_type=str(target.get("type") or ""),
        ra=str(target.get("ra") or ""),
        dec=str(target.get("dec") or ""),
        magnitude=str(target.get("mag") or ""),
        size=str(target.get("size") or ""),
        target_grade=int(target.get("grade") or 0),
        exposure_seconds=int(command.exposure_seconds),
        gain=int(command.gain),
        frames=int(frames),
        estimated_total_minutes=int(total_minutes),
        window=window,
        location=dict(location or {}),
        imaging=dict(imaging or {}),
        plan_json_path=str(out_dir / f"{plan_id}.json"),
        plan_text_path=str(out_dir / f"{plan_id}.md"),
        nina_review_path=str(out_dir / f"{plan_id}.nina-review.json"),
        nina_xml_path=str(out_dir / f"{plan_id}.nina-plan.xml"),
        nina_csv_path=str(out_dir / f"{plan_id}.nina-target.csv"),
        nina_sequence_path=str(out_dir / f"{plan_id}.nina-sequence.json"),
        framing=framing,
        auto_start_requested=bool(command.auto_start_requested),
        review_required=True,
        nina_sequence_confirmed=False,
    )

    payload = {
        "schema": "fzastro_imaging_plan_v1",
        "created_utc": created.astimezone(timezone.utc).isoformat(),
        "command": asdict(command),
        "plan": asdict(result),
        "safety": {
            "review_required": True,
            "auto_start": False,
            "hardware_actions_executed": False,
            "nina_sequence_confirmed": False,
            "message": "FZAstro created a draft imaging plan. Confirm target framing, focal length, exposure, gain, and frames in FZASTRO IMAGING CONTROL before generating the N.I.N.A. sequence JSON.",
        },
    }
    return _write_plan_files(result, payload)


def build_predefined_imaging_plan(
    *,
    command: PredefinedImagingCommand,
    location: dict[str, Any],
    imaging: dict[str, Any],
    output_dir: str | Path | None = None,
) -> ImagingPlanResult:
    from ..astro_tools.target_planner import plan_targets

    forecast = fetch_7timer_astro_forecast(
        lat=location.get("lat"),
        lon=location.get("lon"),
        elev=location.get("elev", 0.0),
        tz=str(location.get("tz") or "UTC"),
        altitude_correction="auto",
    )
    window = choose_best_seeing_window(forecast)
    start_dt = _parse_dt(window.start_iso, str(location.get("tz") or "UTC"))
    date_iso = start_dt.date().isoformat() if start_dt else None
    targets_result = plan_targets(
        location,
        date_iso=date_iso,
        limit=DEFAULT_TARGET_LIMIT,
        min_alt=DEFAULT_MIN_ALT_DEG,
        catalog_source="auto",
    )
    return build_imaging_plan_from_results(
        command=command,
        location=location,
        imaging=imaging,
        forecast=forecast,
        targets_result=targets_result,
        output_dir=output_dir,
    )


def build_selected_target_imaging_plan(
    *,
    command: PredefinedImagingCommand,
    location: dict[str, Any],
    imaging: dict[str, Any],
    selected_target: dict[str, Any],
    output_dir: str | Path | None = None,
) -> ImagingPlanResult:
    """Build a draft for the exact TARGETS row selected by the user.

    This intentionally avoids looking up the target again by name.  TARGETS is
    the selection surface; Imaging Control only adds SEEING-window evaluation,
    auto frame calculation, framing/capture review, and final N.I.N.A. export.
    """

    forecast = fetch_7timer_astro_forecast(
        lat=location.get("lat"),
        lon=location.get("lon"),
        elev=location.get("elev", 0.0),
        tz=str(location.get("tz") or "UTC"),
        altitude_correction="auto",
    )
    return build_imaging_plan_from_results(
        command=command,
        location=location,
        imaging=imaging,
        forecast=forecast,
        targets_result={
            "picks": [dict(selected_target or {})],
            "location": dict(location or {}),
        },
        output_dir=output_dir,
        selected_target=dict(selected_target or {}),
    )


def _window_from_payload(data: dict[str, Any]) -> ImagingWindow:
    return ImagingWindow(
        start_iso=str(data.get("start_iso") or ""),
        end_iso=str(data.get("end_iso") or ""),
        start_label=str(data.get("start_label") or ""),
        end_label=str(data.get("end_label") or ""),
        score=int(data.get("score") or 0),
        score_label=str(data.get("score_label") or ""),
        cloud_pct=data.get("cloud_pct"),
        cloud_text=str(data.get("cloud_text") or ""),
        seeing_text=str(data.get("seeing_text") or ""),
        transparency_text=str(data.get("transparency_text") or ""),
        moon_text=str(data.get("moon_text") or ""),
        astro_dark=bool(data.get("astro_dark") is True),
    )


def _plan_from_payload(plan_data: dict[str, Any]) -> ImagingPlanResult:
    return ImagingPlanResult(
        plan_id=str(plan_data.get("plan_id") or ""),
        target_name=str(plan_data.get("target_name") or "Target"),
        target_type=str(plan_data.get("target_type") or ""),
        ra=str(plan_data.get("ra") or ""),
        dec=str(plan_data.get("dec") or ""),
        magnitude=str(plan_data.get("magnitude") or ""),
        size=str(plan_data.get("size") or ""),
        target_grade=int(plan_data.get("target_grade") or 0),
        exposure_seconds=int(
            plan_data.get("exposure_seconds") or DEFAULT_EXPOSURE_SECONDS
        ),
        gain=int(plan_data.get("gain") or DEFAULT_GAIN),
        frames=int(plan_data.get("frames") or 1),
        estimated_total_minutes=int(plan_data.get("estimated_total_minutes") or 1),
        window=_window_from_payload(dict(plan_data.get("window") or {})),
        location=dict(plan_data.get("location") or {}),
        imaging=dict(plan_data.get("imaging") or {}),
        plan_json_path=str(plan_data.get("plan_json_path") or ""),
        plan_text_path=str(plan_data.get("plan_text_path") or ""),
        nina_review_path=str(plan_data.get("nina_review_path") or ""),
        nina_xml_path=str(plan_data.get("nina_xml_path") or ""),
        nina_csv_path=str(plan_data.get("nina_csv_path") or ""),
        nina_sequence_path=str(plan_data.get("nina_sequence_path") or ""),
        framing=dict(plan_data.get("framing") or {}),
        auto_start_requested=bool(plan_data.get("auto_start_requested")),
        review_required=True,
        nina_sequence_confirmed=bool(plan_data.get("nina_sequence_confirmed")),
    )


def confirm_imaging_plan_for_nina(
    plan_json_path: str | Path,
    *,
    camera_model: str | None = None,
    focal_length_mm: float | None = None,
    reducer_factor: float | None = None,
    exposure_seconds: int | None = None,
    gain: int | None = None,
    frames: int | None = None,
) -> ImagingPlanResult:
    """Generate the final N.I.N.A. JSON only after explicit user confirmation.

    The draft plan is allowed to exist as Markdown/XML/CSV/FZAstro metadata.  The
    importable `.nina-sequence.json` file is created only here, after the user has
    reviewed target, framing, focal length, exposure, gain, and frames.
    """

    json_path = Path(plan_json_path)
    if not json_path.exists():
        raise FileNotFoundError(
            "Draft imaging-plan JSON was not found. Re-send the target from TARGETS and confirm/load again: "
            f"{json_path}"
        )
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    plan_data = dict(payload.get("plan") or {})
    imaging = dict(plan_data.get("imaging") or {})

    if camera_model:
        imaging["preset_name"] = str(camera_model).strip()
    if focal_length_mm is not None:
        imaging["focal_mm"] = max(1.0, float(focal_length_mm))
    if reducer_factor is not None:
        imaging["reducer_factor"] = max(0.05, min(10.0, float(reducer_factor)))
    if exposure_seconds is not None:
        plan_data["exposure_seconds"] = max(1, min(24 * 3600, int(exposure_seconds)))
    if gain is not None:
        plan_data["gain"] = max(0, min(10000, int(gain)))
    if frames is not None:
        plan_data["frames"] = max(1, min(10000, int(frames)))

    exposure = int(plan_data.get("exposure_seconds") or DEFAULT_EXPOSURE_SECONDS)
    gain_value = int(plan_data.get("gain") or DEFAULT_GAIN)
    frame_count = int(plan_data.get("frames") or 1)
    total_minutes = max(1, int((frame_count * exposure) // 60))
    plan_data["estimated_total_minutes"] = total_minutes
    plan_data["imaging"] = imaging
    plan_data["framing"] = calculate_framing_details(
        target_size=plan_data.get("size"),
        imaging=imaging,
        exposure_seconds=exposure,
        gain=gain_value,
        frames=frame_count,
    )
    plan_data["nina_sequence_confirmed"] = True

    result = _plan_from_payload(plan_data)
    sequence_path = Path(result.nina_sequence_path)
    sequence_path.parent.mkdir(parents=True, exist_ok=True)
    _write_nina_sequence_json(sequence_path, result)

    payload["plan"] = asdict(result)
    payload["safety"] = dict(payload.get("safety") or {})
    payload["safety"].update(
        {
            "review_required": True,
            "auto_start": False,
            "hardware_actions_executed": False,
            "nina_sequence_confirmed": True,
            "message": "User confirmed target framing, focal length, exposure, gain, and frames before the N.I.N.A. sequence JSON was generated.",
        }
    )
    payload["confirmation"] = {
        "confirmed_utc": datetime.now(timezone.utc).isoformat(),
        "camera_model": result.framing.get("camera_model") if result.framing else "",
        "effective_focal_length_mm": (
            result.framing.get("effective_focal_length_mm") if result.framing else None
        ),
        "exposure_seconds": result.exposure_seconds,
        "gain": result.gain,
        "frames": result.frames,
        "nina_sequence_path": result.nina_sequence_path,
    }
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    Path(result.plan_text_path).write_text(
        format_imaging_plan_markdown(result), encoding="utf-8"
    )
    _write_nina_review_xml(Path(result.nina_xml_path), result)
    _write_nina_review_csv(Path(result.nina_csv_path), result)

    review_path = Path(result.nina_review_path)
    try:
        review_payload = json.loads(review_path.read_text(encoding="utf-8"))
    except Exception:
        review_payload = {}
    review_payload.update(
        {
            "safe_mode": True,
            "review_required": True,
            "nina_sequence_confirmed": True,
            "sequence": {
                "start_time": result.window.start_iso,
                "end_time": result.window.end_iso,
                "exposure_seconds": result.exposure_seconds,
                "gain": result.gain,
                "frames": result.frames,
                "nina_sequence_path": result.nina_sequence_path,
            },
            "framing": dict(result.framing or {}),
        }
    )
    review_path.write_text(
        json.dumps(review_payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    return result


def format_imaging_plan_markdown(plan: ImagingPlanResult) -> str:
    warning = ""
    if plan.auto_start_requested:
        warning = (
            "\n\n**Safety note:** automatic start/schedule was requested, but this "
            "first-stage command only creates a review plan. Start the sequence manually after checking hardware."
        )
    coord_line = ""
    if plan.ra or plan.dec:
        coord_line = f"\n- Coordinates: RA `{plan.ra or '—'}` · Dec `{plan.dec or '—'}`"

    framing = dict(plan.framing or {})
    sequence_line = (
        f"- `{plan.nina_sequence_path}`\n"
        if plan.nina_sequence_confirmed
        else f"- N.I.N.A. sequence JSON pending: `{plan.nina_sequence_path}`\n"
    )
    sequence_note = (
        "The `.nina-sequence.json` file was generated from a real N.I.N.A. Advanced Sequencer template after confirmation. "
        if plan.nina_sequence_confirmed
        else "The `.nina-sequence.json` file has not been generated yet. Open FZASTRO IMAGING CONTROL, review the target/framing/capture values, then click CONFIRM & GENERATE N.I.N.A. JSON. "
    )
    file_header = (
        "confirmed N.I.N.A. sequence + review files created:\n"
        if plan.nina_sequence_confirmed
        else "draft review files created; N.I.N.A. sequence JSON is pending user confirmation:\n"
    )

    return (
        (
            "**FZAstro Imaging plan confirmed**\n\n"
            if plan.nina_sequence_confirmed
            else "**FZAstro Imaging draft plan created**\n\n"
        )
        + f"- Target: **{plan.target_name}**"
        + f"{coord_line}\n"
        + f"- Type: {plan.target_type or '—'} · Grade: {plan.target_grade or '—'}\n"
        + f"- Window: {plan.window.start_label} → {plan.window.end_label}\n"
        + f"- SEEING score: {plan.window.score}/100 · {plan.window.score_label}\n"
        + f"- Cloud: {plan.window.cloud_pct if plan.window.cloud_pct is not None else '—'}% · {plan.window.cloud_text or '—'}\n"
        + f"- Seeing: {plan.window.seeing_text or '—'}\n"
        + f"- Transparency: {plan.window.transparency_text or '—'}\n"
        + f"- Moon: {plan.window.moon_text or '—'}\n"
        + f"- Framing: {framing.get('camera_model') or 'Camera'} · {framing.get('effective_focal_length_mm') or '—'} mm effective · FOV {framing.get('fov_width_deg') or '—'}° × {framing.get('fov_height_deg') or '—'}° · {framing.get('image_scale_arcsec_px') or '—'} arcsec/px · fit {framing.get('target_fit') or '—'}\n"
        + f"- Exposure: {plan.exposure_seconds}s · Gain: {plan.gain} · Frames: {plan.frames}\n"
        + f"- Estimated light time: {plan.estimated_total_minutes} min\n\n"
        + file_header
        + f"- `{plan.plan_text_path}`\n"
        + sequence_line
        + f"- `{plan.nina_xml_path}`\n"
        + f"- `{plan.nina_csv_path}`\n"
        + f"- `{plan.nina_review_path}`\n"
        + f"- `{plan.plan_json_path}`\n\n"
        + sequence_note
        + "The XML/CSV files are review/helper exports, and the JSON review file is kept for FZAstro metadata.\n\n"
        + "No telescope movement, capture start, or N.I.N.A. sequence execution was performed."
        + warning
    )


def predefined_imaging_command_help() -> str:
    return (
        "Use one of these safe predefined imaging commands:\n\n"
        "- `/nina-plan next`\n"
        "- `/nina-plan next 60s gain 200`\n"
        "- `/nina-plan target M13 60s gain 200`\n"
        "- `/imaging-plan target NGC 7000 exposure 120s gain 100 frames 80`\n\n"
        "These commands create a draft review plan first. The N.I.N.A. Advanced Sequencer JSON is generated only after target framing, focal length, exposure, gain, and frames are confirmed in FZASTRO IMAGING CONTROL."
    )
