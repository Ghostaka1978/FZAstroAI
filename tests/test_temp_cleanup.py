from pathlib import Path

from fzastro_ai.temp_cleanup import FZASTRO_TEMP_DIR_NAMES, cleanup_fzastro_temp_dirs


def test_cleanup_fzastro_temp_dirs_removes_only_known_runtime_caches(tmp_path):
    for dir_name in FZASTRO_TEMP_DIR_NAMES:
        temp_dir = tmp_path / dir_name
        temp_dir.mkdir()
        (temp_dir / "artifact.tmp").write_text("cached", encoding="utf-8")

    unrelated = tmp_path / "not_fzastro"
    unrelated.mkdir()
    (unrelated / "keep.tmp").write_text("keep", encoding="utf-8")

    failed = cleanup_fzastro_temp_dirs(tmp_path)

    assert failed == []
    assert not any(
        (tmp_path / dir_name).exists() for dir_name in FZASTRO_TEMP_DIR_NAMES
    )
    assert unrelated.exists()
    assert (unrelated / "keep.tmp").exists()
