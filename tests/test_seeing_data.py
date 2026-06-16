from fzastro_ai.astro_tools.seeing_data import (
    build_7timer_astro_url,
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


def test_build_7timer_astro_url_uses_expected_parameters():
    url = build_7timer_astro_url(37.9842, 23.7281, 2)

    assert "product=astro" in url
    assert "output=json" in url
    assert "lat=37.984" in url
    assert "lon=23.728" in url
    assert "ac=2" in url


def test_normalise_altitude_correction_auto_from_elevation():
    assert normalise_altitude_correction("auto", 120.0) == 0
    assert normalise_altitude_correction("auto", 1800.0) == 2
    assert normalise_altitude_correction("auto", 5800.0) == 7
    assert normalise_altitude_correction("7", 0.0) == 7
