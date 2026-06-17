from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fzastro_ai.nina.imaging_plan import (
    PredefinedImagingCommand,
    build_imaging_plan_from_results,
    choose_best_seeing_window,
    parse_predefined_imaging_command,
)


def _forecast_fixture():
    return {
        "tz": "Europe/Berlin",
        "rows": [
            {
                "local_iso": "2026-06-17T22:00:00+02:00",
                "score": 40,
                "score_label": "Poor",
                "cloud_mid_pct": 50,
                "cloud_text": "44–56%",
                "seeing_text": '1.0–1.25" · Good',
                "transparency_text": "0.5–0.6 · Good",
                "moon_text": "Down · 10%",
                "astro_dark": True,
            },
            {
                "local_iso": "2026-06-18T01:00:00+02:00",
                "score": 88,
                "score_label": "Excellent",
                "cloud_mid_pct": 3,
                "cloud_text": "0–6%",
                "seeing_text": '0.75–1.0" · Very good',
                "transparency_text": "0.4–0.5 · Very good",
                "moon_text": "Down · 10%",
                "astro_dark": True,
            },
        ],
    }


def _targets_fixture():
    return {
        "location": {"tz": "Europe/Berlin"},
        "picks": [
            {
                "name": "M31",
                "type": "Galaxy",
                "const": "And",
                "ra": "00 42 44",
                "dec": "+41 16 09",
                "mag": "3.4",
                "size": "3.0°",
                "grade": 70,
                "best_time_local": "2026-06-17T22:00:00+02:00",
            },
            {
                "name": "M13",
                "type": "Globular",
                "const": "Her",
                "ra": "16 41 41",
                "dec": "+36 27 36",
                "mag": "5.8",
                "size": "20′",
                "grade": 95,
                "best_time_local": "2026-06-18T01:00:00+02:00",
            },
        ],
    }


def _find_first_type(node, type_fragment: str):
    if isinstance(node, dict):
        if type_fragment in str(node.get("$type") or ""):
            return node
        for value in node.values():
            found = _find_first_type(value, type_fragment)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_first_type(item, type_fragment)
            if found is not None:
                return found
    return None


def test_parse_predefined_imaging_command_defaults():
    command = parse_predefined_imaging_command("/nina-plan next 60s gain 200")

    assert command is not None
    assert command.mode == "next_best"
    assert command.exposure_seconds == 60
    assert command.gain == 200
    assert command.frames == 0


def test_parse_predefined_imaging_command_target_and_safety():
    command = parse_predefined_imaging_command(
        "/imaging-plan target M13 exposure 120s gain 101 frames 40 start automatically"
    )

    assert command is not None
    assert command.mode == "target"
    assert command.target == "M13"
    assert command.exposure_seconds == 120
    assert command.gain == 101
    assert command.frames == 40
    assert command.auto_start_requested


def test_choose_best_seeing_window_prefers_dark_high_score():
    window = choose_best_seeing_window(
        _forecast_fixture(),
        now=datetime(2026, 6, 17, 20, 0, tzinfo=ZoneInfo("Europe/Berlin")),
    )

    assert window.score == 88
    assert window.start_label == "2026-06-18 01:00"
    assert window.cloud_pct == 3


def test_build_imaging_plan_from_results_writes_review_files(tmp_path: Path):
    command = PredefinedImagingCommand(
        raw_text="/nina-plan next 60s gain 200",
        exposure_seconds=60,
        gain=200,
    )

    plan = build_imaging_plan_from_results(
        command=command,
        location={"lat": 50.2, "lon": 8.4, "elev": 660, "tz": "Europe/Berlin"},
        imaging={"preset_name": "ASI585MC", "focal_mm": 700},
        forecast=_forecast_fixture(),
        targets_result=_targets_fixture(),
        output_dir=tmp_path,
        created_at=datetime(2026, 6, 17, 20, 0, tzinfo=ZoneInfo("Europe/Berlin")),
    )

    assert plan.target_name == "M13"
    assert plan.window.score == 88
    assert plan.review_required
    assert Path(plan.plan_json_path).exists()
    assert Path(plan.plan_text_path).exists()
    assert Path(plan.nina_review_path).exists()
    assert Path(plan.nina_xml_path).exists()
    assert Path(plan.nina_csv_path).exists()
    assert Path(plan.nina_sequence_path).exists()
    assert Path(plan.plan_json_path).parent.name == plan.plan_id
    assert "<FZAstroImagingPlan" in Path(plan.nina_xml_path).read_text(encoding="utf-8")
    assert "Name,RA,Dec" in Path(plan.nina_csv_path).read_text(encoding="utf-8-sig")
    assert "review-only" in Path(plan.plan_text_path).read_text(encoding="utf-8")

    sequence = json.loads(Path(plan.nina_sequence_path).read_text(encoding="utf-8"))
    assert sequence["Target"]["TargetName"] == "M13"
    assert sequence["Target"]["InputCoordinates"]["RAHours"] == 16
    assert sequence["Target"]["InputCoordinates"]["RAMinutes"] == 41
    assert sequence["Target"]["InputCoordinates"]["DecDegrees"] == 36

    take_exposure = _find_first_type(sequence, "TakeExposure")
    assert take_exposure["ExposureTime"] == 60.0
    assert take_exposure["Gain"] == 200
    assert take_exposure["ExposureCount"] == plan.frames
