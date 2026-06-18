from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from ..config import APP_DIR
from ..logging_utils import log_debug, log_warning
from ..network_utils import get_limited_json

SEEING_CACHE_DIR = APP_DIR / "seeing"
SEEING_CACHE_MAX_AGE_SECONDS = 6 * 60 * 60
SEVEN_TIMER_API_BASE = "http://www.7timer.info/bin/api.pl"
OPEN_METEO_FORECAST_BASE = "https://api.open-meteo.com/v1/forecast"
METNO_MOON_BASE = "https://api.met.no/weatherapi/sunrise/3.0/moon"
REQUEST_HEADERS = {
    "User-Agent": "FZAstroAI/1.0 SEEING (+https://github.com/Ghostaka1978/FZAstroAI)",
}

SEEING_PROVIDER_HYBRID = "7timer_hybrid"
SEEING_PROVIDER_7TIMER = "7timer"
SEEING_PROVIDER_LABELS = {
    SEEING_PROVIDER_HYBRID: "7Timer ASTRO + Open-Meteo Cloud + Moon/Dark",
    SEEING_PROVIDER_7TIMER: "7Timer ASTRO only",
}

SEEING_LABELS: dict[int, tuple[str, str]] = {
    1: ('<0.5"', "Exceptional"),
    2: ('0.5–0.75"', "Excellent"),
    3: ('0.75–1.0"', "Very good"),
    4: ('1.0–1.25"', "Good"),
    5: ('1.25–1.5"', "Fair"),
    6: ('1.5–2.0"', "Soft"),
    7: ('2.0–2.5"', "Poor"),
    8: ('>2.5"', "Very poor"),
}

TRANSPARENCY_LABELS: dict[int, tuple[str, str]] = {
    1: ("<0.3 mag/airmass", "Exceptional"),
    2: ("0.3–0.4", "Excellent"),
    3: ("0.4–0.5", "Very good"),
    4: ("0.5–0.6", "Good"),
    5: ("0.6–0.7", "Fair"),
    6: ("0.7–0.85", "Hazy"),
    7: ("0.85–1.0", "Poor"),
    8: (">1.0", "Very poor"),
}

CLOUD_LABELS: dict[int, tuple[str, int]] = {
    1: ("0–6%", 3),
    2: ("6–19%", 13),
    3: ("19–31%", 25),
    4: ("31–44%", 38),
    5: ("44–56%", 50),
    6: ("56–69%", 63),
    7: ("69–81%", 75),
    8: ("81–94%", 88),
    9: ("94–100%", 97),
}

WIND_SPEED_LABELS: dict[int, str] = {
    1: "Calm <0.3 m/s",
    2: "Light 0.3–3.4 m/s",
    3: "Moderate 3.4–8.0 m/s",
    4: "Fresh 8.0–10.8 m/s",
    5: "Strong 10.8–17.2 m/s",
    6: "Gale 17.2–24.5 m/s",
    7: "Storm 24.5–32.6 m/s",
    8: "Hurricane >32.6 m/s",
}

PRECIP_LABELS = {
    "none": "None",
    "rain": "Rain",
    "snow": "Snow",
    "frzr": "Freezing rain",
    "icep": "Ice pellets",
}

_SYNODIC = 29.53058867
_MOON_EPOCH = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)


def clamp_lat_lon(lat: Any, lon: Any) -> tuple[float, float]:
    lat_f = max(-90.0, min(90.0, float(lat)))
    lon_f = max(-180.0, min(180.0, float(lon)))
    return lat_f, lon_f


def normalise_provider(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {SEEING_PROVIDER_7TIMER, "7timer", "7timer astro", "astro"}:
        return SEEING_PROVIDER_7TIMER
    return SEEING_PROVIDER_HYBRID


def normalise_altitude_correction(value: Any, elev: float | int | None = None) -> int:
    """Return a 7Timer ASTRO altitude correction value: 0, 2, or 7 km."""
    text = str(value or "").strip().lower()
    if text in {"2", "2km", "2 km", "2000"}:
        return 2
    if text in {"7", "7km", "7 km", "7000"}:
        return 7
    if text and text not in {"auto", "default", "none", "0", "0km", "0 km"}:
        try:
            number = int(float(text))
            if number in {2, 7}:
                return number
        except Exception:
            pass
    try:
        elev_f = float(elev if elev is not None else 0.0)
    except Exception:
        elev_f = 0.0
    if text == "auto":
        if elev_f >= 5500:
            return 7
        if elev_f >= 1500:
            return 2
    return 0


def build_7timer_astro_url(lat: Any, lon: Any, altitude_correction: Any = 0) -> str:
    lat_f, lon_f = clamp_lat_lon(lat, lon)
    ac = normalise_altitude_correction(altitude_correction)
    query = urlencode(
        {
            "lon": f"{lon_f:.3f}",
            "lat": f"{lat_f:.3f}",
            "product": "astro",
            "output": "json",
            "ac": ac,
        }
    )
    return f"{SEVEN_TIMER_API_BASE}?{query}"


def build_open_meteo_hourly_url(
    lat: Any,
    lon: Any,
    *,
    tz: str | None = "UTC",
    elev: Any = None,
    forecast_days: int = 7,
) -> str:
    lat_f, lon_f = clamp_lat_lon(lat, lon)
    query: dict[str, Any] = {
        "latitude": f"{lat_f:.6f}",
        "longitude": f"{lon_f:.6f}",
        "hourly": ",".join(
            [
                "cloud_cover",
                "temperature_2m",
                "precipitation",
                "precipitation_probability",
                "wind_speed_10m",
                "wind_direction_10m",
            ]
        ),
        "current": ",".join(
            [
                "cloud_cover",
                "temperature_2m",
                "precipitation",
                "wind_speed_10m",
                "wind_direction_10m",
            ]
        ),
        "temperature_unit": "celsius",
        "wind_speed_unit": "ms",
        "timezone": str(tz or "UTC"),
        "forecast_days": max(1, min(16, int(forecast_days))),
        "past_days": 1,
    }
    try:
        if elev is not None:
            query["elevation"] = f"{float(elev):.1f}"
    except Exception:
        pass
    return f"{OPEN_METEO_FORECAST_BASE}?{urlencode(query)}"


def _cache_key(
    lat: float,
    lon: float,
    altitude_correction: int,
    provider: str = SEEING_PROVIDER_HYBRID,
) -> str:
    return re.sub(
        r"[^A-Za-z0-9_.-]+",
        "_",
        f"seeing_{provider}_{lat:.3f}_{lon:.3f}_ac{int(altitude_correction)}",
    )


def _cache_path(
    lat: float,
    lon: float,
    altitude_correction: int,
    provider: str = SEEING_PROVIDER_HYBRID,
) -> Path:
    return (
        SEEING_CACHE_DIR / f"{_cache_key(lat, lon, altitude_correction, provider)}.json"
    )


def _read_cache(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if isinstance(payload, dict):
                return payload
    except Exception as exc:
        log_debug("SEEING cache read skipped", exc)
    return {}


def _write_cache(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        tmp_path.replace(path)
    except Exception as exc:
        log_debug("SEEING cache write skipped", exc)


def fetch_open_meteo_hourly_weather(
    *,
    lat: Any,
    lon: Any,
    elev: Any = None,
    tz: str | None = "UTC",
    forecast_days: int = 7,
) -> dict[str, Any]:
    """Fetch hourly cloud/weather from Open-Meteo for SEEING cloud truth."""
    url = build_open_meteo_hourly_url(
        lat,
        lon,
        tz=tz,
        elev=elev,
        forecast_days=forecast_days,
    )
    payload = get_limited_json(
        url,
        max_bytes=768 * 1024,
        timeout=18,
        headers=REQUEST_HEADERS,
    )
    if not isinstance(payload, dict):
        raise ValueError("Open-Meteo returned non-object JSON.")
    hourly = payload.get("hourly")
    if not isinstance(hourly, dict):
        raise ValueError("Open-Meteo returned no hourly weather data.")
    zone = _safe_zoneinfo(str(payload.get("timezone") or tz or "UTC"))
    times = hourly.get("time") if isinstance(hourly.get("time"), list) else []
    cloud = (
        hourly.get("cloud_cover") if isinstance(hourly.get("cloud_cover"), list) else []
    )
    temps = (
        hourly.get("temperature_2m")
        if isinstance(hourly.get("temperature_2m"), list)
        else []
    )
    wind_speeds = (
        hourly.get("wind_speed_10m")
        if isinstance(hourly.get("wind_speed_10m"), list)
        else []
    )
    wind_dirs = (
        hourly.get("wind_direction_10m")
        if isinstance(hourly.get("wind_direction_10m"), list)
        else []
    )
    precip = (
        hourly.get("precipitation")
        if isinstance(hourly.get("precipitation"), list)
        else []
    )
    precip_probability = (
        hourly.get("precipitation_probability")
        if isinstance(hourly.get("precipitation_probability"), list)
        else []
    )
    count = min(
        len(times),
        len(cloud),
        len(temps),
        len(wind_speeds),
        len(wind_dirs),
        len(precip),
        len(precip_probability),
    )
    if count <= 0:
        raise ValueError("Open-Meteo hourly weather data is empty.")

    records: dict[str, dict[str, Any]] = {}
    for index in range(count):
        try:
            local_dt = datetime.fromisoformat(str(times[index])).replace(tzinfo=zone)
        except Exception:
            continue
        hour_key = local_dt.replace(minute=0, second=0, microsecond=0).isoformat()
        records[hour_key] = {
            "local_iso": hour_key,
            "cloud_cover": cloud[index],
            "temperature_2m": temps[index],
            "wind_speed_10m": wind_speeds[index],
            "wind_direction_10m": wind_dirs[index],
            "precipitation": precip[index],
            "precipitation_probability": precip_probability[index],
        }
    if not records:
        raise ValueError("Open-Meteo hourly weather rows could not be parsed.")
    current_payload = payload.get("current")
    current_record: dict[str, Any] = {}
    if isinstance(current_payload, dict):
        try:
            current_dt = datetime.fromisoformat(
                str(current_payload.get("time"))
            ).replace(tzinfo=zone)
            current_record = {
                "local_iso": current_dt.isoformat(),
                "cloud_cover": current_payload.get("cloud_cover"),
                "temperature_2m": current_payload.get("temperature_2m"),
                "wind_speed_10m": current_payload.get("wind_speed_10m"),
                "wind_direction_10m": current_payload.get("wind_direction_10m"),
                "precipitation": current_payload.get("precipitation"),
                "precipitation_probability": None,
                "is_current": True,
            }
        except Exception:
            current_record = {}
    return {
        "provider": "Open-Meteo",
        "source_url": url,
        "timezone": str(payload.get("timezone") or tz or "UTC"),
        "rows_by_local_hour": records,
        "current": current_record,
    }


def _weather_record_for_local_hour(
    weather: dict[str, Any], local_dt: datetime, zone: ZoneInfo
) -> dict[str, Any] | None:
    records = (
        weather.get("rows_by_local_hour")
        if isinstance(weather.get("rows_by_local_hour"), dict)
        else {}
    )
    if not records:
        return None
    try:
        key = (
            local_dt.astimezone(zone)
            .replace(minute=0, second=0, microsecond=0)
            .isoformat()
        )
    except Exception:
        return None
    record = records.get(key)
    return record if isinstance(record, dict) else None


def _apply_open_meteo_record_to_row(
    row: dict[str, Any], record: dict[str, Any], source_url: str
) -> bool:
    cloud_pct = _float_value(record.get("cloud_cover"))
    if cloud_pct is None:
        return False
    cloud_int = max(0, min(100, int(round(cloud_pct))))
    cloud_code = _cloud_code_from_pct(cloud_int)
    row["cloud_7timer_code"] = row.get("cloud_code")
    row["cloud_7timer_text"] = row.get("cloud_text")
    row["cloud_7timer_mid_pct"] = row.get("cloud_mid_pct")
    row["cloud_code"] = cloud_code
    row["cloud_text"] = CLOUD_LABELS.get(cloud_code, ("Unknown", 100))[0]
    row["cloud_mid_pct"] = cloud_int
    row["cloud_source"] = "Open-Meteo hourly"
    row["cloud_source_url"] = source_url

    temp = _float_value(record.get("temperature_2m"))
    if temp is not None:
        row["temp2m_c"] = round(temp, 1)
    wind_speed = _float_value(record.get("wind_speed_10m"))
    if wind_speed is not None:
        row["wind_speed_ms"] = round(wind_speed, 1)
        row["wind_speed_code"] = _wind_speed_code_from_ms(wind_speed)
        row["wind_speed_text"] = f"{wind_speed:.1f} m/s"
    direction = _wind_direction_from_deg(record.get("wind_direction_10m"))
    if direction:
        row["wind_direction"] = direction
    precip_type, precip_text = _precip_text_from_open_meteo(
        record.get("precipitation"), record.get("precipitation_probability")
    )
    row["precip_type"] = precip_type
    row["precip_text"] = precip_text
    row["raw_open_meteo"] = dict(record)
    _refresh_row_sky_score(row)
    return True


def expand_seeing_rows_to_hourly(
    result: dict[str, Any], weather: dict[str, Any]
) -> int:
    """Expand 7Timer's 3-hour astronomy rows into hourly planner rows."""
    rows = result.get("rows") if isinstance(result.get("rows"), list) else []
    if len(rows) < 2:
        return 0
    zone = _safe_zoneinfo(str(result.get("tz") or weather.get("timezone") or "UTC"))
    parsed: list[tuple[datetime, dict[str, Any]]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            local_dt = datetime.fromisoformat(str(row.get("local_iso"))).astimezone(
                zone
            )
        except Exception:
            continue
        parsed.append((local_dt.replace(minute=0, second=0, microsecond=0), row))
    if len(parsed) < 2:
        return 0
    parsed.sort(key=lambda item: item[0])
    start = parsed[0][0]
    end = parsed[-1][0]
    if end <= start:
        return 0

    source_url = str(weather.get("source_url") or "")
    hourly_rows: list[dict[str, Any]] = []
    matched_weather = 0
    current = start
    while current <= end:
        source_dt, source_row = min(
            parsed, key=lambda item: abs((item[0] - current).total_seconds())
        )
        row = dict(source_row)
        utc_dt = current.astimezone(timezone.utc)
        row["utc_iso"] = utc_dt.isoformat().replace("+00:00", "Z")
        row["local_iso"] = current.isoformat()
        row["local_label"] = current.strftime("%Y-%m-%d %H:%M")
        row["hour_label"] = current.strftime("%a %H:%M")
        try:
            init_dt = datetime.fromisoformat(
                str(result.get("init_utc")).replace("Z", "+00:00")
            )
            row["timepoint_hours"] = round(
                (utc_dt - init_dt.astimezone(timezone.utc)).total_seconds() / 3600
            )
        except Exception:
            pass
        row["hourly_row"] = True
        row["hourly_interpolated"] = current != source_dt
        row["source_7timer_local_label"] = str(source_row.get("local_label") or "")
        row["source_7timer_timepoint_hours"] = source_row.get("timepoint_hours")

        record = _weather_record_for_local_hour(weather, current, zone)
        if record is not None and _apply_open_meteo_record_to_row(
            row, record, source_url
        ):
            matched_weather += 1
        else:
            _refresh_row_sky_score(row)
        hourly_rows.append(row)
        current += timedelta(hours=1)

    if matched_weather <= 0:
        return 0
    result["rows"] = hourly_rows
    result["hourly_rows"] = True
    result["hourly_rows_added"] = max(0, len(hourly_rows) - len(rows))
    result["seeing_cadence_note"] = (
        "Hourly planner rows use nearest 7Timer seeing/transparency samples."
    )
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    summary["rows"] = len(hourly_rows)
    result["summary"] = summary
    return matched_weather


def apply_open_meteo_current_weather(
    result: dict[str, Any], weather: dict[str, Any]
) -> bool:
    """Apply Open-Meteo current conditions to the closest current planner row."""
    current_record = (
        weather.get("current") if isinstance(weather.get("current"), dict) else {}
    )
    if not current_record:
        return False
    current_iso = str(current_record.get("local_iso") or "").strip()
    if not current_iso:
        return False
    try:
        zone = _safe_zoneinfo(str(result.get("tz") or weather.get("timezone") or "UTC"))
        current_dt = datetime.fromisoformat(current_iso).astimezone(zone)
    except Exception:
        return False
    rows = result.get("rows") if isinstance(result.get("rows"), list) else []
    best_row: dict[str, Any] | None = None
    best_delta = 999999.0
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            row_dt = datetime.fromisoformat(str(row.get("local_iso"))).astimezone(zone)
        except Exception:
            continue
        delta = abs((row_dt - current_dt).total_seconds())
        if delta < best_delta:
            best_delta = delta
            best_row = row
    if best_row is None or best_delta > 60 * 60:
        return False
    source_url = str(weather.get("source_url") or "")
    if not _apply_open_meteo_record_to_row(best_row, current_record, source_url):
        return False
    best_row["cloud_source"] = "Open-Meteo current"
    best_row["current_weather_row"] = True
    best_row["current_weather_time"] = current_iso
    result["current_weather_applied"] = True
    result["current_weather_time"] = current_iso
    result["current_cloud_pct"] = best_row.get("cloud_mid_pct")
    return True


def apply_open_meteo_hourly_weather(
    result: dict[str, Any], weather: dict[str, Any]
) -> int:
    """Replace coarse 7Timer cloud rows with Open-Meteo hourly cloud values."""
    rows = result.get("rows") if isinstance(result.get("rows"), list) else []
    records = (
        weather.get("rows_by_local_hour")
        if isinstance(weather.get("rows_by_local_hour"), dict)
        else {}
    )
    if not rows or not records:
        return 0
    matched = expand_seeing_rows_to_hourly(result, weather)
    if matched:
        apply_open_meteo_current_weather(result, weather)
        result["cloud_provider"] = "Open-Meteo hourly"
        result["cloud_source_url"] = str(weather.get("source_url") or "")
        return matched
    zone = _safe_zoneinfo(str(result.get("tz") or weather.get("timezone") or "UTC"))
    matched = 0
    for row in rows:
        try:
            local_dt = datetime.fromisoformat(str(row.get("local_iso"))).astimezone(
                zone
            )
        except Exception:
            continue
        key = local_dt.replace(minute=0, second=0, microsecond=0).isoformat()
        record = records.get(key)
        if not isinstance(record, dict):
            continue
        cloud_pct = _float_value(record.get("cloud_cover"))
        if cloud_pct is None:
            continue
        cloud_int = max(0, min(100, int(round(cloud_pct))))
        cloud_code = _cloud_code_from_pct(cloud_int)
        row["cloud_7timer_code"] = row.get("cloud_code")
        row["cloud_7timer_text"] = row.get("cloud_text")
        row["cloud_7timer_mid_pct"] = row.get("cloud_mid_pct")
        row["cloud_code"] = cloud_code
        row["cloud_text"] = CLOUD_LABELS.get(cloud_code, ("Unknown", 100))[0]
        row["cloud_mid_pct"] = cloud_int
        row["cloud_source"] = "Open-Meteo hourly"
        row["cloud_source_url"] = str(weather.get("source_url") or "")

        temp = _float_value(record.get("temperature_2m"))
        if temp is not None:
            row["temp2m_c"] = round(temp, 1)
        wind_speed = _float_value(record.get("wind_speed_10m"))
        if wind_speed is not None:
            row["wind_speed_ms"] = round(wind_speed, 1)
            row["wind_speed_code"] = _wind_speed_code_from_ms(wind_speed)
            row["wind_speed_text"] = f"{wind_speed:.1f} m/s"
        direction = _wind_direction_from_deg(record.get("wind_direction_10m"))
        if direction != "—":
            row["wind_direction"] = direction
        precip_type, precip_text = _precip_text_from_open_meteo(
            record.get("precipitation"), record.get("precipitation_probability")
        )
        row["precip_type"] = precip_type
        row["precip_text"] = precip_text
        row["raw_open_meteo"] = dict(record)
        _refresh_row_sky_score(row)
        matched += 1
    if matched:
        apply_open_meteo_current_weather(result, weather)
        result["cloud_provider"] = "Open-Meteo hourly"
        result["cloud_source_url"] = str(weather.get("source_url") or "")
    return matched


def attach_open_meteo_weather(
    result: dict[str, Any],
    *,
    lat: Any,
    lon: Any,
    elev: Any = None,
    tz: str | None = "UTC",
) -> dict[str, Any]:
    """Attach Open-Meteo hourly cloud/weather, leaving 7Timer seeing intact."""
    weather = fetch_open_meteo_hourly_weather(lat=lat, lon=lon, elev=elev, tz=tz)
    matched = apply_open_meteo_hourly_weather(result, weather)
    if matched <= 0:
        raise ValueError("Open-Meteo hourly rows did not match 7Timer forecast hours.")
    result["weather_provider"] = "Open-Meteo hourly"
    result["weather_source_url"] = str(weather.get("source_url") or "")
    result["weather_rows_matched"] = matched
    if result.get("hourly_rows"):
        result["weather_cadence"] = "hourly"
    return result


def _parse_cache_saved_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _cache_age_seconds(
    cached: dict[str, Any], *, now: datetime | None = None
) -> int | None:
    saved = _parse_cache_saved_utc(
        cached.get("saved_utc") if isinstance(cached, dict) else None
    )
    if saved is None:
        return None
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    age = (current.astimezone(timezone.utc) - saved).total_seconds()
    return max(0, int(age))


def _cache_age_label(seconds: int | float | None) -> str:
    if seconds is None:
        return "unknown age"
    total_seconds = max(0, int(seconds))
    if total_seconds < 60:
        return f"{total_seconds}s old"
    total_minutes = total_seconds // 60
    if total_minutes < 60:
        return f"{total_minutes}m old"
    total_hours = total_minutes // 60
    minutes = total_minutes % 60
    if total_hours < 48:
        if minutes:
            return f"{total_hours}h {minutes}m old"
        return f"{total_hours}h old"
    days = total_hours // 24
    hours = total_hours % 24
    if hours:
        return f"{days}d {hours}h old"
    return f"{days}d old"


def _parse_init_datetime(value: Any) -> datetime:
    text = str(value or "").strip()
    for fmt in ("%Y%m%d%H", "%Y%m%d%H%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)


def _safe_zoneinfo(tz: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(str(tz or "UTC").strip() or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def _int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _float_value(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except Exception:
        return default


def _quality_from_code(code: int, *, max_code: int) -> int:
    if code <= 0:
        return 0
    if max_code <= 1:
        return 100
    return max(0, min(100, round(100 - ((code - 1) / (max_code - 1)) * 100)))


def _cloud_code_from_pct(value: Any) -> int:
    try:
        pct = max(0, min(100, int(round(float(value)))))
    except Exception:
        return 9
    if pct <= 6:
        return 1
    if pct <= 19:
        return 2
    if pct <= 31:
        return 3
    if pct <= 44:
        return 4
    if pct <= 56:
        return 5
    if pct <= 69:
        return 6
    if pct <= 81:
        return 7
    if pct <= 94:
        return 8
    return 9


def _wind_speed_code_from_ms(value: Any) -> int:
    speed = _float_value(value, 0.0) or 0.0
    if speed < 0.3:
        return 1
    if speed < 3.4:
        return 2
    if speed < 8.0:
        return 3
    if speed < 10.8:
        return 4
    if speed < 17.2:
        return 5
    if speed < 24.5:
        return 6
    if speed < 32.6:
        return 7
    return 8


def _wind_direction_from_deg(value: Any) -> str:
    degrees = _float_value(value)
    if degrees is None:
        return "—"
    labels = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
    index = int((degrees % 360.0 + 22.5) // 45.0) % 8
    return labels[index]


def _precip_text_from_open_meteo(amount: Any, probability: Any) -> tuple[str, str]:
    amount_mm = _float_value(amount, 0.0) or 0.0
    probability_pct = _float_value(probability)
    if amount_mm > 0.05:
        if probability_pct is not None:
            return "rain", f"Rain {amount_mm:.1f} mm · {int(round(probability_pct))}%"
        return "rain", f"Rain {amount_mm:.1f} mm"
    if probability_pct is not None and probability_pct >= 30:
        return "rain", f"Possible rain {int(round(probability_pct))}%"
    return "none", "None"


def _cloud_score_from_pct(pct: int) -> int:
    """Return a cloud score tuned for imaging, not general weather.

    Cloud cover must dominate the final astronomy score: excellent seeing is
    not useful for deep-sky imaging when the sky is mostly covered.
    """
    pct = max(0, min(100, int(pct)))
    if pct <= 10:
        return 100
    if pct <= 20:
        return 92
    if pct <= 30:
        return 82
    if pct <= 40:
        return 68
    if pct <= 50:
        return 52
    if pct <= 60:
        return 36
    if pct <= 70:
        return 24
    if pct <= 80:
        return 14
    if pct <= 90:
        return 7
    return 0


def _cloud_score_cap(pct: int) -> int:
    """Hard ceiling for final score based on cloud cover.

    This prevents rows like 66% cloud + good seeing from being shown as
    a strong imaging opportunity.
    """
    pct = max(0, min(100, int(pct)))
    if pct >= 95:
        return 15
    if pct >= 85:
        return 25
    if pct >= 75:
        return 35
    if pct >= 65:
        return 42
    if pct >= 55:
        return 48
    if pct >= 45:
        return 60
    if pct >= 35:
        return 70
    if pct >= 25:
        return 78
    return 100


def _score_from_parts(
    *,
    seeing_code: Any,
    transparency_code: Any,
    cloud_pct: Any,
    wind_speed_code: Any = 2,
    precip_type: Any = "none",
) -> int:
    seeing_score = _quality_from_code(_int_value(seeing_code), max_code=8)
    transparency_score = _quality_from_code(_int_value(transparency_code), max_code=8)
    cloud_mid_pct = max(0, min(100, _int_value(cloud_pct, 100)))
    cloud_score = _cloud_score_from_pct(cloud_mid_pct)
    wind_speed = _int_value(wind_speed_code, 2)
    wind_score = _quality_from_code(wind_speed, max_code=8)
    precip_text = str(precip_type or "none").strip().lower()
    precip_score = 100 if precip_text in {"", "none"} else 10
    base_score = round(
        seeing_score * 0.30
        + transparency_score * 0.22
        + cloud_score * 0.36
        + wind_score * 0.08
        + precip_score * 0.04
    )
    return max(0, min(100, min(base_score, _cloud_score_cap(cloud_mid_pct))))


def _row_score(row: dict[str, Any]) -> int:
    cloud_code = _int_value(row.get("cloudcover"), 9)
    cloud_mid_pct = CLOUD_LABELS.get(cloud_code, ("Unknown", 100))[1]
    return _score_from_parts(
        seeing_code=row.get("seeing"),
        transparency_code=row.get("transparency"),
        cloud_pct=cloud_mid_pct,
        wind_speed_code=(row.get("wind10m") or {}).get("speed"),
        precip_type=row.get("prec_type"),
    )


def _refresh_row_sky_score(row: dict[str, Any]) -> None:
    score = _score_from_parts(
        seeing_code=row.get("seeing_code"),
        transparency_code=row.get("transparency_code"),
        cloud_pct=row.get("cloud_mid_pct"),
        wind_speed_code=row.get("wind_speed_code"),
        precip_type=row.get("precip_type"),
    )
    row["score"] = score
    row["score_label"] = score_label(score)
    row.pop("sky_score", None)
    row.pop("sky_score_label", None)


def score_label(score: Any) -> str:
    try:
        value = int(score)
    except Exception:
        value = 0
    if value >= 80:
        return "Excellent"
    if value >= 65:
        return "Good"
    if value >= 50:
        return "Fair"
    if value >= 35:
        return "Poor"
    return "Avoid"


def _sun_darkness_score_cap(sun_altitude_deg: Any, astro_dark: Any) -> int:
    """Hard imaging score cap from Sun altitude.

    SEEING is an astrophotography planner, so a daylight or twilight row must
    not rank as an excellent imaging slot just because clouds/seeing are good.
    """
    if astro_dark is True:
        return 100
    try:
        altitude = float(sun_altitude_deg)
    except Exception:
        return 45
    if altitude >= -6.0:
        return 5
    if altitude >= -12.0:
        return 20
    if altitude >= -18.0:
        return 45
    return 100


def _sun_darkness_score_factor(sun_altitude_deg: Any, astro_dark: Any) -> float:
    """Scale twilight/daylight rows instead of making every row hit the same cap.

    The cap protects the planner from advertising twilight as a deep-sky imaging
    window. The factor keeps relative weather quality visible, so a cloudy
    twilight record scores lower than a clear twilight record.
    """
    if astro_dark is True:
        return 1.0
    try:
        altitude = float(sun_altitude_deg)
    except Exception:
        return 0.55
    if altitude >= -6.0:
        return 0.10
    if altitude >= -12.0:
        return 0.32
    if altitude >= -18.0:
        return 0.55
    return 1.0


def _moon_score_cap(moon_up: Any, moon_pct: Any) -> int:
    """Soft imaging score cap when the Moon is up.

    The Moon is less absolute than cloud or daylight, but a bright Moon should
    still prevent a card from being advertised as an excellent dark-sky window.
    """
    if moon_up is not True:
        return 100
    pct = max(0, min(100, _int_value(moon_pct, 0)))
    if pct >= 80:
        return 50
    if pct >= 60:
        return 60
    if pct >= 40:
        return 70
    if pct >= 20:
        return 80
    if pct >= 10:
        return 90
    return 100


def _darkness_text_from_sun_altitude(value: Any) -> str:
    altitude = _float_value(value)
    if altitude is None:
        return "Twilight/day"
    if altitude < -18.0:
        return "Astro dark"
    if altitude < -12.0:
        return "Astronomical twilight"
    if altitude < -6.0:
        return "Nautical twilight"
    if altitude < 0.0:
        return "Civil twilight"
    return "Daylight"


def _planner_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows that should drive observing-window decisions.

    True astronomical darkness is ideal. During high-summer/no-dark periods,
    use twilight rows as the fallback instead of letting daylight rows drive
    night-window summaries and daily cloud averages.
    """
    dark_rows = [row for row in rows if row.get("astro_dark") is True]
    if dark_rows:
        return dark_rows
    twilight_rows = [
        row
        for row in rows
        if (_float_value(row.get("sun_altitude_deg"), 90.0) or 90.0) < -6.0
    ]
    return twilight_rows or rows


def _planner_scope(rows: list[dict[str, Any]]) -> str:
    selected = _planner_rows(rows)
    if any(row.get("astro_dark") is True for row in selected):
        return "dark"
    if any(
        (_float_value(row.get("sun_altitude_deg"), 90.0) or 90.0) < -6.0
        for row in selected
    ):
        return "twilight"
    return "daylight"


def _apply_imaging_context_score(row: dict[str, Any]) -> None:
    """Replace the raw atmosphere score with a night-imaging score in-place."""
    base_score = _int_value(row.get("sky_score", row.get("score")), 0)
    row.setdefault("sky_score", base_score)
    row.setdefault("sky_score_label", score_label(base_score))

    sun_cap = _sun_darkness_score_cap(
        row.get("sun_altitude_deg"), row.get("astro_dark")
    )
    sun_factor = _sun_darkness_score_factor(
        row.get("sun_altitude_deg"), row.get("astro_dark")
    )
    moon_cap = _moon_score_cap(row.get("moon_up"), row.get("moon_pct"))

    darkness_scaled_score = round(base_score * sun_factor)
    capped_score = max(0, min(100, darkness_scaled_score, sun_cap, moon_cap))
    row["score"] = capped_score
    row["score_label"] = score_label(capped_score)

    if row.get("astro_dark") is not True:
        row["score_note"] = "Reduced because this hour is not astronomical darkness."
    elif row.get("moon_up") is True and capped_score < base_score:
        row["score_note"] = "Capped because the Moon is up."
    elif capped_score < base_score:
        row["score_note"] = "Capped for imaging conditions."
    else:
        row.pop("score_note", None)


def _seeing_text(code: int) -> str:
    label, quality = SEEING_LABELS.get(code, ("Unknown", "Unknown"))
    return f"{label} · {quality}"


def _transparency_text(code: int) -> str:
    label, quality = TRANSPARENCY_LABELS.get(code, ("Unknown", "Unknown"))
    return f"{label} · {quality}"


def _cloud_text(code: int) -> str:
    label, _mid = CLOUD_LABELS.get(code, ("Unknown", 100))
    return label


def _jd_from_dt_utc(dt_utc: datetime) -> float:
    return dt_utc.timestamp() / 86400.0 + 2440587.5


def _norm360(value: float) -> float:
    return (value % 360.0 + 360.0) % 360.0


def solar_altitude_deg(dt_utc: datetime, lat_deg: float, lon_deg: float) -> float:
    jd = _jd_from_dt_utc(dt_utc)
    n = jd - 2451545.0
    mean_long = _norm360(280.460 + 0.9856474 * n)
    mean_anomaly = math.radians(_norm360(357.528 + 0.9856003 * n))
    ecliptic_long = math.radians(
        _norm360(
            mean_long
            + 1.915 * math.sin(mean_anomaly)
            + 0.020 * math.sin(2 * mean_anomaly)
        )
    )
    obliquity = math.radians(23.439 - 0.000013 * n)
    right_ascension = math.atan2(
        math.cos(obliquity) * math.sin(ecliptic_long), math.cos(ecliptic_long)
    )
    declination = math.asin(math.sin(obliquity) * math.sin(ecliptic_long))
    gmst = _norm360(280.46061837 + 360.98564736629 * (jd - 2451545.0))
    lst = _norm360(gmst + lon_deg)
    hour_angle = math.radians(_norm360(lst) - math.degrees(right_ascension))
    lat = math.radians(lat_deg)
    altitude = math.asin(
        math.sin(lat) * math.sin(declination)
        + math.cos(lat) * math.cos(declination) * math.cos(hour_angle)
    )
    return math.degrees(altitude)


def _interpolate_crossing(
    t0_local: datetime,
    a0: float,
    t1_local: datetime,
    a1: float,
    target_alt: float = -18.0,
) -> datetime:
    if a0 == a1:
        return t0_local
    fraction = (target_alt - a0) / (a1 - a0)
    fraction = max(0.0, min(1.0, fraction))
    return t0_local + (t1_local - t0_local) * fraction


def moon_illum_and_name(dt_utc: datetime) -> tuple[float, str]:
    days = (dt_utc - _MOON_EPOCH).total_seconds() / 86400.0
    age = (days % _SYNODIC + _SYNODIC) % _SYNODIC
    k = 2.0 * math.pi * age / _SYNODIC
    illum = 0.5 * (1 - math.cos(k))
    if age < 1.84566:
        name = "New Moon"
    elif age < 5.53699:
        name = "Waxing Crescent"
    elif age < 9.22831:
        name = "First Quarter"
    elif age < 12.91963:
        name = "Waxing Gibbous"
    elif age < 16.61096:
        name = "Full Moon"
    elif age < 20.30228:
        name = "Waning Gibbous"
    elif age < 23.99361:
        name = "Last Quarter"
    elif age < 27.68493:
        name = "Waning Crescent"
    else:
        name = "New Moon"
    return illum, name


def _date_range_inclusive(start: date, end: date) -> list[date]:
    days: list[date] = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


def _offset_str_for_date(tz_str: str, day: date) -> str:
    zone = _safe_zoneinfo(tz_str)
    dt = datetime(day.year, day.month, day.day, 12, 0, tzinfo=zone)
    offset = dt.utcoffset() or timedelta(0)
    sign = "+" if offset >= timedelta(0) else "-"
    offset = abs(offset)
    hours = int(offset.total_seconds() // 3600)
    minutes = int((offset.total_seconds() % 3600) // 60)
    return f"{sign}{hours:02d}:{minutes:02d}"


def _parse_optional_datetime(value: Any, tz_str: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_safe_zoneinfo(tz_str))
        return parsed
    except Exception:
        return None


def _format_local_dt(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.strftime("%H:%M")


def build_metno_moon_url(lat: Any, lon: Any, day: date, tz: str | None = "UTC") -> str:
    lat_f, lon_f = clamp_lat_lon(lat, lon)
    query = urlencode(
        {
            "lat": f"{lat_f:.6f}",
            "lon": f"{lon_f:.6f}",
            "date": day.isoformat(),
            "offset": _offset_str_for_date(str(tz or "UTC"), day),
        }
    )
    return f"{METNO_MOON_BASE}?{query}"


def fetch_moon_periods(
    lat: float, lon: float, tz: str, start_day: date, end_day: date
) -> list[dict[str, Any]]:
    periods: list[dict[str, Any]] = []
    for day in _date_range_inclusive(start_day, end_day):
        url = build_metno_moon_url(lat, lon, day, tz)
        row: dict[str, Any] = {
            "date": day.isoformat(),
            "moonrise": None,
            "moonset": None,
        }
        try:
            payload = get_limited_json(
                url,
                max_bytes=128 * 1024,
                timeout=10,
                headers=REQUEST_HEADERS,
            )
            props = (
                (payload or {}).get("properties", {})
                if isinstance(payload, dict)
                else {}
            )
            row["moonrise"] = (props.get("moonrise") or {}).get("time")
            row["moonset"] = (props.get("moonset") or {}).get("time")
        except Exception as exc:
            log_debug("SEEING moonrise/moonset fetch skipped", exc)
        moonrise_dt = _parse_optional_datetime(row.get("moonrise"), tz)
        moonset_dt = _parse_optional_datetime(row.get("moonset"), tz)
        midpoint = datetime(
            day.year, day.month, day.day, 12, 0, tzinfo=_safe_zoneinfo(tz)
        ).astimezone(timezone.utc)
        illum, phase = moon_illum_and_name(midpoint)
        periods.append(
            {
                "date": day.isoformat(),
                "moonrise": row.get("moonrise"),
                "moonset": row.get("moonset"),
                "moonrise_label": _format_local_dt(moonrise_dt),
                "moonset_label": _format_local_dt(moonset_dt),
                "moonrise_dt": moonrise_dt,
                "moonset_dt": moonset_dt,
                "illumination_pct": int(round(illum * 100)),
                "phase": phase,
            }
        )
    return periods


def _moon_intervals(
    periods: list[dict[str, Any]], tz: str
) -> list[tuple[datetime, datetime]]:
    zone = _safe_zoneinfo(tz)
    intervals: list[tuple[datetime, datetime]] = []
    for row in periods:
        try:
            current_day = date.fromisoformat(str(row.get("date")))
        except Exception:
            continue
        day_start = datetime(
            current_day.year, current_day.month, current_day.day, 0, 0, tzinfo=zone
        )
        day_end = day_start + timedelta(days=1)
        rise = (
            row.get("moonrise_dt")
            if isinstance(row.get("moonrise_dt"), datetime)
            else None
        )
        set_ = (
            row.get("moonset_dt")
            if isinstance(row.get("moonset_dt"), datetime)
            else None
        )
        if rise is not None and set_ is not None:
            if rise <= set_:
                intervals.append((rise, set_))
            else:
                intervals.append((rise, day_end))
                intervals.append((day_start, set_))
        elif rise is not None:
            intervals.append((rise, day_end))
        elif set_ is not None:
            intervals.append((day_start, set_))
    return intervals


def _is_moon_up(
    local_dt: datetime, moon_periods: list[dict[str, Any]], tz: str
) -> bool | None:
    if not moon_periods:
        return None
    for start, end in _moon_intervals(moon_periods, tz):
        if start <= local_dt <= end:
            return True
    return False


def build_dark_periods(
    *,
    lat: float,
    lon: float,
    tz: str,
    start_local: datetime,
    end_local: datetime,
    step_minutes: int = 20,
) -> list[dict[str, Any]]:
    zone = _safe_zoneinfo(tz)
    current = start_local.astimezone(zone).replace(second=0, microsecond=0)
    end = end_local.astimezone(zone).replace(second=0, microsecond=0)
    samples: list[tuple[datetime, float]] = []
    while current <= end:
        alt = solar_altitude_deg(current.astimezone(timezone.utc), lat, lon)
        samples.append((current, alt))
        current += timedelta(minutes=max(5, int(step_minutes)))
    if not samples:
        return []

    periods: list[dict[str, Any]] = []
    below = False
    period_start: datetime | None = None
    previous_time, previous_alt = samples[0]
    if previous_alt < -18.0:
        below = True
        period_start = previous_time

    for sample_time, sample_alt in samples[1:]:
        if not below and sample_alt < -18.0:
            below = True
            period_start = _interpolate_crossing(
                previous_time, previous_alt, sample_time, sample_alt, -18.0
            )
        elif below and sample_alt >= -18.0:
            period_end = _interpolate_crossing(
                previous_time, previous_alt, sample_time, sample_alt, -18.0
            )
            if period_start is not None:
                duration = period_end - period_start
                periods.append(
                    {
                        "start": period_start.isoformat(),
                        "end": period_end.isoformat(),
                        "start_label": period_start.strftime("%a %Y-%m-%d %H:%M"),
                        "end_label": period_end.strftime("%a %Y-%m-%d %H:%M"),
                        "duration_minutes": int(duration.total_seconds() // 60),
                    }
                )
            below = False
            period_start = None
        previous_time, previous_alt = sample_time, sample_alt

    if below and period_start is not None:
        period_end = samples[-1][0]
        duration = period_end - period_start
        periods.append(
            {
                "start": period_start.isoformat(),
                "end": period_end.isoformat(),
                "start_label": period_start.strftime("%a %Y-%m-%d %H:%M"),
                "end_label": period_end.strftime("%a %Y-%m-%d %H:%M"),
                "duration_minutes": int(duration.total_seconds() // 60),
            }
        )
    return periods


def _period_duration_text(minutes: Any) -> str:
    try:
        mins = max(0, int(minutes))
    except Exception:
        return "—"
    return f"{mins // 60}h {mins % 60:02d}m"


def attach_astro_context(
    result: dict[str, Any], *, include_moon_periods: bool = True
) -> dict[str, Any]:
    """Attach astronomical darkness, moon phase, and moon-up state to forecast rows."""
    rows = result.get("rows") if isinstance(result.get("rows"), list) else []
    if not rows:
        return result
    try:
        lat = float(result.get("lat"))
        lon = float(result.get("lon"))
    except Exception:
        return result
    tz = str(result.get("tz") or "UTC")
    zone = _safe_zoneinfo(tz)
    local_times: list[datetime] = []
    for row in rows:
        try:
            dt = datetime.fromisoformat(str(row.get("local_iso"))).astimezone(zone)
        except Exception:
            try:
                dt = datetime.fromisoformat(str(row.get("local_label"))).replace(
                    tzinfo=zone
                )
            except Exception:
                continue
        local_times.append(dt)
    if not local_times:
        return result

    start_local = min(local_times) - timedelta(hours=6)
    end_local = max(local_times) + timedelta(hours=6)
    dark_periods = build_dark_periods(
        lat=lat,
        lon=lon,
        tz=tz,
        start_local=start_local,
        end_local=end_local,
    )

    moon_periods: list[dict[str, Any]] = []
    moon_note = "Moon rise/set lookup disabled for this provider view."
    if include_moon_periods:
        start_day = (start_local - timedelta(days=1)).date()
        end_day = (end_local + timedelta(days=1)).date()
        moon_periods = fetch_moon_periods(lat, lon, tz, start_day, end_day)
        if any(
            period.get("moonrise") or period.get("moonset") for period in moon_periods
        ):
            moon_note = "Moon rise/set loaded."
        else:
            moon_note = "Moon rise/set unavailable; moon phase still estimated."

    for row in rows:
        try:
            local_dt = datetime.fromisoformat(str(row.get("local_iso"))).astimezone(
                zone
            )
        except Exception:
            continue
        utc_dt = local_dt.astimezone(timezone.utc)
        sun_alt = solar_altitude_deg(utc_dt, lat, lon)
        illum, phase = moon_illum_and_name(utc_dt)
        moon_up = (
            _is_moon_up(local_dt, moon_periods, tz) if include_moon_periods else None
        )
        row["sun_altitude_deg"] = round(sun_alt, 1)
        row["astro_dark"] = bool(sun_alt < -18.0)
        row["astro_dark_text"] = _darkness_text_from_sun_altitude(sun_alt)
        row["moon_pct"] = int(round(illum * 100))
        row["moon_phase"] = phase
        row["moon_up"] = moon_up
        row["moon_text"] = (
            f"{'Up' if moon_up else 'Down'} · {int(round(illum * 100))}%"
            if moon_up is not None
            else f"{int(round(illum * 100))}% · {phase}"
        )
        _apply_imaging_context_score(row)

    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    dark_labels = [
        f"{period.get('start_label', '—')} → {period.get('end_label', '—')} ({_period_duration_text(period.get('duration_minutes'))})"
        for period in dark_periods[:4]
    ]
    moon_labels = [
        f"{period.get('date', '—')}: rise {period.get('moonrise_label', '—')} · set {period.get('moonset_label', '—')} · {period.get('illumination_pct', '—')}% {period.get('phase', '')}"
        for period in moon_periods[:5]
    ]
    # Summaries should represent the best observing slot. Prefer actual
    # astronomical darkness, then twilight fallback, then daylight only when
    # no darker forecast points are available in the record.
    imaging_rows = _planner_rows(rows)
    planner_scope = _planner_scope(rows)
    best_row = max(imaging_rows, key=lambda row: int(row.get("score") or 0))
    summary["best_score"] = int(best_row.get("score") or 0)
    summary["best_score_label"] = score_label(best_row.get("score"))
    summary["best_time"] = best_row.get("local_label", "—")
    summary["best_hour_label"] = best_row.get("hour_label", "—")
    summary["best_seeing"] = best_row.get("seeing_text", "—")
    summary["best_transparency"] = best_row.get("transparency_text", "—")
    summary["best_cloud"] = best_row.get("cloud_text", "—")
    summary["best_dark"] = best_row.get("astro_dark_text", "—")
    summary["best_moon"] = best_row.get("moon_text", "—")
    summary["best_moon_pct"] = best_row.get("moon_pct")
    summary["best_cloud_pct"] = best_row.get("cloud_mid_pct")
    summary["best_cloud_compact"] = (
        f"{best_row.get('cloud_mid_pct', '—')}% · {best_row.get('cloud_text', '—')}"
    )
    summary["best_window_kind"] = planner_scope
    summary["best_window_has_astro_dark"] = planner_scope == "dark"
    summary["best_window_is_twilight_fallback"] = planner_scope == "twilight"
    summary["dark_periods"] = dark_labels
    summary["next_dark_period"] = (
        dark_labels[0] if dark_labels else "No astronomical darkness in forecast range."
    )
    summary["moon_periods"] = moon_labels
    summary["moon_period_note"] = moon_note
    summary["rows"] = len(rows)
    result["summary"] = summary
    result["astro_context"] = {
        "dark_periods": dark_periods,
        "moon_periods": [
            {
                key: value
                for key, value in period.items()
                if key not in {"moonrise_dt", "moonset_dt"}
            }
            for period in moon_periods
        ],
        "moon_period_note": moon_note,
    }
    return result


def parse_7timer_astro_payload(
    payload: dict[str, Any],
    *,
    lat: float,
    lon: float,
    elev: float = 0.0,
    tz: str | None = "UTC",
    altitude_correction: int = 0,
    source_url: str = "",
    cache_used: bool = False,
) -> dict[str, Any]:
    """Convert the 7Timer ASTRO JSON payload into UI-ready rows and summary data."""
    if not isinstance(payload, dict):
        raise ValueError("7Timer ASTRO returned an invalid payload.")
    rows_raw = payload.get("dataseries")
    if not isinstance(rows_raw, list) or not rows_raw:
        raise ValueError("7Timer ASTRO returned no forecast rows.")

    init_utc = _parse_init_datetime(payload.get("init"))
    zone = _safe_zoneinfo(tz)
    rows: list[dict[str, Any]] = []

    for item in rows_raw:
        if not isinstance(item, dict):
            continue
        timepoint = _int_value(item.get("timepoint"), 0)
        utc_dt = init_utc + timedelta(hours=timepoint)
        local_dt = utc_dt.astimezone(zone)
        seeing_code = _int_value(item.get("seeing"), 0)
        trans_code = _int_value(item.get("transparency"), 0)
        cloud_code = _int_value(item.get("cloudcover"), 0)
        cloud_mid = CLOUD_LABELS.get(cloud_code, ("Unknown", 100))[1]
        wind = item.get("wind10m") if isinstance(item.get("wind10m"), dict) else {}
        wind_speed_code = _int_value(wind.get("speed"), 0)
        precip_type = str(item.get("prec_type") or "none").strip().lower()
        normalised = {
            "timepoint_hours": timepoint,
            "utc_iso": utc_dt.isoformat().replace("+00:00", "Z"),
            "local_iso": local_dt.isoformat(),
            "local_label": local_dt.strftime("%Y-%m-%d %H:%M"),
            "hour_label": local_dt.strftime("%a %H:%M"),
            "seeing_code": seeing_code,
            "seeing_text": _seeing_text(seeing_code),
            "transparency_code": trans_code,
            "transparency_text": _transparency_text(trans_code),
            "cloud_code": cloud_code,
            "cloud_text": _cloud_text(cloud_code),
            "cloud_mid_pct": cloud_mid,
            "temp2m_c": item.get("temp2m"),
            "rh2m_code": item.get("rh2m"),
            "wind_direction": str(wind.get("direction") or "—"),
            "wind_speed_code": wind_speed_code,
            "wind_speed_text": WIND_SPEED_LABELS.get(wind_speed_code, "Unknown"),
            "precip_type": precip_type,
            "precip_text": PRECIP_LABELS.get(
                precip_type, precip_type.title() or "None"
            ),
            "raw": dict(item),
        }
        normalised["score"] = _row_score(item)
        normalised["score_label"] = score_label(normalised["score"])
        rows.append(normalised)

    if not rows:
        raise ValueError("7Timer ASTRO rows could not be parsed.")

    best_row = max(rows, key=lambda row: int(row.get("score") or 0))
    best_seeing_row = min(
        rows,
        key=lambda row: (
            int(row.get("seeing_code") or 99),
            -int(row.get("score") or 0),
        ),
    )
    best_transparency_row = min(
        rows,
        key=lambda row: (
            int(row.get("transparency_code") or 99),
            -int(row.get("score") or 0),
        ),
    )

    return {
        "provider": "7Timer ASTRO",
        "provider_id": SEEING_PROVIDER_7TIMER,
        "product": str(payload.get("product") or "astro"),
        "init": str(payload.get("init") or ""),
        "init_utc": init_utc.isoformat().replace("+00:00", "Z"),
        "lat": float(lat),
        "lon": float(lon),
        "elev": float(elev),
        "tz": str(tz or "UTC"),
        "altitude_correction": int(altitude_correction),
        "source_url": str(
            source_url or build_7timer_astro_url(lat, lon, altitude_correction)
        ),
        "cache_used": bool(cache_used),
        "rows": rows,
        "summary": {
            "best_score": int(best_row.get("score") or 0),
            "best_score_label": score_label(best_row.get("score")),
            "best_time": best_row.get("local_label", "—"),
            "best_hour_label": best_row.get("hour_label", "—"),
            "best_seeing": best_row.get("seeing_text", "—"),
            "best_transparency": best_row.get("transparency_text", "—"),
            "best_cloud": best_row.get("cloud_text", "—"),
            "best_cloud_pct": best_row.get("cloud_mid_pct"),
            "best_cloud_compact": f"{best_row.get('cloud_mid_pct', '—')}% · {best_row.get('cloud_text', '—')}",
            "best_true_seeing_time": best_seeing_row.get("local_label", "—"),
            "best_true_seeing": best_seeing_row.get("seeing_text", "—"),
            "best_transparency_time": best_transparency_row.get("local_label", "—"),
            "best_transparency_value": best_transparency_row.get(
                "transparency_text", "—"
            ),
            "rows": len(rows),
        },
    }


def fetch_7timer_astro_forecast(
    *,
    lat: Any,
    lon: Any,
    elev: Any = 0.0,
    tz: str | None = "UTC",
    altitude_correction: Any = "auto",
    provider: Any = SEEING_PROVIDER_HYBRID,
) -> dict[str, Any]:
    """Fetch true astronomy seeing/transparency data from 7Timer ASTRO.

    The default hybrid provider keeps 7Timer for true seeing/transparency and
    attaches FZAstro astronomical darkness and moon-period context for the UI.
    """
    provider_id = normalise_provider(provider)
    lat_f, lon_f = clamp_lat_lon(lat, lon)
    elev_f = float(elev or 0.0)
    ac = normalise_altitude_correction(altitude_correction, elev_f)
    url = build_7timer_astro_url(lat_f, lon_f, ac)
    cache_path = _cache_path(lat_f, lon_f, ac, provider_id)
    include_context = provider_id == SEEING_PROVIDER_HYBRID

    try:
        payload = get_limited_json(
            url,
            max_bytes=512 * 1024,
            timeout=18,
            headers=REQUEST_HEADERS,
        )
        if not isinstance(payload, dict):
            raise ValueError("7Timer ASTRO returned non-object JSON.")
        _write_cache(
            cache_path,
            {
                "payload": payload,
                "url": url,
                "saved_utc": datetime.now(timezone.utc).isoformat(),
            },
        )
        result = parse_7timer_astro_payload(
            payload,
            lat=lat_f,
            lon=lon_f,
            elev=elev_f,
            tz=tz,
            altitude_correction=ac,
            source_url=url,
            cache_used=False,
        )
        result["provider_id"] = provider_id
        result["provider"] = SEEING_PROVIDER_LABELS.get(provider_id, "7Timer ASTRO")
        weather_note = ""
        if include_context:
            try:
                result = attach_open_meteo_weather(
                    result,
                    lat=lat_f,
                    lon=lon_f,
                    elev=elev_f,
                    tz=tz,
                )
                weather_note = (
                    " Open-Meteo hourly cloud loaded; hourly planner rows generated."
                    if result.get("hourly_rows")
                    else " Open-Meteo hourly cloud loaded."
                )
                if result.get("current_weather_applied"):
                    weather_note += " Current cloud applied to nearest hour."
            except Exception as weather_exc:
                log_warning("SEEING Open-Meteo cloud request failed", weather_exc)
                result["weather_status_note"] = (
                    f"Open-Meteo cloud unavailable; using 7Timer cloud ({weather_exc})."
                )
                weather_note = " Open-Meteo cloud unavailable; using 7Timer cloud."
        if include_context:
            result = attach_astro_context(result, include_moon_periods=True)
        result["status_note"] = (
            "Live 7Timer ASTRO seeing/transparency loaded." + weather_note
        )
        return result
    except Exception as exc:
        log_warning("SEEING live 7Timer ASTRO request failed", exc)
        cached = _read_cache(cache_path)
        payload = cached.get("payload") if isinstance(cached, dict) else None
        if isinstance(payload, dict):
            age_seconds = _cache_age_seconds(cached)
            cache_age_text = _cache_age_label(age_seconds)
            if age_seconds is None or age_seconds > SEEING_CACHE_MAX_AGE_SECONDS:
                saved_text = str(cached.get("saved_utc") or "unknown UTC")
                raise RuntimeError(
                    "Live 7Timer ASTRO request failed and the cached SEEING "
                    f"forecast is stale ({cache_age_text}, saved {saved_text}). "
                    "Retry when the network/provider is available."
                ) from exc
            result = parse_7timer_astro_payload(
                payload,
                lat=lat_f,
                lon=lon_f,
                elev=elev_f,
                tz=tz,
                altitude_correction=ac,
                source_url=str(cached.get("url") or url),
                cache_used=True,
            )
            result["provider_id"] = provider_id
            result["provider"] = SEEING_PROVIDER_LABELS.get(provider_id, "7Timer ASTRO")
            result["cache_saved_utc"] = str(cached.get("saved_utc") or "")
            result["cache_age_seconds"] = age_seconds
            result["cache_max_age_seconds"] = SEEING_CACHE_MAX_AGE_SECONDS
            weather_note = ""
            if include_context:
                try:
                    result = attach_open_meteo_weather(
                        result,
                        lat=lat_f,
                        lon=lon_f,
                        elev=elev_f,
                        tz=tz,
                    )
                    weather_note = (
                        " Open-Meteo hourly cloud loaded; hourly planner rows generated."
                        if result.get("hourly_rows")
                        else " Open-Meteo hourly cloud loaded."
                    )
                    if result.get("current_weather_applied"):
                        weather_note += " Current cloud applied to nearest hour."
                except Exception as weather_exc:
                    log_warning("SEEING Open-Meteo cloud request failed", weather_exc)
                    result["weather_status_note"] = (
                        "Open-Meteo cloud unavailable; using cached 7Timer cloud "
                        f"({weather_exc})."
                    )
                    weather_note = (
                        " Open-Meteo cloud unavailable; using cached 7Timer cloud."
                    )
            if include_context:
                result = attach_astro_context(result, include_moon_periods=True)
            result["status_note"] = (
                "Live 7Timer ASTRO request failed; showing recent cached "
                f"seeing/transparency ({cache_age_text})." + weather_note
            )
            return result
        raise
