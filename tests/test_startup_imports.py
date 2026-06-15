from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_package_init_does_not_import_old_worker_locations():
    package_init = PROJECT_ROOT / "fzastro_ai" / "__init__.py"
    text = package_init.read_text(encoding="utf-8-sig")
    assert "from .chat_worker import ChatWorker" not in text
    assert "from .workers import ChatWorker" not in text


def test_worker_exports_match_current_module_layout():
    workers_init = (PROJECT_ROOT / "fzastro_ai" / "workers" / "__init__.py").read_text(
        encoding="utf-8-sig"
    )
    memory_worker = (
        PROJECT_ROOT / "fzastro_ai" / "workers" / "memory_extraction_worker.py"
    ).read_text(encoding="utf-8-sig")

    assert "from .chat_worker import ChatWorker" in workers_init
    assert (
        "from .memory_extraction_worker import MemoryExtractionWorker" in workers_init
    )
    assert "class MemoryExtractionWorker" in memory_worker


def test_package_import_smoke_without_ui_dependencies():
    import fzastro_ai

    assert getattr(fzastro_ai, "__version__")


def test_app_module_does_not_import_optional_web_providers_at_module_load():
    app_text = (PROJECT_ROOT / "fzastro_ai" / "app.py").read_text(encoding="utf-8-sig")

    forbidden_imports = [
        "from bs4 import BeautifulSoup",
        "from ddgs import DDGS",
        "from playwright.sync_api import sync_playwright",
        "import openpyxl",
        "from PyPDF2 import PdfReader",
    ]

    for import_line in forbidden_imports:
        assert import_line not in app_text.split("from .config import", 1)[0]


def test_network_modules_keep_optional_parsers_lazy():
    news_text = (PROJECT_ROOT / "fzastro_ai" / "news_tools.py").read_text(
        encoding="utf-8-sig"
    )
    web_text = (PROJECT_ROOT / "fzastro_ai" / "web_tools.py").read_text(
        encoding="utf-8-sig"
    )

    assert (
        "from bs4 import BeautifulSoup"
        not in news_text.split("def fetch_daily_news_section", 1)[0]
    )
    assert "from ddgs import DDGS" not in web_text.split("def perform_web_search", 1)[0]
    assert (
        "from playwright.sync_api import sync_playwright"
        not in web_text.split("def _load_pixmap", 1)[0]
    )


def test_app_uses_source_root_for_resource_path_in_source_mode():
    app_text = (PROJECT_ROOT / "fzastro_ai" / "app.py").read_text(encoding="utf-8-sig")

    assert 'getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])' in app_text
    assert 'os.path.abspath(".")' not in app_text


def test_startup_model_discovery_is_not_synchronous_in_ui_constructor():
    app_text = (PROJECT_ROOT / "fzastro_ai" / "app.py").read_text(encoding="utf-8-sig")
    model_controls_text = (PROJECT_ROOT / "fzastro_ai" / "model_controls.py").read_text(
        encoding="utf-8-sig"
    )

    assert "self.model_box.addItems([DEFAULT_MODEL_NAME])" in app_text
    assert "ModelDiscoveryWorker" in model_controls_text
    assert "worker.start()" in model_controls_text
    assert "self.model_box.addItems(get_available_models())" not in app_text


def test_markdown_link_opening_restricts_external_schemes():
    widget_text = (PROJECT_ROOT / "fzastro_ai" / "ui" / "message_widgets.py").read_text(
        encoding="utf-8-sig"
    )

    assert 'scheme not in {"http", "https", "mailto"}' in widget_text
    assert 'scheme == "fzastro"' in widget_text
    assert "QDesktopServices.openUrl(QUrl(url_text))" in widget_text


def test_model_selector_can_display_unavailable_provider_without_losing_model_id():
    model_controls_text = (PROJECT_ROOT / "fzastro_ai" / "model_controls.py").read_text(
        encoding="utf-8-sig"
    )
    app_text = (PROJECT_ROOT / "fzastro_ai" / "app.py").read_text(encoding="utf-8-sig")

    assert "current_model_name" in model_controls_text
    assert "currentData(Qt.UserRole)" in model_controls_text
    assert "status_message=status_message" in model_controls_text
    assert "selector_enabled=False" in model_controls_text
    assert "current_model_name = _current_model_name" in app_text
