from pathlib import Path

from fzastro_ai.dev_agent.project_scanner import scan_project


def test_scan_project_ignores_generated_and_backup_files(tmp_path: Path):
    (tmp_path / "fzastro_ai").mkdir()
    (tmp_path / "fzastro_ai" / "app.py").write_text(
        "class App:\n    pass\n", encoding="utf-8"
    )
    (tmp_path / "fzastro_ai" / "app.py.bak").write_text("backup", encoding="utf-8")
    (tmp_path / "fzastro_ai" / "__pycache__").mkdir()
    (tmp_path / "fzastro_ai" / "__pycache__" / "app.pyc").write_bytes(b"pyc")
    (tmp_path / "README.md").write_text("# Demo", encoding="utf-8")

    scan = scan_project(tmp_path)
    paths = {item.path for item in scan.files}

    assert "fzastro_ai/app.py" in paths
    assert "README.md" in paths
    assert "fzastro_ai/app.py.bak" not in paths
    assert all("__pycache__" not in path for path in paths)
    assert scan.python_count == 1


def test_scan_project_extracts_python_symbols(tmp_path: Path):
    (tmp_path / "fzastro_ai").mkdir()
    (tmp_path / "fzastro_ai" / "worker.py").write_text(
        "import os\n\nclass Worker:\n    def run(self):\n        return os.getcwd()\n",
        encoding="utf-8",
    )

    scan = scan_project(tmp_path)
    file = scan.files[0]

    assert file.role == "worker"
    assert "Worker" in file.symbols
    assert "run" in file.symbols
    assert "os" in file.imports


def test_scan_project_ignores_nested_git_workspace(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "fzastro_ai").mkdir()
    (tmp_path / "fzastro_ai" / "app.py").write_text("print('main')\n", encoding="utf-8")
    nested = tmp_path / "other_project"
    nested.mkdir()
    (nested / ".git").mkdir()
    (nested / "secret.py").write_text("TOKEN = 'do-not-index'\n", encoding="utf-8")

    scan = scan_project(tmp_path)
    paths = {item.path for item in scan.files}

    assert "fzastro_ai/app.py" in paths
    assert "other_project/secret.py" not in paths
