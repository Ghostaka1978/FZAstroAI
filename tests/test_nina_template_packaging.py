from pathlib import Path

from fzastro_ai.nina.nina_sequence_template import (
    TEMPLATE_FILENAME,
    load_osc_template,
    resolve_osc_template_path,
)


def test_nina_sequence_template_resource_exists_and_loads():
    path = resolve_osc_template_path()
    assert path.name == TEMPLATE_FILENAME
    assert path.is_file()

    data = load_osc_template()
    assert data["$type"].startswith("NINA.Sequencer.Container.DeepSkyObjectContainer")
    assert "Target" in data


def test_build_script_includes_nina_template_resource():
    script = Path("scripts/build_exe.ps1").read_text(encoding="utf-8-sig")
    assert (
        "fzastro_ai\\resources\\nina_templates" in script
        or "fzastro_ai\resources\nina_templates" in script
    )
    assert "osc_advanced_sequence_template.json" in script
