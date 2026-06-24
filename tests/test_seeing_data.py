from datetime import datetime, timedelta, timezone

import pytest

from fzastro_ai.astro_tools import seeing_data
from fzastro_ai.astro_tools.seeing_data import (
    SEEING_CACHE_MAX_AGE_SECONDS,
    SEEING_PROVIDER_7TIMER,
    apply_open_meteo_hourly_weather,
    attach_astro_context,
    build_7timer_astro_url,
    build_open_meteo_hourly_url,
    build_metno_geosatellite_url,
    fetch_7timer_astro_forecast,
    normalise_altitude_correction,
    parse_7timer_astro_payload,
)


def sample_payload():
    return {
        "product": "astro",
        "init": "2026061600",
        "dataseries": [
            {
                "timepoint": 3,
                "cloudcover": 1,
                "seeing": 2,
                "transparency": 2,
                "temp2m": 18,
                "rh2m": 8,
                "wind10m": {"direction": "NE", "speed": 2},
                "prec_type": "none",
            },
            {
                "timepoint": 6,
                "cloudcover": 8,
                "seeing": 7,
                "transparency": 7,
                "temp2m": 17,
                "rh2m": 12,
                "wind10m": {"direction": "N", "speed": 4},
                "prec_type": "rain",
            },
        ],
    }


def test_parse_7timer_astro_payload_builds_summary_and_rows():
    result = parse_7timer_astro_payload(
        sample_payload(),
        lat=37.98,
        lon=23.72,
        elev=120.0,
        tz="Europe/Athens",
        altitude_correction=0,
        source_url="http://example.invalid/seeing.json",
    )

    assert result["provider"] == "7Timer ASTRO"
    assert result["summary"]["rows"] == 2
    assert result["summary"]["best_score"] > 80
    assert result["summary"]["best_seeing"].startswith('0.5–0.75"')
    assert result["rows"][0]["local_label"] == "2026-06-16 06:00"
    assert result["rows"][1]["score"] < result["rows"][0]["score"]
    assert result["rows"][0]["cloud_mid_pct"] == 3
    assert result["rows"][1]["cloud_mid_pct"] == 88


def test_build_7timer_astro_url_uses_expected_parameters():
    url = build_7timer_astro_url(37.9842, 23.7281, 2)

    assert "product=astro" in url
    assert "output=json" in url
    assert "lat=37.984" in url
    assert "lon=23.728" in url
    assert "ac=2" in url


def test_build_open_meteo_hourly_url_requests_cloud_weather_for_site():
    url = build_open_meteo_hourly_url(
        50.17723,
        8.49655,
        tz="Europe/Berlin",
        elev=660.0,
    )

    assert "api.open-meteo.com" in url
    assert "latitude=50.177230" in url
    assert "longitude=8.496550" in url
    assert "cloud_cover" in url
    assert "current=cloud_cover" in url
    assert "wind_speed_10m" in url
    assert "timezone=Europe%2FBerlin" in url
    assert "elevation=660.0" in url


def test_build_metno_geosatellite_url_defaults_to_latest_europe_infrared():
    url = build_metno_geosatellite_url()

    assert "api.met.no/weatherapi/geosatellite" in url
    assert "area=europe" in url
    assert "type=infrared" in url
    assert "time=" not in url


def test_open_meteo_weather_keeps_precipitation_and_humidity_distinct():
    result = parse_7timer_astro_payload(
        {
            "product": "astro",
            "init": "2026061811",
            "dataseries": [
                {
                    "timepoint": 3,
                    "cloudcover": 1,
                    "seeing": 2,
                    "transparency": 2,
                    "temp2m": 25,
                    "wind10m": {"direction": "N", "speed": 2},
                    "prec_type": "none",
                }
            ],
        },
        lat=50.17723,
        lon=8.49655,
        elev=660.0,
        tz="Europe/Berlin",
        altitude_correction=0,
    )
    row = result["rows"][0]

    matched = apply_open_meteo_hourly_weather(
        result,
        {
            "source_url": "https://api.open-meteo.com/v1/forecast",
            "timezone": "Europe/Berlin",
            "rows_by_local_hour": {
                "2026-06-18T16:00:00+02:00": {
                    "cloud_cover": 5,
                    "temperature_2m": 19.4,
                    "relative_humidity_2m": 91,
                    "wind_speed_10m": 1.2,
                    "wind_direction_10m": 180,
                    "precipitation": 0.0,
                    "precipitation_probability": 22,
                }
            },
        },
    )

    assert matched == 1
    assert row["humidity_pct"] == 91
    assert row["humidity_text"] == "91% · high dew risk"
    assert row["precip_probability_pct"] == 22
    assert row["precip_amount_mm"] == 0.0
    assert row["precip_text"] == "22% · 0.0 mm"
    assert row["precip_type"] == "none"


def test_moon_below_horizon_high_illumination_is_not_score_capped():
    down_row = {
        "score": 92,
        "sun_altitude_deg": -25,
        "astro_dark": True,
        "moon_up": False,
        "moon_pct": 90,
    }
    up_row = dict(down_row, moon_up=True)

    seeing_data._apply_imaging_context_score(down_row)
    seeing_data._apply_imaging_context_score(up_row)

    assert down_row["score"] == 92
    assert up_row["score"] == 50
    assert seeing_data._moon_text(False, 90, "Waxing gibbous") == (
        "Below horizon · 90% illuminated"
    )


def test_open_meteo_hourly_weather_overrides_7timer_cloud_and_rescores():
    result = parse_7timer_astro_payload(
        {
            "product": "astro",
            "init": "2026061811",
            "dataseries": [
                {
                    "timepoint": 3,
                    "cloudcover": 8,
                    "seeing": 2,
                    "transparency": 2,
                    "temp2m": 25,
                    "wind10m": {"direction": "N", "speed": 4},
                    "prec_type": "none",
                }
            ],
        },
        lat=50.17723,
        lon=8.49655,
        elev=660.0,
        tz="Europe/Berlin",
        altitude_correction=0,
    )
    row = result["rows"][0]
    old_score = row["score"]
    assert row["local_label"] == "2026-06-18 16:00"
    assert row["cloud_mid_pct"] == 88

    matched = apply_open_meteo_hourly_weather(
        result,
        {
            "source_url": "https://api.open-meteo.com/v1/forecast",
            "timezone": "Europe/Berlin",
            "rows_by_local_hour": {
                "2026-06-18T16:00:00+02:00": {
                    "cloud_cover": 0,
                    "temperature_2m": 29.3,
                    "wind_speed_10m": 2.1,
                    "wind_direction_10m": 90,
                    "precipitation": 0,
                    "precipitation_probability": 0,
                }
            },
        },
    )

    assert matched == 1
    assert row["cloud_source"] == "Open-Meteo hourly"
    assert row["cloud_7timer_mid_pct"] == 88
    assert row["cloud_mid_pct"] == 0
    assert row["cloud_text"] == "0–6%"
    assert row["temp2m_c"] == 29.3
    assert row["wind_direction"] == "E"
    assert row["wind_speed_code"] == 2
    assert row["precip_text"] == "0% · 0.0 mm"
    assert row["precip_amount_mm"] == 0.0
    assert row["precip_probability_pct"] == 0
    assert row["score"] > old_score


def test_open_meteo_hourly_weather_expands_7timer_rows_to_hourly():
    result = parse_7timer_astro_payload(
        {
            "product": "astro",
            "init": "2026061820",
            "dataseries": [
                {
                    "timepoint": 0,
                    "cloudcover": 5,
                    "seeing": 4,
                    "transparency": 3,
                    "wind10m": {"direction": "N", "speed": 3},
                    "prec_type": "none",
                },
                {
                    "timepoint": 3,
                    "cloudcover": 1,
                    "seeing": 6,
                    "transparency": 4,
                    "wind10m": {"direction": "N", "speed": 3},
                    "prec_type": "none",
                },
            ],
        },
        lat=50.17723,
        lon=8.49655,
        elev=660.0,
        tz="UTC",
        altitude_correction=0,
    )

    matched = apply_open_meteo_hourly_weather(
        result,
        {
            "source_url": "https://api.open-meteo.com/v1/forecast",
            "timezone": "UTC",
            "rows_by_local_hour": {
                "2026-06-18T20:00:00+00:00": {
                    "cloud_cover": 10,
                    "temperature_2m": 20,
                    "wind_speed_10m": 1.0,
                    "wind_direction_10m": 0,
                    "precipitation": 0,
                    "precipitation_probability": 0,
                },
                "2026-06-18T21:00:00+00:00": {
                    "cloud_cover": 20,
                    "temperature_2m": 19,
                    "wind_speed_10m": 1.1,
                    "wind_direction_10m": 20,
                    "precipitation": 0,
                    "precipitation_probability": 0,
                },
                "2026-06-18T22:00:00+00:00": {
                    "cloud_cover": 30,
                    "temperature_2m": 18,
                    "wind_speed_10m": 1.2,
                    "wind_direction_10m": 40,
                    "precipitation": 0,
                    "precipitation_probability": 0,
                },
                "2026-06-18T23:00:00+00:00": {
                    "cloud_cover": 40,
                    "temperature_2m": 17,
                    "wind_speed_10m": 1.3,
                    "wind_direction_10m": 60,
                    "precipitation": 0,
                    "precipitation_probability": 0,
                },
            },
        },
    )

    assert matched == 4
    assert result["hourly_rows"] is True
    assert result["summary"]["rows"] == 4
    assert [row["local_label"] for row in result["rows"]] == [
        "2026-06-18 20:00",
        "2026-06-18 21:00",
        "2026-06-18 22:00",
        "2026-06-18 23:00",
    ]
    assert [row["cloud_mid_pct"] for row in result["rows"]] == [10, 20, 30, 40]
    assert result["rows"][1]["hourly_interpolated"] is True
    assert result["rows"][1]["source_7timer_local_label"] == "2026-06-18 20:00"
    assert result["rows"][2]["hourly_interpolated"] is True
    assert result["rows"][2]["source_7timer_local_label"] == "2026-06-18 23:00"


def test_open_meteo_current_cloud_corrects_nearest_current_hour():
    result = parse_7timer_astro_payload(
        {
            "product": "astro",
            "init": "2026061811",
            "dataseries": [
                {
                    "timepoint": 0,
                    "cloudcover": 3,
                    "seeing": 2,
                    "transparency": 2,
                    "wind10m": {"direction": "SW", "speed": 2},
                    "prec_type": "none",
                },
                {
                    "timepoint": 3,
                    "cloudcover": 8,
                    "seeing": 2,
                    "transparency": 2,
                    "wind10m": {"direction": "SW", "speed": 2},
                    "prec_type": "none",
                },
            ],
        },
        lat=50.31890,
        lon=8.41003,
        elev=660.0,
        tz="Europe/Berlin",
        altitude_correction=0,
    )

    matched = apply_open_meteo_hourly_weather(
        result,
        {
            "source_url": "https://api.open-meteo.com/v1/forecast",
            "timezone": "Europe/Berlin",
            "current": {
                "local_iso": "2026-06-18T13:44:00+02:00",
                "cloud_cover": 0,
                "temperature_2m": 27,
                "wind_speed_10m": 1.6,
                "wind_direction_10m": 225,
                "precipitation": 0,
                "precipitation_probability": None,
            },
            "rows_by_local_hour": {
                "2026-06-18T13:00:00+02:00": {
                    "cloud_cover": 14,
                    "temperature_2m": 27,
                    "wind_speed_10m": 1.6,
                    "wind_direction_10m": 225,
                    "precipitation": 0,
                    "precipitation_probability": 0,
                },
                "2026-06-18T14:00:00+02:00": {
                    "cloud_cover": 64,
                    "temperature_2m": 27,
                    "wind_speed_10m": 1.6,
                    "wind_direction_10m": 225,
                    "precipitation": 0,
                    "precipitation_probability": 0,
                },
                "2026-06-18T15:00:00+02:00": {
                    "cloud_cover": 92,
                    "temperature_2m": 28,
                    "wind_speed_10m": 0.7,
                    "wind_direction_10m": 225,
                    "precipitation": 0,
                    "precipitation_probability": 0,
                },
                "2026-06-18T16:00:00+02:00": {
                    "cloud_cover": 69,
                    "temperature_2m": 28,
                    "wind_speed_10m": 2.0,
                    "wind_direction_10m": 225,
                    "precipitation": 0,
                    "precipitation_probability": 0,
                },
            },
        },
    )

    assert matched == 4
    current_row = next(
        row for row in result["rows"] if row["local_label"] == "2026-06-18 14:00"
    )
    assert current_row["current_weather_row"] is True
    assert current_row["cloud_source"] == "Open-Meteo current"
    assert current_row["cloud_mid_pct"] == 0
    assert result["current_weather_applied"] is True
    assert result["current_cloud_pct"] == 0


def test_attach_astro_context_uses_twilight_fallback_when_no_astro_dark():
    result = parse_7timer_astro_payload(
        {
            "product": "astro",
            "init": "2026061806",
            "dataseries": [
                {
                    "timepoint": 3,
                    "cloudcover": 2,
                    "seeing": 2,
                    "transparency": 3,
                    "wind10m": {"direction": "NE", "speed": 2},
                    "prec_type": "none",
                },
                {
                    "timepoint": 6,
                    "cloudcover": 5,
                    "seeing": 2,
                    "transparency": 2,
                    "wind10m": {"direction": "NE", "speed": 2},
                    "prec_type": "none",
                },
                {
                    "timepoint": 9,
                    "cloudcover": 7,
                    "seeing": 2,
                    "transparency": 2,
                    "wind10m": {"direction": "NE", "speed": 2},
                    "prec_type": "none",
                },
                {
                    "timepoint": 12,
                    "cloudcover": 1,
                    "seeing": 4,
                    "transparency": 2,
                    "wind10m": {"direction": "NE", "speed": 2},
                    "prec_type": "none",
                },
                {
                    "timepoint": 15,
                    "cloudcover": 1,
                    "seeing": 5,
                    "transparency": 3,
                    "wind10m": {"direction": "NE", "speed": 2},
                    "prec_type": "none",
                },
            ],
        },
        lat=50.17723,
        lon=8.49655,
        elev=660.0,
        tz="Europe/Berlin",
        altitude_correction=0,
    )

    result = attach_astro_context(result, include_moon_periods=False)
    summary = result["summary"]

    assert not any(row["astro_dark"] for row in result["rows"])
    assert any("twilight" in row["astro_dark_text"].lower() for row in result["rows"])
    assert summary["best_window_kind"] == "twilight"
    assert summary["best_window_is_twilight_fallback"] is True
    assert summary["best_time"] == "2026-06-18 23:00"
    assert "twilight" in summary["best_dark"].lower()


def test_normalise_altitude_correction_auto_from_elevation():
    assert normalise_altitude_correction("auto", 120.0) == 0
    assert normalise_altitude_correction("auto", 1800.0) == 2
    assert normalise_altitude_correction("auto", 5800.0) == 7
    assert normalise_altitude_correction("7", 0.0) == 7


def test_fetch_7timer_astro_forecast_uses_recent_cache_when_live_fails(
    monkeypatch, tmp_path
):
    def fail_live_request(*args, **kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr(seeing_data, "get_limited_json", fail_live_request)
    monkeypatch.setattr(seeing_data, "SEEING_CACHE_DIR", tmp_path)

    saved_utc = datetime.now(timezone.utc) - timedelta(minutes=30)
    cache_path = seeing_data._cache_path(37.98, 23.72, 0, SEEING_PROVIDER_7TIMER)
    seeing_data._write_cache(
        cache_path,
        {
            "payload": sample_payload(),
            "url": "http://example.invalid/recent-cache.json",
            "saved_utc": saved_utc.isoformat(),
        },
    )

    result = fetch_7timer_astro_forecast(
        lat=37.98,
        lon=23.72,
        elev=120.0,
        tz="Europe/Athens",
        altitude_correction=0,
        provider=SEEING_PROVIDER_7TIMER,
    )

    assert result["cache_used"] is True
    assert result["cache_age_seconds"] <= SEEING_CACHE_MAX_AGE_SECONDS
    assert "recent cached seeing/transparency" in result["status_note"]
    assert result["rows"][0]["cloud_mid_pct"] == 3


def test_fetch_7timer_astro_forecast_rejects_stale_cache_when_live_fails(
    monkeypatch, tmp_path
):
    def fail_live_request(*args, **kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr(seeing_data, "get_limited_json", fail_live_request)
    monkeypatch.setattr(seeing_data, "SEEING_CACHE_DIR", tmp_path)

    saved_utc = datetime.now(timezone.utc) - timedelta(
        seconds=SEEING_CACHE_MAX_AGE_SECONDS + 60
    )
    cache_path = seeing_data._cache_path(37.98, 23.72, 0, SEEING_PROVIDER_7TIMER)
    seeing_data._write_cache(
        cache_path,
        {
            "payload": sample_payload(),
            "url": "http://example.invalid/stale-cache.json",
            "saved_utc": saved_utc.isoformat(),
        },
    )

    with pytest.raises(RuntimeError, match="cached SEEING forecast is stale"):
        fetch_7timer_astro_forecast(
            lat=37.98,
            lon=23.72,
            elev=120.0,
            tz="Europe/Athens",
            altitude_correction=0,
            provider=SEEING_PROVIDER_7TIMER,
        )
