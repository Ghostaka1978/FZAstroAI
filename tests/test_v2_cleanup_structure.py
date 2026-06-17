from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_overlay_was_integrated_not_kept_as_root_bundle():
    assert not (PROJECT_ROOT / "overlay").exists()
    assert (PROJECT_ROOT / "fzastro_ai" / "dev_agent" / "project_scanner.py").exists()
    assert (PROJECT_ROOT / "fzastro_ai" / "ui" / "dev_workbench_dialog.py").exists()
    assert (PROJECT_ROOT / "fzastro_ai" / "actions" / "dev_actions.py").exists()


def test_stale_bundle_readmes_are_consolidated():
    stale = [
        "README_ATTACHMENT_CONTEXT_BUNDLE.md",
        "README_DEV_WORKBENCH_BUNDLE.md",
        "README_TARGETS_PATCH.md",
        "README_WEB_COMPANION.md",
    ]
    for name in stale:
        assert not (PROJECT_ROOT / name).exists(), name
    assert (PROJECT_ROOT / "docs" / "WEB_COMPANION.md").exists()
    assert (PROJECT_ROOT / "docs" / "AI_DEVELOPER_WORKBENCH.md").exists()
    assert (PROJECT_ROOT / "docs" / "PROJECT_OVERVIEW.md").exists()


def test_dev_workbench_is_wired_into_app_source():
    app = (PROJECT_ROOT / "fzastro_ai" / "app.py").read_text(encoding="utf-8")
    actions = (PROJECT_ROOT / "fzastro_ai" / "actions" / "__init__.py").read_text(
        encoding="utf-8"
    )
    assert "DevActionsMixin" in app
    assert "self.dev_workbench_button" in app
    assert "open_dev_workbench" in app
    assert "DevActionsMixin" in actions
