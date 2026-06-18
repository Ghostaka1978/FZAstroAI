from fzastro_ai import weather_tools


def test_extract_weather_location_from_direct_question():
    assert (
        weather_tools.extract_weather_location("How is the weather today in Berlin?")
        == "Berlin"
    )
    assert weather_tools.extract_weather_location("Athens weather now") == "Athens"


def test_short_location_followup_uses_recent_weather_context():
    recent_context = "AI: Please share your city, region, or coordinates for weather."

    assert weather_tools.is_weather_request("Athens", recent_context=recent_context)
    assert (
        weather_tools.extract_weather_location(
            "Athens",
            recent_context=recent_context,
        )
        == "Athens"
    )


def test_weather_detection_ignores_url_explanation_and_code_examples():
    assert not weather_tools.is_weather_request(
        "Explain what this link is: "
        "https://api.open-meteo.com/v1/forecast?latitude=50.1&longitude=8.6"
    )
    assert not weather_tools.is_weather_request(
        "Show me a Python example that prints a weather summary"
    )


def test_build_open_meteo_weather_url_contains_current_hourly_and_daily_fields():
    url = weather_tools.build_open_meteo_weather_url(
        {
            "latitude": 50.1109,
            "longitude": 8.6821,
            "timezone": "Europe/Berlin",
        }
    )

    assert "api.open-meteo.com" in url
    assert "latitude=50.110900" in url
    assert "longitude=8.682100" in url
    assert "current=temperature_2m" in url
    assert "weather_code" in url
    assert "daily=weather_code" in url
    assert "timezone=Europe%2FBerlin" in url


def test_perform_weather_today_formats_open_meteo_result(monkeypatch):
    calls = []

    def fake_get_limited_json(url, **kwargs):
        calls.append(url)

        if "geocoding-api.open-meteo.com" in url:
            return {
                "results": [
                    {
                        "name": "Berlin",
                        "admin1": "Berlin",
                        "country": "Germany",
                        "latitude": 52.52,
                        "longitude": 13.405,
                        "timezone": "Europe/Berlin",
                    }
                ]
            }

        return {
            "timezone": "Europe/Berlin",
            "current_units": {
                "temperature_2m": "C",
                "wind_speed_10m": "m/s",
            },
            "current": {
                "time": "2026-06-18T22:00",
                "temperature_2m": 21.4,
                "apparent_temperature": 21.2,
                "relative_humidity_2m": 61,
                "precipitation": 0,
                "rain": 0,
                "showers": 0,
                "snowfall": 0,
                "weather_code": 2,
                "cloud_cover": 46,
                "wind_speed_10m": 3.4,
                "wind_direction_10m": 250,
                "wind_gusts_10m": 7.1,
            },
            "hourly": {
                "time": ["2026-06-18T22:00", "2026-06-18T23:00"],
                "temperature_2m": [21.4, 20.2],
                "relative_humidity_2m": [61, 64],
                "precipitation_probability": [10, 12],
                "precipitation": [0, 0],
                "weather_code": [2, 2],
                "cloud_cover": [46, 50],
                "wind_speed_10m": [3.4, 3.0],
            },
            "daily": {
                "weather_code": [2],
                "temperature_2m_max": [25.2],
                "temperature_2m_min": [15.8],
                "precipitation_sum": [0.1],
                "precipitation_probability_max": [20],
                "sunrise": ["2026-06-18T05:14"],
                "sunset": ["2026-06-18T21:39"],
            },
        }

    monkeypatch.setattr(weather_tools, "get_limited_json", fake_get_limited_json)

    report = weather_tools.perform_weather_today("weather today in Berlin")

    assert report.startswith("[WEATHER]")
    assert "# Weather Today - Berlin, Berlin, Germany" in report
    assert "Partly cloudy" in report
    assert "21.4 C" in report
    assert "High 25.2 C / low 15.8 C" in report
    assert "Source: [Open-Meteo forecast](" in report
    assert "Open-Meteo URL:" not in report
    assert any("geocoding-api.open-meteo.com" in call for call in calls)
    assert any("api.open-meteo.com" in call for call in calls)
