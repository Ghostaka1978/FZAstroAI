from __future__ import annotations


def test_top_level_project_scanner_compat_imports():
    from fzastro_ai.project_scanner import ProjectFile, ProjectScan, scan_project

    assert ProjectFile is not None
    assert ProjectScan is not None
    assert callable(scan_project)


def test_top_level_safety_compat_imports():
    from fzastro_ai.safety import DevAgentSafetyError, resolve_project_path

    assert issubclass(DevAgentSafetyError, Exception)
    assert callable(resolve_project_path)


def test_chat_file_tools_remains_attachment_extractor():
    from fzastro_ai.file_tools import extract_file_text

    assert callable(extract_file_text)
