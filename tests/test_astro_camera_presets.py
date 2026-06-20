from __future__ import annotations

import ast
import math
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOOKUP_DIALOG = PROJECT_ROOT / "fzastro_ai" / "ui" / "astro_lookup_dialog.py"
WEB_INDEX = (
    PROJECT_ROOT / "fzastro_ai" / "astro_tools" / "fzastro" / "web" / "index.html"
)


def _camera_presets() -> dict:
    tree = ast.parse(LOOKUP_DIALOG.read_text(encoding="utf-8-sig"))
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and getattr(node.target, "id", None) == "CAMERA_PRESETS"
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("CAMERA_PRESETS not found")


def test_zwo_imx455_full_frame_preset_is_available_without_color_or_mono_variant():
    presets = _camera_presets()

    preset = presets["455"]
    assert preset["name"] == "IMX455"
    assert preset["label"] == "IMX455 (full frame, 9576 × 6388)"
    assert preset["preset_label_text"] == "IMX455 (2.946°, full frame, 9576 × 6388)"
    assert preset["sensor_width_mm"] == 36.0
    assert preset["native_width"] == 9576
    assert preset["native_height"] == 6388
    assert preset["output_width"] == 1536
    assert preset["output_height"] == 1024

    assert "asi6200mm" not in presets
    assert "asi6200mc" not in presets


def test_zwo_imx455_full_frame_fov_at_700mm_matches_expected_geometry():
    preset = _camera_presets()["455"]
    sensor_width = float(preset["sensor_width_mm"])
    fov = 2.0 * math.atan((sensor_width / 2.0) / 700.0) * 180.0 / math.pi
    fov_y = fov * int(preset["output_height"]) / int(preset["output_width"])

    assert round(fov, 3) == 2.946
    assert round(fov_y, 3) == 1.964


def test_zwo_asi120_and_asi220_generic_presets_are_available():
    presets = _camera_presets()

    asi120 = presets["120"]
    assert asi120["name"] == "ASI120"
    assert asi120["label"] == "ASI120 (1280 × 960)"
    assert asi120["preset_label_text"] == "ASI120 (0.393°, 1280 × 960)"
    assert asi120["sensor_width_mm"] == 4.8
    assert asi120["native_width"] == 1280
    assert asi120["native_height"] == 960
    assert asi120["output_width"] == 1280
    assert asi120["output_height"] == 960

    asi220 = presets["220"]
    assert asi220["name"] == "ASI220"
    assert asi220["label"] == "ASI220 (1920 × 1080)"
    assert asi220["preset_label_text"] == "ASI220 (0.629°, 1920 × 1080)"
    assert asi220["sensor_width_mm"] == 7.68
    assert asi220["native_width"] == 1920
    assert asi220["native_height"] == 1080
    assert asi220["output_width"] == 1536
    assert asi220["output_height"] == 864


def test_zwo_asi120_and_asi220_fov_at_700mm_matches_expected_geometry():
    presets = _camera_presets()

    asi120_fov = (
        2.0
        * math.atan((float(presets["120"]["sensor_width_mm"]) / 2.0) / 700.0)
        * 180.0
        / math.pi
    )
    asi120_fov_y = (
        asi120_fov
        * int(presets["120"]["output_height"])
        / int(presets["120"]["output_width"])
    )
    assert round(asi120_fov, 3) == 0.393
    assert round(asi120_fov_y, 3) == 0.295

    asi220_fov = (
        2.0
        * math.atan((float(presets["220"]["sensor_width_mm"]) / 2.0) / 700.0)
        * 180.0
        / math.pi
    )
    asi220_fov_y = (
        asi220_fov
        * int(presets["220"]["output_height"])
        / int(presets["220"]["output_width"])
    )
    assert round(asi220_fov, 3) == 0.629
    assert round(asi220_fov_y, 3) == 0.354


def test_camera_presets_are_displayed_from_smallest_to_largest_field_of_view():
    assert list(_camera_presets()) == ["120", "220", "533", "585", "aps", "455"]

    html = WEB_INDEX.read_text(encoding="utf-8-sig")
    labels = [
        '<option value="120">ASI120 (0.393°, 1280 × 960)</option>',
        '<option value="220">ASI220 (0.629°, 1920 × 1080)</option>',
        '<option value="533">IMX533 (1.12°, 3008 × 3008)</option>',
        '<option value="585" selected>IMX585 (1.33°, 3840 × 2160)</option>',
        '<option value="aps">IMX571 (2.337°, 6248 × 4176)</option>',
        '<option value="455">IMX455 (2.946°, full frame, 9576 × 6388)</option>',
    ]
    positions = [html.index(label) for label in labels]
    assert positions == sorted(positions)


def test_legacy_web_lookup_has_single_imx455_full_frame_preset():
    html = WEB_INDEX.read_text(encoding="utf-8-sig")

    assert (
        '<option value="455">IMX455 (2.946°, full frame, 9576 × 6388)</option>' in html
    )
    assert '<option value="120">ASI120 (0.393°, 1280 × 960)</option>' in html
    assert '<option value="220">ASI220 (0.629°, 1920 × 1080)</option>' in html
    assert '"455":{ w: 36.0 }' in html
    assert '"120":{ w: 4.8 }' in html
    assert '"220":{ w: 7.68 }' in html
    assert 'k === "455"' in html
    assert 'k === "120"' in html
    assert 'k === "220"' in html
    assert "ASI6200MM" not in html
    assert "ASI6200MC" not in html
    assert "asi6200mm" not in html
    assert "asi6200mc" not in html
