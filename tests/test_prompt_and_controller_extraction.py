import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_core_prompt_lives_outside_app_module():
    app_text = (PROJECT_ROOT / "fzastro_ai" / "app.py").read_text(encoding="utf-8")
    prompts_text = (PROJECT_ROOT / "fzastro_ai" / "prompts.py").read_text(
        encoding="utf-8"
    )

    assert "from .prompts import DEFAULT_CORE_SYSTEM_PROMPT" in app_text
    assert "self.system_prompt.setPlainText(DEFAULT_CORE_SYSTEM_PROMPT)" in app_text
    assert "DEFAULT_CORE_SYSTEM_PROMPT" in prompts_text
    assert "PRIORITY AND TRUTH GATE" in prompts_text
    assert "PRIORITY AND TRUTH GATE" not in app_text


def test_shutdown_controller_extracted_from_main_window():
    app_path = PROJECT_ROOT / "fzastro_ai" / "app.py"
    controller_path = (
        PROJECT_ROOT / "fzastro_ai" / "controllers" / "shutdown_controller.py"
    )
    app_tree = ast.parse(app_path.read_text(encoding="utf-8"))
    app_class = next(
        node
        for node in app_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "FZAstroAI"
    )

    assert "ShutdownControllerMixin" in [ast.unparse(base) for base in app_class.bases]
    assert not any(
        isinstance(item, ast.FunctionDef) and item.name == "closeEvent"
        for item in app_class.body
    )

    controller_text = controller_path.read_text(encoding="utf-8")
    assert "class ShutdownControllerMixin" in controller_text
    assert "def closeEvent" in controller_text
    assert "save_persistent_memory" in controller_text


def test_document_knowledge_library_was_extracted_from_app_module_source():
    app_source = Path("fzastro_ai/app.py").read_text(encoding="utf-8")
    library_source = Path("fzastro_ai/knowledge_library.py").read_text(encoding="utf-8")

    assert "class DocumentKnowledgeLibrary" not in app_source
    assert "from .knowledge_library import DocumentKnowledgeLibrary" in app_source
    assert "class DocumentKnowledgeLibrary" in library_source


def test_legacy_shutdown_controller_import_shim_remains_available():
    import pytest

    pytest.importorskip("PySide6.QtCore")

    namespace = {}
    exec(
        "from fzastro_ai.shutdown_controller import ShutdownControllerMixin",
        namespace,
    )
    assert namespace["ShutdownControllerMixin"].__name__ == "ShutdownControllerMixin"
