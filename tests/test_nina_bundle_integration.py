from pathlib import Path

from fzastro_ai.nina import nina_bridge


def test_nina_settings_round_trip(tmp_path):
    settings_path = tmp_path / "nina_integration.json"
    saved = nina_bridge.save_settings(
        {
            "executable_path": "C:/Tools/FZAstroImaging/FZAstroImaging.exe",
            "api_host": "127.0.0.1",
            "api_port": "1888",
            "installed_version": "3.2.1",
            "update_manifest_url": "https://example.invalid/manifest.json",
            "auto_check_updates": True,
            "auto_download_updates": False,
        },
        path=settings_path,
    )
    loaded = nina_bridge.load_settings(settings_path)

    assert saved["api_port"] == 1888
    assert loaded["executable_path"].endswith("FZAstroImaging.exe")
    assert loaded["auto_check_updates"] is True
    assert loaded["auto_download_updates"] is False


def test_nina_update_manifest_normalizes_and_compares(monkeypatch):
    def fake_read_url_json(url, timeout=10.0):
        assert url == "https://example.invalid/manifest.json"
        return {
            "version": "3.2.2-fzastro.1",
            "download_url": "https://example.invalid/FZAstroImaging.zip",
            "sha256": "",
            "release_notes": "Branded bundle update",
            "published_at": "2026-06-17",
        }

    monkeypatch.setattr(nina_bridge, "_read_url_json", fake_read_url_json)
    info = nina_bridge.check_for_update(
        {
            "installed_version": "3.2.1",
            "update_manifest_url": "https://example.invalid/manifest.json",
        }
    )

    assert info is not None
    assert info.version == "3.2.2-fzastro.1"
    assert info.is_newer is True
    assert info.has_download is True


def test_nina_bridge_supports_github_latest_release_payload(monkeypatch):
    def fake_read_url_json(url, timeout=10.0):
        return {
            "tag_name": "v3.3.0",
            "body": "Release body",
            "assets": [
                {
                    "name": "notes.txt",
                    "browser_download_url": "https://example.invalid/notes.txt",
                },
                {
                    "name": "FZAstroImaging-3.3.0.zip",
                    "browser_download_url": "https://example.invalid/FZAstroImaging.zip",
                },
            ],
        }

    monkeypatch.setattr(nina_bridge, "_read_url_json", fake_read_url_json)
    info = nina_bridge.check_for_update(
        {
            "installed_version": "3.2.9",
            "update_manifest_url": "https://api.github.com/repos/example/fzastro-imaging/releases/latest",
        }
    )

    assert info is not None
    assert info.version == "v3.3.0"
    assert info.download_url.endswith("FZAstroImaging.zip")
    assert info.release_notes == "Release body"


def test_fzastro_app_has_nina_top_bar_integration(project_root: Path):
    app_text = (project_root / "fzastro_ai" / "app.py").read_text(encoding="utf-8-sig")
    actions_text = (project_root / "fzastro_ai" / "actions" / "__init__.py").read_text(
        encoding="utf-8-sig"
    )

    assert "NinaActionsMixin" in actions_text
    assert 'self.nina_control_button = QPushButton("N.I.N.A.")' in app_text
    assert "cockpitNinaGroup" in app_text
    assert "self.maybe_auto_check_nina_updates()" in app_text


def test_launch_sequence_file_passes_generated_plan_to_executable(
    tmp_path, monkeypatch
):
    sequence = tmp_path / "M13.nina-sequence.json"
    sequence.write_text("{}", encoding="utf-8")
    exe = tmp_path / "FZAstroImaging.exe"
    exe.write_text("", encoding="utf-8")

    calls = []

    class FakeProcess:
        pass

    def fake_popen(args, cwd=None):
        calls.append((args, cwd))
        return FakeProcess()

    monkeypatch.setattr(nina_bridge.subprocess, "Popen", fake_popen)

    result = nina_bridge.launch_sequence_file(sequence, executable_path=exe)

    assert result.launched is True
    assert result.open_attempted is True
    assert result.sequence_path == str(sequence)
    assert calls == [([str(exe), str(sequence)], str(tmp_path))]


def test_latest_sequence_file_returns_newest_generated_plan(tmp_path):
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    old = old_dir / "old.nina-sequence.json"
    new = new_dir / "new.nina-sequence.json"
    old.write_text("{}", encoding="utf-8")
    new.write_text("{}", encoding="utf-8")
    old_mtime = 1_700_000_000
    new_mtime = 1_700_000_100
    import os

    os.utime(old, (old_mtime, old_mtime))
    os.utime(new, (new_mtime, new_mtime))

    assert nina_bridge.latest_sequence_file(tmp_path) == new
