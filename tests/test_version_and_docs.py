from pathlib import Path

from fzastro_ai.config import APP_MILESTONE, APP_VERSION, APP_VERSION_LABEL

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RELEASE_VALIDATION_DOC = PROJECT_ROOT / "docs" / "RELEASE_VALIDATION.md"


def read_release_validation_doc():
    return RELEASE_VALIDATION_DOC.read_text(encoding="utf-8")


def test_version_constants_match_version_file():
    version_file = PROJECT_ROOT / "VERSION.txt"
    assert version_file.read_text(encoding="utf-8").strip() == "2.1.0"
    assert APP_VERSION == "2.1.0"
    assert APP_MILESTONE == "Imaging Production"
    assert APP_VERSION_LABEL == "FZAstro AI v2.1.0 (Imaging Production)"


def test_release_docs_are_imaging_production_not_rc3_current_release():
    checked_files = [
        PROJECT_ROOT / "README.md",
        RELEASE_VALIDATION_DOC,
        PROJECT_ROOT / "fzastro_ai" / "ui" / "about_dialog.py",
        PROJECT_ROOT / "fzastro_ai" / "ui" / "help_dialog.py",
        PROJECT_ROOT / "scripts" / "validate_release.ps1",
    ]
    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="replace") for path in checked_files
    )

    assert "Imaging Production" in combined
    assert "v2.1.0" in combined
    assert "Production 2.0 BETA" not in combined
    assert "2.0.0-beta" not in combined
    assert "Version 2 Production local AI workstation" not in combined
    assert "RC 3 Final Production local AI workstation" not in combined
    assert "Release Candidate 2" not in combined
    assert "not a final production claim" not in combined


def test_migrated_fzastro_web_readme_is_not_stale_chess_doc():
    readme = (
        PROJECT_ROOT / "fzastro_ai" / "astro_tools" / "fzastro" / "web" / "README.md"
    )
    content = readme.read_text(encoding="utf-8", errors="replace")

    assert "FZAstro AI Astro Web Assets" in content
    assert "Ancient Greek Chess" not in content
    assert "assets/pieces" not in content


def test_black_is_part_of_release_workflow():
    requirements = (
        (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    )
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    build_script = (PROJECT_ROOT / "scripts" / "build_exe.ps1").read_text(
        encoding="utf-8"
    )
    validation_script = (PROJECT_ROOT / "scripts" / "validate_release.ps1").read_text(
        encoding="utf-8"
    )

    assert "black" in requirements
    assert "[tool.black]" in pyproject
    assert "Formatting source with Black before build" in build_script
    assert "Checking Black formatting" in validation_script


def test_llm_benchmark_feature_is_documented_and_wired():
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    release_docs = read_release_validation_doc()
    help_dialog = (PROJECT_ROOT / "fzastro_ai" / "ui" / "help_dialog.py").read_text(
        encoding="utf-8"
    )
    app_source = (PROJECT_ROOT / "fzastro_ai" / "app.py").read_text(encoding="utf-8")
    benchmark_source = (
        PROJECT_ROOT / "fzastro_ai" / "ui" / "llm_benchmark_dialog.py"
    ).read_text(encoding="utf-8")

    assert "LLM Benchmark Dashboard" in readme
    assert "LLM BENCH" in readme
    assert "LLM Benchmark checks" in release_docs
    assert "polished control layout" in release_docs
    assert "LLM Benchmark Dashboard" in help_dialog
    assert "Run All Presets" in readme
    assert "Run All Presets" in release_docs
    assert "Run All Presets" in help_dialog
    assert "Delete Selected" in readme
    assert "Delete Selected" in release_docs
    assert "Delete Selected" in help_dialog
    assert "persona/calibration" in readme
    assert "persona/calibration" in release_docs
    assert "persona/calibration" in help_dialog
    assert "telemetry" in readme.lower()
    assert "telemetry" in release_docs.lower()
    assert "telemetry" in help_dialog.lower()
    assert "benchmarkTelemetryCard" in benchmark_source
    assert 'tabs.addTab(self.dashboard_tab, "Dashboard")' in benchmark_source
    assert 'tabs.addTab(self.history_tab, "History")' in benchmark_source
    assert 'tabs.addTab(self.compare_tab, "Compare")' in benchmark_source
    assert 'tabs.addTab(self.benchmark_tab, "Benchmark")' not in benchmark_source
    assert "Composite" in benchmark_source
    assert "evaluate_response_quality" in benchmark_source
    assert "selected_persona_payload" in benchmark_source
    assert "Raw model (no persona)" in benchmark_source
    assert "open_llm_benchmark_dialog" in app_source
    assert "llm_benchmark_button" in app_source
    assert "https://github.com/Ghostaka1978/FZAstroAI" in app_source
    assert "https://github.com/Ghostaka1978/FZAstroAI" in readme
    assert "https://github.com/Ghostaka1978/FZAstroAI" in release_docs
    assert "GitHub repository" in help_dialog
    assert "_handle_brand_mark_click" in app_source


def test_distance_ladder_feature_is_documented():
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    release_docs = read_release_validation_doc()
    help_dialog = (PROJECT_ROOT / "fzastro_ai" / "ui" / "help_dialog.py").read_text(
        encoding="utf-8"
    )
    about_dialog = (PROJECT_ROOT / "fzastro_ai" / "ui" / "about_dialog.py").read_text(
        encoding="utf-8"
    )
    engine_source = (
        PROJECT_ROOT / "fzastro_ai" / "astro_tools" / "engine.py"
    ).read_text(encoding="utf-8")

    combined_docs = "\n".join([readme, release_docs, help_dialog, about_dialog])

    assert "Distance ladder calculations" in readme
    assert "distance-ladder" in combined_docs
    assert "parallax" in combined_docs
    assert "Gaia" in combined_docs
    assert "NED-D" in combined_docs
    assert "Hubble" in combined_docs
    assert "FZASTRO_USE_DISTANCE_LADDER" in readme
    assert "FZASTRO_USE_DISTANCE_LADDER" in help_dialog
    assert "_legacy_distance_ladder_for_fast_info" in engine_source
    assert "hubble(z)" in engine_source


def test_v2_astro_tools_suite_is_documented():
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    release_docs = read_release_validation_doc()
    help_dialog = (PROJECT_ROOT / "fzastro_ai" / "ui" / "help_dialog.py").read_text(
        encoding="utf-8"
    )
    about_dialog = (PROJECT_ROOT / "fzastro_ai" / "ui" / "about_dialog.py").read_text(
        encoding="utf-8"
    )
    combined = "\n".join([readme, release_docs, help_dialog, about_dialog])

    assert "Astro Tools Suite" in combined
    assert "SITE, IMAGING, LOOKUP, SUN NOW, SEEING, TARGETS, and SOLAR MAP" in combined
    assert "cloud-aware" in combined
    assert "Bortle" in combined
    assert "8–9 white/urban" in combined
    assert "2–3 blue" in combined
    assert "1 violet" in combined
    assert "Astropy/IERS" in readme
    assert "provider-timeout" in about_dialog or "provider timeouts" in readme
