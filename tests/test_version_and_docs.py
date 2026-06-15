from pathlib import Path

from fzastro_ai.config import APP_MILESTONE, APP_VERSION, APP_VERSION_LABEL


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_version_constants_match_version_file():
    version_file = PROJECT_ROOT / "VERSION.txt"
    assert version_file.read_text(encoding="utf-8").strip() == "1.0.0"
    assert APP_VERSION == "1.0.0"
    assert APP_MILESTONE == "Version 1 Release Candidate"
    assert APP_VERSION_LABEL == "FZAstro AI v1.0.0 (Version 1 Release Candidate)"


def test_release_docs_are_version_1_not_production_2():
    checked_files = [
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT / "RELEASE_VALIDATION.md",
        PROJECT_ROOT / "fzastro_ai" / "ui" / "about_dialog.py",
        PROJECT_ROOT / "fzastro_ai" / "ui" / "help_dialog.py",
        PROJECT_ROOT / "validate_release.ps1",
    ]
    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="replace") for path in checked_files
    )

    assert "Version 1" in combined
    assert "v1.0.0" in combined
    assert "Production 2.0 BETA" not in combined
    assert "2.0.0-beta" not in combined


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
    build_script = (PROJECT_ROOT / "build_exe.ps1").read_text(encoding="utf-8")
    validation_script = (PROJECT_ROOT / "validate_release.ps1").read_text(
        encoding="utf-8"
    )

    assert "black" in requirements
    assert "[tool.black]" in pyproject
    assert "Formatting source with Black before build" in build_script
    assert "Checking Black formatting" in validation_script
