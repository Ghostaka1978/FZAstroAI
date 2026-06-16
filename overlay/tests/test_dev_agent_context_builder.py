from pathlib import Path

from fzastro_ai.dev_agent.context_builder import build_dev_context
from fzastro_ai.dev_agent.task_classifier import classify_dev_task


def test_classify_dev_task_detects_patch_and_role_hints():
    task = classify_dev_task("Fix the SEEING planner score button in the UI")

    assert task.mode == "patch"
    assert "ui" in task.role_hints
    assert "astro_tools" in task.role_hints


def test_build_context_selects_relevant_files(tmp_path: Path):
    (tmp_path / "fzastro_ai" / "ui").mkdir(parents=True)
    (tmp_path / "fzastro_ai" / "astro_tools").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "fzastro_ai" / "ui" / "seeing_dialog.py").write_text(
        "class SeeingDialog:\n    def score_clouds(self):\n        return 1\n",
        encoding="utf-8",
    )
    (tmp_path / "fzastro_ai" / "astro_tools" / "seeing_data.py").write_text(
        "def load_seeing():\n    return {}\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_seeing_data.py").write_text(
        "def test_seeing():\n    assert True\n",
        encoding="utf-8",
    )

    context = build_dev_context(tmp_path, "Fix seeing cloud scoring in seeing_dialog.py")
    paths = [file.path for file in context.files]

    assert "fzastro_ai/ui/seeing_dialog.py" in paths
    assert context.task.mode == "patch"
    assert "Developer Workbench Context" in context.prompt_package
