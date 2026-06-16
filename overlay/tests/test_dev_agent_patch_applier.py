from pathlib import Path

from fzastro_ai.dev_agent.patch_applier import changed_paths_from_patch, create_patch_snapshot


def test_changed_paths_from_patch_extracts_a_b_paths():
    patch = """--- a/fzastro_ai/app.py
+++ b/fzastro_ai/app.py
@@ -1 +1 @@
-old
+new
--- /dev/null
+++ b/fzastro_ai/dev_agent/new_file.py
@@ -0,0 +1 @@
+ok
"""

    assert changed_paths_from_patch(patch) == (
        "fzastro_ai/app.py",
        "fzastro_ai/dev_agent/new_file.py",
    )


def test_create_patch_snapshot_backs_up_existing_files(tmp_path: Path):
    source = tmp_path / "fzastro_ai" / "app.py"
    source.parent.mkdir()
    source.write_text("old", encoding="utf-8")

    snapshot = create_patch_snapshot(
        tmp_path,
        ("fzastro_ai/app.py", "fzastro_ai/new.py"),
        patch_text="patch",
        label="unit test",
    )

    snapshot_dir = Path(snapshot.directory)
    assert (snapshot_dir / "patch.diff").read_text(encoding="utf-8") == "patch"
    assert (snapshot_dir / "backups" / "fzastro_ai" / "app.py").read_text(encoding="utf-8") == "old"
    assert (snapshot_dir / "manifest.json").exists()
