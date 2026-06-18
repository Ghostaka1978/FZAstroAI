from pathlib import Path

from fzastro_ai.nina.nina_sequence_template import (
    TEMPLATE_FILENAME,
    NinaSequencePlan,
    fill_osc_template,
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


def test_filled_nina_sequence_is_full_advanced_sequence_root():
    data = fill_osc_template(
        load_osc_template(),
        NinaSequencePlan(
            target_name="M 13",
            ra="16:41:41.5",
            dec="+36:27:37",
            start_iso="2026-06-17T23:01:57+02:00",
            end_iso="2026-06-18T03:00:06+02:00",
            exposure_seconds=60,
            gain=200,
            frames=170,
        ),
    )

    assert data["$type"].startswith("NINA.Sequencer.Container.SequenceRootContainer")
    assert data["Name"] == "FZAstro M 13"
    assert _contains_type(data, "StartAreaContainer")
    assert _contains_type(data, "TargetAreaContainer")
    assert _contains_type(data, "EndAreaContainer")
    assert _contains_type(data, "ConnectAllEquipment")
    assert _contains_type(data, "DisconnectAllEquipment")
    assert _contains_type(data, "DeepSkyObjectContainer")


def _contains_type(node, type_fragment: str) -> bool:
    if isinstance(node, dict):
        if type_fragment in str(node.get("$type") or ""):
            return True
        return any(_contains_type(value, type_fragment) for value in node.values())
    if isinstance(node, list):
        return any(_contains_type(item, type_fragment) for item in node)
    return False
