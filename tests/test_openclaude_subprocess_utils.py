import os

from fzastro_ai.dev_agent.subprocess_utils import hidden_subprocess_kwargs


def test_hidden_subprocess_kwargs_are_platform_safe():
    kwargs = hidden_subprocess_kwargs()

    if os.name == "nt":
        assert "startupinfo" in kwargs
        assert "creationflags" in kwargs
    else:
        assert kwargs == {}


def test_openclaude_subprocess_helpers_are_used_for_dev_helper_processes():
    root = os.path.dirname(os.path.dirname(__file__))
    rel_paths = [
        "fzastro_ai/dev_agent/git_tools.py",
        "fzastro_ai/dev_agent/project_scanner.py",
        "fzastro_ai/dev_agent/test_runner.py",
        "fzastro_ai/dev_agent/patch_applier.py",
        "fzastro_ai/dev_agent/openclaude_bridge.py",
    ]
    for rel in rel_paths:
        text = open(os.path.join(root, rel), encoding="utf-8").read()
        assert "hidden_subprocess_kwargs" in text
