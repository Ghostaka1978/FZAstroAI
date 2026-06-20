from pathlib import Path
import os

from fzastro_ai.dev_agent.openclaude_bridge import OpenClaudeLaunchConfig
from fzastro_ai.dev_agent.openclaude_embedded_terminal import (
    EmbeddedTerminalSupport,
    build_openclaude_embedded_command,
    command_to_cmdline,
    format_embedded_terminal_status,
    get_embedded_terminal_support,
)
import fzastro_ai.dev_agent.openclaude_embedded_terminal as embedded


def make_fzastro_root(tmp_path: Path) -> Path:
    root = tmp_path / "FZAstroAI"
    (root / "fzastro_ai").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "main.py").write_text("print('ok')\n", encoding="utf-8")
    return root


def make_fake_command(bin_dir: Path, name: str) -> None:
    command = bin_dir / name
    command.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    command.chmod(0o755)


def test_embedded_terminal_support_is_optional_on_non_windows():
    support = get_embedded_terminal_support()

    if support.supported:
        assert support.backend == "pywinpty-conpty"
    else:
        assert support.backend in {"external-terminal", "missing-pywinpty"}
        assert support.reason


def test_embedded_command_uses_selected_model_and_openclaude_path(
    tmp_path, monkeypatch
):
    root = make_fzastro_root(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("node", "npm", "openclaude"):
        make_fake_command(bin_dir, name)

    monkeypatch.setattr(
        embedded,
        "get_embedded_terminal_support",
        lambda: EmbeddedTerminalSupport(True, "pywinpty-conpty", "ready"),
    )
    config = OpenClaudeLaunchConfig(
        project_root=root,
        model="rafw007/qwen36-a3b-claude-coder:latest",
        base_url="http://localhost:11434/v1",
        api_key="ollama",
    )

    command = build_openclaude_embedded_command(
        config,
        env={"PATH": str(bin_dir), "APPDATA": str(tmp_path / "AppData")},
    )

    assert command.cwd == root.resolve()
    if os.name == "nt":
        assert command.command[0].lower().endswith("powershell.exe")
        assert "-File" in command.command
        assert any(
            str(part).endswith("run_openclaude_companion.ps1")
            for part in command.command
        )
    else:
        assert command.command[0].endswith("openclaude")
    assert command.env["OPENAI_MODEL"] == "rafw007/qwen36-a3b-claude-coder:latest"
    assert command.env["OPENAI_BASE_URL"] == "http://localhost:11434/v1"
    assert command.support.backend == "pywinpty-conpty"


def test_command_to_cmdline_quotes_paths():
    cmdline = command_to_cmdline((r"C:\Program Files\nodejs\openclaude.cmd", "--help"))

    assert "openclaude.cmd" in cmdline
    assert "--help" in cmdline
    assert cmdline.startswith('"')


def test_embedded_status_mentions_fallback(tmp_path, monkeypatch):
    root = make_fzastro_root(tmp_path)
    monkeypatch.setattr(
        embedded,
        "get_embedded_terminal_support",
        lambda: EmbeddedTerminalSupport(
            False, "missing-pywinpty", "pywinpty missing", "pip install pywinpty"
        ),
    )
    config = OpenClaudeLaunchConfig(project_root=root, model="qwen3:32b")

    status = format_embedded_terminal_status(config)

    assert "Embedded OpenClaude Terminal" in status
    assert "missing-pywinpty" in status
    assert "setup/build/deploy" in status
    assert "pip install pywinpty" in status
