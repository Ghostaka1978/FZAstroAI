from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .astropy_runtime import configure_astropy_runtime

configure_astropy_runtime()

try:
    from astropy import units as u
    from astropy.coordinates import EarthLocation
except Exception:  # pragma: no cover - exercised only in thin/non-astro envs
    u = None
    EarthLocation = None

from .target_catalog import catalog_stats, default_catalog_db_path, load_catalog_rows


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


def _catalog_cache_token() -> tuple[str, int, int]:
    path = default_catalog_db_path()
    try:
        stat = path.stat()
    except OSError:
        return (str(path), 0, 0)
    return (str(path), int(stat.st_mtime_ns), int(stat.st_size))


def _target_plan_cache_key(
    location: dict[str, Any],
    *,
    date_iso: str | None,
    limit: int,
    min_alt: float,
    step_min: int,
    catalog_source: str,
    object_type: str,
    min_size_arcmin: float,
    max_mag: float | None,
) -> tuple[Any, ...]:
    return (
        round(_safe_float(location.get("lat"), 50.2459), 6),
        round(_safe_float(location.get("lon"), 8.4923), 6),
        round(_safe_float(location.get("elev"), 660.0), 1),
        str(location.get("tz") or "UTC").strip() or "UTC",
        str(date_iso or "").strip(),
        max(1, _safe_int(limit, 20)),
        round(_safe_float(min_alt, 45.0), 3),
        max(1, _safe_int(step_min, 3)),
        str(catalog_source or "auto").strip() or "auto",
        str(object_type or "All").strip() or "All",
        round(_safe_float(min_size_arcmin, 0.0), 3),
        None if max_mag is None else round(_safe_float(max_mag, 0.0), 3),
        _catalog_cache_token(),
    )


def _missing_astropy_result() -> dict[str, Any]:
    return {
        "ok": False,
        "error": "TARGETS requires Astropy. Install the astronomy dependencies and run the planner again.",
        "picks": [],
        "catalog": _safe_catalog_stats(),
    }


def _safe_catalog_stats() -> dict[str, Any]:
    try:
        return catalog_stats()
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def _longest_sun_altitude_window(
    legacy_target: Any,
    anchor_local_noon: datetime,
    tz: ZoneInfo,
    loc: Any,
    *,
    max_sun_altitude: float,
    step_min: int = 2,
) -> tuple[datetime, datetime] | None:
    """Return the longest block whose Sun altitude is below *max_sun_altitude*.

    TARGETS used to require true astronomical darkness (Sun < -18 degrees).
    That hides every target during high-summer/no-dark seasons.  The fallback
    windows below keep the target ranking useful while clearly marking the
    result as a reduced-quality twilight/night plan.
    """
    start_local = anchor_local_noon
    end_local = start_local + timedelta(days=1)
    np = legacy_target.np
    secs = np.arange(
        int(start_local.astimezone(timezone.utc).timestamp()),
        int(end_local.astimezone(timezone.utc).timestamp()),
        max(1, int(step_min)) * 60,
        dtype=np.int64,
    )
    if secs.size == 0:
        return None

    times = legacy_target.Time(secs, format="unix", scale="utc")
    alt = legacy_target.sun_altitudes(times, loc)
    mask = alt < float(max_sun_altitude)
    if not np.any(mask):
        return None

    idx = np.flatnonzero(mask)
    gaps = np.flatnonzero(np.diff(idx) > 1)
    starts = np.r_[0, gaps + 1]
    ends = np.r_[gaps, len(idx) - 1]
    lengths = ends - starts + 1
    block = int(np.nanargmax(lengths))
    i0 = idx[starts[block]]
    i1 = idx[ends[block]]
    return (
        datetime.fromtimestamp(int(secs[i0]), tz=tz),
        datetime.fromtimestamp(int(secs[i1]), tz=tz),
    )


def _select_targets_planning_window(
    legacy_target: Any,
    anchor: datetime,
    tz: ZoneInfo,
    loc: Any,
) -> dict[str, Any] | None:
    """Pick astronomical darkness first, then progressively darker fallbacks."""
    anchors = (anchor, anchor + timedelta(days=1))
    for candidate_anchor in anchors:
        window = legacy_target.night_window(candidate_anchor, tz, loc, step_min=2)
        if window is not None:
            return {
                "start": window[0],
                "end": window[1],
                "type": "astronomical_darkness",
                "label": "Astronomical darkness",
                "has_astro_dark": True,
                "note": "True astronomical darkness is available.",
                "score_cap": None,
            }

    fallback_specs = (
        (
            -12.0,
            "nautical_twilight",
            "Nautical twilight fallback",
            "No astronomical darkness is available; using the darkest nautical-twilight window.",
            70,
        ),
        (
            -6.0,
            "civil_twilight",
            "Civil twilight fallback",
            "No astronomical or nautical darkness is available; using the darkest civil-twilight window.",
            50,
        ),
        (
            0.0,
            "sun_below_horizon",
            "Below-horizon fallback",
            "No true twilight darkness is available; using the longest Sun-below-horizon window.",
            35,
        ),
    )
    for threshold, window_type, label, note, score_cap in fallback_specs:
        for candidate_anchor in anchors:
            window = _longest_sun_altitude_window(
                legacy_target,
                candidate_anchor,
                tz,
                loc,
                max_sun_altitude=threshold,
                step_min=2,
            )
            if window is not None:
                return {
                    "start": window[0],
                    "end": window[1],
                    "type": window_type,
                    "label": label,
                    "has_astro_dark": False,
                    "note": note,
                    "score_cap": score_cap,
                }
    return None


@lru_cache(maxsize=32)
def _plan_targets_cached(key: tuple[Any, ...]) -> dict[str, Any]:
    (
        lat,
        lon,
        elev,
        tz_name,
        date_key,
        limit,
        min_alt,
        step_min,
        catalog_source,
        object_type,
        min_size_arcmin,
        max_mag,
        _catalog_token,
    ) = key
    return _plan_targets_uncached(
        {"lat": lat, "lon": lon, "elev": elev, "tz": tz_name},
        date_iso=date_key or None,
        limit=limit,
        min_alt=min_alt,
        step_min=step_min,
        catalog_source=catalog_source,
        object_type=object_type,
        min_size_arcmin=min_size_arcmin,
        max_mag=max_mag,
    )


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
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Plan the best astrophotography targets for one astronomical night."""
    if should_stop is not None:
        return _plan_targets_uncached(
            location,
            date_iso=date_iso,
            limit=limit,
            min_alt=min_alt,
            step_min=step_min,
            catalog_source=catalog_source,
            object_type=object_type,
            min_size_arcmin=min_size_arcmin,
            max_mag=max_mag,
            should_stop=should_stop,
        )

    key = _target_plan_cache_key(
        location,
        date_iso=date_iso,
        limit=limit,
        min_alt=min_alt,
        step_min=step_min,
        catalog_source=catalog_source,
        object_type=object_type,
        min_size_arcmin=min_size_arcmin,
        max_mag=max_mag,
    )
    return deepcopy(_plan_targets_cached(key))


def _plan_targets_uncached(
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
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Plan the best astrophotography targets for one astronomical night."""
    if u is None or EarthLocation is None:
        return _missing_astropy_result()

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

    def stopped() -> bool:
        try:
            return bool(should_stop and should_stop())
        except Exception:
            return False

    def cancelled_result() -> dict[str, Any]:
        return {
            "ok": False,
            "cancelled": True,
            "error": "TARGETS calculation stopped.",
            "picks": [],
            "catalog": _safe_catalog_stats(),
        }

    if stopped():
        return cancelled_result()

    loc = EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=elev * u.m)
    if date_iso:
        base = datetime.fromisoformat(str(date_iso))
        if base.tzinfo is None:
            base = base.replace(tzinfo=tz)
        anchor = legacy_target.local_noon(base.astimezone(tz))
    else:
        anchor = legacy_target.local_noon(datetime.now(tz))

    planning_window = _select_targets_planning_window(legacy_target, anchor, tz, loc)
    if planning_window is None:
        return {
            "ok": False,
            "error": "No usable night/twilight window for this date/location.",
            "picks": [],
            "catalog": _safe_catalog_stats(),
        }

    dark_start = planning_window["start"]
    dark_end = planning_window["end"]
    legacy_target.REF_HOUR_LOCAL = legacy_target._ref_hour_local(dark_start, dark_end)

    rows = load_catalog_rows(
        source=catalog_source,
        object_type=object_type,
        min_size_arcmin=min_size_arcmin,
        max_mag=max_mag,
    )

    def can_reach_min_alt(row: tuple[Any, ...]) -> bool:
        # Cheap meridian-altitude prefilter. If an object cannot ever reach
        # the requested altitude at this latitude, the expensive Astropy
        # AltAz sweep for that object cannot pass either.
        try:
            dec = legacy_target.Angle(str(row[4]) + " degrees").degree
            return (90.0 - abs(lat - dec)) >= legacy_target.MIN_ALT
        except Exception:
            return True

    picks = []
    rejected = 0
    prefiltered_by_alt = 0
    for index, row in enumerate(rows):
        if index % 25 == 0 and stopped():
            return cancelled_result()
        if not can_reach_min_alt(row):
            rejected += 1
            prefiltered_by_alt += 1
            continue
        pick = legacy_target.evaluate_target(row, dark_start, dark_end, tz, loc)
        if stopped():
            return cancelled_result()
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
        score_cap = planning_window.get("score_cap")
        if score_cap is not None and pick.grade is not None:
            try:
                pick.grade = min(int(pick.grade), int(score_cap))
            except Exception:
                pass
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
        "window_type": planning_window.get("type"),
        "window_label": planning_window.get("label"),
        "window_note": planning_window.get("note"),
        "has_astro_dark": bool(planning_window.get("has_astro_dark")),
        "fallback_no_astro_dark": not bool(planning_window.get("has_astro_dark")),
        "score_cap": planning_window.get("score_cap"),
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
        "catalog": _safe_catalog_stats(),
        "evaluated": len(rows),
        "rejected": rejected,
        "prefiltered_by_alt": prefiltered_by_alt,
        "picks": [_pick_to_dict(pick) for pick in picks],
    }
