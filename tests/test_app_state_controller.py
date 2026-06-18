import json

from fzastro_ai.controllers.app_state_controller import AppStateController


def test_app_state_controller_loads_and_saves_web_companion_settings(tmp_path):
    controller = AppStateController(tmp_path)

    assert controller.load_web_companion_settings() == {"auto_start_desktop": False}

    controller.save_web_companion_settings({"auto_start_desktop": True})

    assert json.loads(
        (tmp_path / "web_companion_settings.json").read_text(encoding="utf-8")
    ) == {"auto_start_desktop": True}
    assert list(tmp_path.glob("*.tmp")) == []


def test_app_state_controller_preserves_corrupt_web_companion_settings(tmp_path):
    settings_file = tmp_path / "web_companion_settings.json"
    settings_file.write_text("{not valid json", encoding="utf-8")

    controller = AppStateController(tmp_path)

    assert controller.load_web_companion_settings() == {"auto_start_desktop": False}
    assert not settings_file.exists()
    corrupt_files = list(tmp_path.glob("web_companion_settings.corrupt-*.json"))
    assert len(corrupt_files) == 1
    assert corrupt_files[0].read_text(encoding="utf-8") == "{not valid json"
