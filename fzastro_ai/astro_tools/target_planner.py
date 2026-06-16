from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from astropy import units as u
from astropy.coordinates import EarthLocation

from .target_catalog import catalog_stats, load_catalog_rows


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _dt_to_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _pick_to_dict(pick: Any) -> dict[str, Any]:
    data = asdict(pick)
    for key in ("best_time_local",):
        data[key] = _dt_to_iso(data.get(key))
    return data


def plan_targets(
    location: dict[str, Any],
    *,
    date_iso: str | None = None,
    limit: int = 20,
    min_alt: float = 45.0,
    step_min: int = 3,
    catalog_source: str = "auto",
    object_type: str = "All",
    min_size_arcmin: float = 0.0,
    max_mag: float | None = None,
) -> dict[str, Any]:
    """Plan the best astrophotography targets for one astronomical night."""
    from .fzastro import target as legacy_target

    lat = _safe_float(location.get("lat"), 50.2459)
    lon = _safe_float(location.get("lon"), 8.4923)
    elev = _safe_float(location.get("elev"), 660.0)
    tz_name = str(location.get("tz") or "UTC").strip() or "UTC"
    tz = ZoneInfo(tz_name)

    legacy_target.LAT = lat
    legacy_target.LON = lon
    legacy_target.ELEV = elev
    legacy_target.TZ = tz
    legacy_target.MIN_ALT = _safe_float(min_alt, 45.0)
    legacy_target.STEP_MIN = max(1, _safe_int(step_min, 3))
    legacy_target.LIMIT = max(1, _safe_int(limit, 20))

    loc = EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=elev * u.m)
    if date_iso:
        base = datetime.fromisoformat(str(date_iso))
        if base.tzinfo is None:
            base = base.replace(tzinfo=tz)
        anchor = legacy_target.local_noon(base.astimezone(tz))
    else:
        anchor = legacy_target.local_noon(datetime.now(tz))

    window = legacy_target.night_window(anchor, tz, loc, step_min=2)
    if window is None:
        window = legacy_target.night_window(
            anchor + timedelta(days=1), tz, loc, step_min=2
        )
    if window is None:
        return {
            "ok": False,
            "error": "No astronomical darkness for this date/location.",
            "picks": [],
            "catalog": catalog_stats(),
        }

    dark_start, dark_end = window
    legacy_target.REF_HOUR_LOCAL = legacy_target._ref_hour_local(dark_start, dark_end)

    rows = load_catalog_rows(
        source=catalog_source,
        object_type=object_type,
        min_size_arcmin=min_size_arcmin,
        max_mag=max_mag,
    )

    visible_rows = legacy_target._site_visible(
        (str(r[0]), str(r[1]), str(r[2]), str(r[3]), str(r[4])) for r in rows
    )
    visible_names = {row[0] for row in visible_rows}

    picks = []
    rejected = 0
    for row in rows:
        if row[0] not in visible_names:
            rejected += 1
            continue
        pick = legacy_target.evaluate_target(row, dark_start, dark_end, tz, loc)
        if pick is None:
            rejected += 1
            continue
        if pick.max_alt < legacy_target.MIN_ALT:
            rejected += 1
            continue
        if pick.visible_minutes < legacy_target.MIN_DURATION_MIN:
            rejected += 1
            continue
        if pick.airmass_min > legacy_target.MAX_AIRMASS:
            rejected += 1
            continue
        if pick.edge_distance_min < legacy_target.EDGE_GUARD_MIN:
            rejected += 1
            continue
        if (
            pick.alt_at_ref is not None
            and pick.alt_at_ref < legacy_target.MIN_ALT_AT_REF
        ):
            rejected += 1
            continue
        picks.append(pick)

    picks.sort(key=lambda item: item.grade, reverse=True)
    picks = picks[: legacy_target.LIMIT]

    midpoint_local = dark_start + (dark_end - dark_start) / 2
    illum, phase_name = legacy_target.moon_illum_and_name(
        midpoint_local.astimezone(timezone.utc)
    )
    duration_min = int((dark_end - dark_start).total_seconds() // 60)

    return {
        "ok": True,
        "location": {"lat": lat, "lon": lon, "elev": elev, "tz": tz_name},
        "date": anchor.date().isoformat(),
        "dark_start": dark_start.isoformat(),
        "dark_end": dark_end.isoformat(),
        "duration_minutes": duration_min,
        "moon": {
            "illumination_pct": int(round(float(illum) * 100.0)),
            "phase": phase_name,
        },
        "filters": {
            "limit": legacy_target.LIMIT,
            "min_alt": legacy_target.MIN_ALT,
            "step_min": legacy_target.STEP_MIN,
            "max_airmass": legacy_target.MAX_AIRMASS,
            "min_duration_min": legacy_target.MIN_DURATION_MIN,
            "edge_guard_min": legacy_target.EDGE_GUARD_MIN,
            "catalog_source": catalog_source,
            "object_type": object_type,
            "min_size_arcmin": float(min_size_arcmin or 0.0),
            "max_mag": max_mag,
        },
        "catalog": catalog_stats(),
        "evaluated": len(rows),
        "rejected": rejected,
        "picks": [_pick_to_dict(pick) for pick in picks],
    }
