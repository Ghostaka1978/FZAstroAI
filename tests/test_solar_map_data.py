from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_solar_map_skyfield_loader_uses_quiet_safe_stdio():
    source = (
        PROJECT_ROOT / "fzastro_ai" / "astro_tools" / "solar_map_data.py"
    ).read_text(encoding="utf-8-sig")

    assert "Loader(str(data_dir), verbose=False)" in source
    assert "def _safe_skyfield_stdio" in source
    assert "sys.stdout = null_stream" in source
    assert "sys.stderr = null_stream" in source
    assert "with _safe_skyfield_stdio():" in source
    assert "loader(EPHEMERIS_FILE)" in source


def test_legacy_solar_system_script_handles_windowed_stdio():
    source = (
        PROJECT_ROOT / "fzastro_ai" / "astro_tools" / "fzastro" / "solarsystem.py"
    ).read_text(encoding="utf-8-sig")

    assert "def _protect_null_stdio" in source
    assert "Loader(str(DATA_DIR), verbose=False)" in source
    assert "_protect_null_stdio()" in source
