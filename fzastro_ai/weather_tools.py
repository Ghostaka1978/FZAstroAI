"""Direct weather lookup helpers for current conditions and today's forecast."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from .network_utils import get_limited_json


OPEN_METEO_FORECAST_BASE = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_GEOCODING_BASE = "https://geocoding-api.open-meteo.com/v1/search"
IP_LOCATION_ENDPOINTS = (
    "https://ipapi.co/json/",
    "https://ipwho.is/",
)
REQUEST_HEADERS = {
    "User-Agent": "FZAstroAI/1.0 weather lookup (+https://open-meteo.com/)",
    "Accept": "application/json,text/plain,*/*",
}


WEATHER_CODE_TEXT = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def _clean_text(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _recent_context_mentions_weather(recent_context: Any) -> bool:
    clean = _clean_text(recent_context).casefold()
    return bool(
        re.search(
            r"\b(?:weather|forecast|temperature|conditions|rain|snow|cloud|wind)\b",
            clean,
        )
    )


def _looks_like_location_followup(text: Any) -> bool:
    clean = _clean_text(text)

    if not clean or len(clean) > 80:
        return False

    if re.search(r"https?://|[?!]|\b(?:why|how|what|when|where|who)\b", clean, re.I):
        return False

    words = re.findall(r"[A-Za-z][A-Za-z'.-]*|\d+(?:\.\d+)?", clean)
    return 1 <= len(words) <= 6


def _looks_like_weather_meta_request(text: Any) -> bool:
    clean = _clean_text(text).casefold()

    if not clean:
        return False

    if re.search(r"https?://", clean) and re.search(
        r"\b(?:explain|read|summari[sz]e|inspect|analy[sz]e|what\s+is|what's|link|url|endpoint|api)\b",
        clean,
    ):
        return True

    if re.search(r"\b(?:python|code|script|snippet|example|program)\b", clean):
        return bool(
            re.search(
                r"\b(?:show|write|create|generate|make|give|print|prints|example)\b",
                clean,
            )
        )

    return False


def is_weather_request(text: Any, *, recent_context: Any = "") -> bool:
    """Return True when the text should use the deterministic weather tool."""

    clean = _clean_text(text).casefold()

    if not clean:
        return False

    if _looks_like_weather_meta_request(clean):
        return False

    if re.search(
        r"\b(?:weather|forecast|temperature|conditions|rain|snow|clouds?|wind)\b",
        clean,
    ):
        return True

    return bool(
        _recent_context_mentions_weather(recent_context)
        and _looks_like_location_followup(text)
    )


def extract_weather_location(text: Any, *, recent_context: Any = "") -> str:
    """Extract a city/region/coordinate target from a weather request."""

    clean = _clean_text(text)

    if not clean:
        return ""

    if not re.search(
        r"\b(?:weather|forecast|temperature|conditions|rain|snow|clouds?|wind)\b",
        clean,
        flags=re.I,
    ):
        return clean if _recent_context_mentions_weather(recent_context) else ""

    location_patterns = (
        r"\b(?:in|for|at|near|around)\s+(.+)$",
        r"\b(?:weather|forecast|temperature|conditions)\s+(?:in|for|at|near|around)\s+(.+)$",
    )

    for pattern in location_patterns:
        match = re.search(pattern, clean, flags=re.I)
        if match:
            location = match.group(1)
            break
    else:
        location = clean

    cleanup_patterns = (
        r"\b(?:what|how|is|are|the|today|tonight|tomorrow|now|currently|current|"
        r"weather|forecast|temperature|conditions|outside|please|pls|like|for|in)\b",
    )

    for pattern in cleanup_patterns:
        location = re.sub(pattern, " ", location, flags=re.I)

    location = re.sub(r"[^A-Za-z0-9,.\-+/ ]+", " ", location)
    location = re.sub(r"\s+", " ", location).strip(" ,.-")

    if location.casefold() in {"here", "my location", "current location", "local"}:
        return ""

    return location


def _float_value(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_number(value: Any, digits: int = 1, suffix: str = "") -> str:
    number = _float_value(value)

    if number is None:
        return "n/a"

    if abs(number - round(number)) < 0.05:
        text = str(int(round(number)))
    else:
        text = f"{number:.{digits}f}"

    return f"{text}{suffix}"


def _safe_unit(value: Any, default: str) -> str:
    unit = str(value or default).strip()
    unit = unit.replace("°C", "C").replace("°F", "F")
    return unit or default


def _wind_direction_text(degrees: Any) -> str:
    value = _float_value(degrees)

    if value is None:
        return ""

    directions = (
        "N",
        "NNE",
        "NE",
        "ENE",
        "E",
        "ESE",
        "SE",
        "SSE",
        "S",
        "SSW",
        "SW",
        "WSW",
        "W",
        "WNW",
        "NW",
        "NNW",
    )
    index = int((value % 360) / 22.5 + 0.5) % 16
    return directions[index]


def _weather_code_text(value: Any) -> str:
    try:
        return WEATHER_CODE_TEXT.get(int(value), f"Weather code {int(value)}")
    except (TypeError, ValueError):
        return "Conditions unavailable"


def _location_label(location: dict[str, Any]) -> str:
    parts = [
        location.get("name") or location.get("city"),
        location.get("admin1") or location.get("region"),
        location.get("country") or location.get("country_name"),
    ]
    return ", ".join(str(part).strip() for part in parts if str(part or "").strip())


def _parse_coordinate_location(text: str) -> dict[str, Any] | None:
    match = re.search(
        r"^\s*(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)\s*$",
        str(text or ""),
    )

    if not match:
        return None

    lat = float(match.group(1))
    lon = float(match.group(2))

    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None

    return {
        "name": f"{lat:.4f}, {lon:.4f}",
        "latitude": lat,
        "longitude": lon,
        "timezone": "auto",
    }


def geocode_weather_location(location: str) -> dict[str, Any]:
    """Resolve a city/place name to coordinates with Open-Meteo geocoding."""

    clean_location = _clean_text(location)

    if not clean_location:
        return geolocate_ip_weather_location()

    coordinate_location = _parse_coordinate_location(clean_location)
    if coordinate_location:
        return coordinate_location

    query = urlencode(
        {
            "name": clean_location,
            "count": 5,
            "language": "en",
            "format": "json",
        }
    )
    url = f"{OPEN_METEO_GEOCODING_BASE}?{query}"
    payload = get_limited_json(
        url,
        max_bytes=256 * 1024,
        timeout=12,
        headers=REQUEST_HEADERS,
    )
    results = payload.get("results") if isinstance(payload, dict) else []

    if not isinstance(results, list) or not results:
        raise ValueError(f"No weather location found for '{clean_location}'.")

    best = dict(results[0])
    best["source_url"] = url
    return best


def geolocate_ip_weather_location() -> dict[str, Any]:
    """Resolve the approximate current location from public IP metadata."""

    errors = []

    for endpoint in IP_LOCATION_ENDPOINTS:
        try:
            payload = get_limited_json(
                endpoint,
                max_bytes=128 * 1024,
                timeout=10,
                headers=REQUEST_HEADERS,
            )
        except Exception as exc:
            errors.append(str(exc))
            continue

        if not isinstance(payload, dict):
            continue

        lat = _float_value(payload.get("latitude") or payload.get("lat"))
        lon = _float_value(payload.get("longitude") or payload.get("lon"))

        if lat is None or lon is None:
            continue

        timezone = payload.get("timezone")
        if isinstance(timezone, dict):
            timezone = timezone.get("id")

        return {
            "name": payload.get("city") or "IP-derived location",
            "admin1": payload.get("region") or payload.get("region_name"),
            "country": payload.get("country_name") or payload.get("country"),
            "latitude": lat,
            "longitude": lon,
            "timezone": timezone or "auto",
            "source_url": endpoint,
            "ip_location": True,
        }

    raise ValueError(
        "No location was provided and IP location lookup failed"
        + (f": {'; '.join(errors[:2])}" if errors else ".")
    )


def build_open_meteo_weather_url(location: dict[str, Any]) -> str:
    lat = float(location["latitude"])
    lon = float(location["longitude"])
    timezone = str(location.get("timezone") or "auto")
    query = {
        "latitude": f"{lat:.6f}",
        "longitude": f"{lon:.6f}",
        "current": ",".join(
            [
                "temperature_2m",
                "relative_humidity_2m",
                "apparent_temperature",
                "is_day",
                "precipitation",
                "rain",
                "showers",
                "snowfall",
                "weather_code",
                "cloud_cover",
                "wind_speed_10m",
                "wind_direction_10m",
                "wind_gusts_10m",
            ]
        ),
        "hourly": ",".join(
            [
                "temperature_2m",
                "relative_humidity_2m",
                "precipitation_probability",
                "precipitation",
                "weather_code",
                "cloud_cover",
                "wind_speed_10m",
            ]
        ),
        "daily": ",".join(
            [
                "weather_code",
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_sum",
                "precipitation_probability_max",
                "sunrise",
                "sunset",
            ]
        ),
        "temperature_unit": "celsius",
        "wind_speed_unit": "ms",
        "timezone": timezone,
        "forecast_days": 2,
    }
    return f"{OPEN_METEO_FORECAST_BASE}?{urlencode(query)}"


def fetch_open_meteo_weather(location: dict[str, Any]) -> dict[str, Any]:
    url = build_open_meteo_weather_url(location)
    payload = get_limited_json(
        url,
        max_bytes=512 * 1024,
        timeout=16,
        headers=REQUEST_HEADERS,
    )

    if not isinstance(payload, dict):
        raise ValueError("Open-Meteo returned non-object weather data.")

    if not isinstance(payload.get("current"), dict):
        raise ValueError("Open-Meteo returned no current weather data.")

    payload["source_url"] = url
    return payload


def _hourly_rows(payload: dict[str, Any], *, limit: int = 6) -> list[dict[str, Any]]:
    hourly = payload.get("hourly") if isinstance(payload.get("hourly"), dict) else {}
    times = hourly.get("time") if isinstance(hourly.get("time"), list) else []
    temps = (
        hourly.get("temperature_2m")
        if isinstance(hourly.get("temperature_2m"), list)
        else []
    )
    precip_probs = (
        hourly.get("precipitation_probability")
        if isinstance(hourly.get("precipitation_probability"), list)
        else []
    )
    codes = (
        hourly.get("weather_code")
        if isinstance(hourly.get("weather_code"), list)
        else []
    )
    clouds = (
        hourly.get("cloud_cover") if isinstance(hourly.get("cloud_cover"), list) else []
    )
    winds = (
        hourly.get("wind_speed_10m")
        if isinstance(hourly.get("wind_speed_10m"), list)
        else []
    )
    zone = ZoneInfo(str(payload.get("timezone") or "UTC"))

    try:
        now = datetime.now(zone)
    except Exception:
        now = datetime.now()

    rows = []

    for index, raw_time in enumerate(times):
        if len(rows) >= int(limit):
            break

        try:
            local_time = datetime.fromisoformat(str(raw_time)).replace(tzinfo=zone)
        except Exception:
            continue

        if local_time < now:
            continue

        rows.append(
            {
                "time": local_time,
                "temperature": temps[index] if index < len(temps) else None,
                "precipitation_probability": (
                    precip_probs[index] if index < len(precip_probs) else None
                ),
                "weather_code": codes[index] if index < len(codes) else None,
                "cloud_cover": clouds[index] if index < len(clouds) else None,
                "wind_speed": winds[index] if index < len(winds) else None,
            }
        )

    return rows


def format_weather_report(
    location: dict[str, Any],
    payload: dict[str, Any],
    *,
    requested_location: str = "",
) -> str:
    current = payload.get("current") if isinstance(payload.get("current"), dict) else {}
    daily = payload.get("daily") if isinstance(payload.get("daily"), dict) else {}
    units = (
        payload.get("current_units")
        if isinstance(payload.get("current_units"), dict)
        else {}
    )
    label = _location_label(location) or requested_location or "Current location"
    timezone = str(payload.get("timezone") or location.get("timezone") or "local time")
    source_url = str(payload.get("source_url") or "")
    source_text = (
        f"Source: [Open-Meteo forecast]({source_url}) and Open-Meteo geocoding APIs."
        if source_url
        else "Source: Open-Meteo forecast and geocoding APIs."
    )
    retrieved = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    current_time = str(current.get("time") or "").replace("T", " ")
    condition = _weather_code_text(current.get("weather_code"))
    temp_unit = _safe_unit(units.get("temperature_2m"), "C")
    wind_unit = _safe_unit(units.get("wind_speed_10m"), "m/s")
    wind_direction = _wind_direction_text(current.get("wind_direction_10m"))
    wind_direction_suffix = f" {wind_direction}" if wind_direction else ""

    max_temp = (daily.get("temperature_2m_max") or [None])[0]
    min_temp = (daily.get("temperature_2m_min") or [None])[0]
    precip_sum = (daily.get("precipitation_sum") or [None])[0]
    precip_chance = (daily.get("precipitation_probability_max") or [None])[0]
    sunrise = str((daily.get("sunrise") or [""])[0]).replace("T", " ")
    sunset = str((daily.get("sunset") or [""])[0]).replace("T", " ")

    lines = [
        "[WEATHER]",
        f"# Weather Today - {label}",
        "",
        f"Retrieved: {retrieved}",
        f"Timezone: {timezone}",
        source_text,
        "",
        "## Current Conditions",
        (
            f"{condition} at {current_time or 'the current forecast hour'}: "
            f"{_format_number(current.get('temperature_2m'), suffix=' ' + temp_unit)}, "
            f"feels like {_format_number(current.get('apparent_temperature'), suffix=' ' + temp_unit)}."
        ),
        (
            f"Humidity {_format_number(current.get('relative_humidity_2m'), suffix='%')}; "
            f"cloud cover {_format_number(current.get('cloud_cover'), suffix='%')}; "
            f"wind {_format_number(current.get('wind_speed_10m'), suffix=' ' + wind_unit)}"
            f"{wind_direction_suffix}; gusts "
            f"{_format_number(current.get('wind_gusts_10m'), suffix=' ' + wind_unit)}."
        ),
        (
            f"Precipitation now {_format_number(current.get('precipitation'), suffix=' mm')} "
            f"(rain {_format_number(current.get('rain'), suffix=' mm')}, "
            f"showers {_format_number(current.get('showers'), suffix=' mm')}, "
            f"snow {_format_number(current.get('snowfall'), suffix=' cm')})."
        ),
        "",
        "## Today",
        (
            f"High {_format_number(max_temp, suffix=' ' + temp_unit)} / "
            f"low {_format_number(min_temp, suffix=' ' + temp_unit)}; "
            f"precipitation chance up to {_format_number(precip_chance, suffix='%')}; "
            f"precipitation total {_format_number(precip_sum, suffix=' mm')}."
        ),
    ]

    if sunrise or sunset:
        lines.append(f"Sunrise {sunrise or 'n/a'}; sunset {sunset or 'n/a'}.")

    hourly_rows = _hourly_rows(payload, limit=6)

    if hourly_rows:
        lines.extend(["", "## Next Hours"])

        for row in hourly_rows:
            lines.append(
                "- "
                + row["time"].strftime("%H:%M")
                + ": "
                + f"{_weather_code_text(row.get('weather_code'))}, "
                + f"{_format_number(row.get('temperature'), suffix=' ' + temp_unit)}, "
                + f"rain chance {_format_number(row.get('precipitation_probability'), suffix='%')}, "
                + f"cloud {_format_number(row.get('cloud_cover'), suffix='%')}, "
                + f"wind {_format_number(row.get('wind_speed'), suffix=' ' + wind_unit)}"
            )

    return "\n".join(lines).strip()


def perform_weather_today(query: Any, *, recent_context: Any = "") -> str:
    """Return a markdown weather report for a city, coordinates, or IP location."""

    requested_location = extract_weather_location(query, recent_context=recent_context)

    try:
        location = geocode_weather_location(requested_location)
        payload = fetch_open_meteo_weather(location)
        return format_weather_report(
            location,
            payload,
            requested_location=requested_location,
        )
    except Exception as exc:
        location_hint = requested_location or "IP-derived location"
        return f"Weather lookup failed for {location_hint}: {exc}"


__all__ = [
    "build_open_meteo_weather_url",
    "extract_weather_location",
    "fetch_open_meteo_weather",
    "format_weather_report",
    "geocode_weather_location",
    "geolocate_ip_weather_location",
    "is_weather_request",
    "perform_weather_today",
]
