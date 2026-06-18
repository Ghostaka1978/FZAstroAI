from fastapi.testclient import TestClient

from fzastro_ai.web_companion.server import create_app


def test_web_companion_seeing_endpoint_uses_modern_planner(monkeypatch):
    from fzastro_ai.astro_tools import seeing_data

    captured = {}

    def fake_fetch(**kwargs):
        captured.update(kwargs)
        return {
            "provider": "7Timer ASTRO + Open-Meteo Cloud + Moon/Dark",
            "lat": kwargs["lat"],
            "lon": kwargs["lon"],
            "elev": kwargs["elev"],
            "tz": kwargs["tz"],
            "source_url": "https://www.7timer.info/bin/astro.php",
            "status_note": "Live 7Timer ASTRO seeing/transparency loaded.",
            "summary": {
                "best_score": 86,
                "best_score_label": "Excellent",
                "best_time": "2026-06-19 23:00",
                "best_cloud_compact": "12% Clear",
                "best_dark": "Astro dark",
                "best_moon": "Down 18%",
                "best_seeing": "Very good",
                "best_transparency": "Excellent",
                "dark_periods": ["Fri 2026-06-19 23:00 -> Sat 03:30 (4h 30m)"],
                "moon_periods": ["2026-06-19: rise -- | set 02:10 | 18% Waning"],
            },
            "rows": [
                {
                    "local_label": "2026-06-19 23:00",
                    "score": 86,
                    "score_label": "Excellent",
                    "cloud_mid_pct": 12,
                    "cloud_text": "Clear",
                    "astro_dark": True,
                    "astro_dark_text": "Astro dark",
                    "moon_text": "Down 18%",
                    "seeing_text": "Very good",
                    "transparency_text": "Excellent",
                    "wind_speed_text": "Light",
                    "temp2m_c": 13,
                    "precip_text": "None",
                }
            ],
        }

    monkeypatch.setattr(seeing_data, "fetch_7timer_astro_forecast", fake_fetch)

    response = TestClient(create_app()).post(
        "/api/astro/seeing",
        json={
            "lat": 50.1,
            "lon": 8.6,
            "elev": 120,
            "tz": "Europe/Berlin",
            "nights": 1,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert captured["provider"] == "7timer_hybrid"
    assert captured["altitude_correction"] == "auto"
    assert data["title"] == "SEEING"
    assert "Astronomy Seeing Planner" in data["text"]
    assert "Forecast Rows" in data["text"]
    assert "2026-06-19 23:00" in data["text"]


def test_web_companion_seeing_endpoint_tolerates_status_rows_flag(monkeypatch):
    from fzastro_ai.astro_tools import seeing_data

    def fake_fetch(**kwargs):
        return {
            "ok": True,
            "provider": "7Timer ASTRO + Open-Meteo Cloud + Moon/Dark",
            "lat": kwargs["lat"],
            "lon": kwargs["lon"],
            "elev": kwargs["elev"],
            "tz": kwargs["tz"],
            "rows": True,
            "summary": {"best_score": 61, "best_score_label": "Good"},
        }

    monkeypatch.setattr(seeing_data, "fetch_7timer_astro_forecast", fake_fetch)

    response = TestClient(create_app()).post(
        "/api/astro/seeing",
        json={
            "lat": 50.1,
            "lon": 8.6,
            "elev": 120,
            "tz": "Europe/Berlin",
            "nights": 1,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "Astronomy Seeing Planner" in data["text"]
    assert "No rows returned." in data["text"]


def test_web_companion_seeing_endpoint_returns_card_on_failure(monkeypatch):
    from fzastro_ai.astro_tools import seeing_data

    def fake_fetch(**kwargs):
        raise RuntimeError("provider offline")

    monkeypatch.setattr(seeing_data, "fetch_7timer_astro_forecast", fake_fetch)

    response = TestClient(create_app()).post(
        "/api/astro/seeing",
        json={
            "lat": 50.1,
            "lon": 8.6,
            "elev": 120,
            "tz": "Europe/Berlin",
            "nights": 1,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert "Seeing Forecast Unavailable" in data["text"]
    assert "provider offline" in data["text"]


def test_web_companion_targets_endpoint_uses_desktop_target_planner(monkeypatch):
    from fzastro_ai.astro_tools import target_planner

    captured = {}

    def fake_plan(location, **kwargs):
        captured["location"] = location
        captured["kwargs"] = kwargs
        return {
            "ok": True,
            "location": location,
            "date": "2026-06-19",
            "dark_start": "2026-06-19T23:00:00+02:00",
            "dark_end": "2026-06-20T03:30:00+02:00",
            "duration_minutes": 270,
            "moon": {"illumination_pct": 18, "phase": "Waning"},
            "filters": {
                "limit": kwargs["limit"],
                "min_alt": kwargs["min_alt"],
                "catalog_source": "auto",
            },
            "evaluated": 354,
            "rejected": 320,
            "picks": [
                {
                    "grade": 92,
                    "name": "M 13",
                    "type": "Globular",
                    "const": "Her",
                    "ra": "16:41:41",
                    "dec": "+36:27:36",
                    "mag": 5.8,
                    "size": "20'",
                    "size_src": "20'",
                    "max_alt": 82.4,
                    "airmass_min": 1.01,
                    "visible_minutes": 260,
                    "best_time_local": "2026-06-20T00:35:00+02:00",
                    "alt_at_ref": 80.2,
                    "edge_distance_min": 60,
                }
            ],
        }

    monkeypatch.setattr(target_planner, "plan_targets", fake_plan)

    response = TestClient(create_app()).post(
        "/api/astro/targets",
        json={
            "lat": 50.1,
            "lon": 8.6,
            "elev": 120,
            "tz": "Europe/Berlin",
            "date": "2026-06-19",
            "limit": 10,
            "min_alt": 45,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert captured["location"]["tz"] == "Europe/Berlin"
    assert captured["kwargs"]["date_iso"] == "2026-06-19"
    assert data["title"] == "TARGETS"
    assert "Best Astrophotography Targets" in data["text"]
    assert "Ranked Targets" in data["text"]
    assert "M 13" in data["text"]


def test_web_companion_targets_endpoint_returns_card_on_failure(monkeypatch):
    from fzastro_ai.astro_tools import target_planner

    def fake_plan(location, **kwargs):
        raise RuntimeError("catalog unavailable")

    monkeypatch.setattr(target_planner, "plan_targets", fake_plan)

    response = TestClient(create_app()).post(
        "/api/astro/targets",
        json={
            "lat": 50.1,
            "lon": 8.6,
            "elev": 120,
            "tz": "Europe/Berlin",
            "date": "2026-06-19",
            "limit": 10,
            "min_alt": 45,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert "No Matching Targets" in data["text"]
    assert "catalog unavailable" in data["text"]
