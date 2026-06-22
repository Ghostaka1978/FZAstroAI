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
    assert "ToolDecisionWorker" in workers_init
    assert "WebDecisionWorker" in workers_init
    assert "class MemoryExtractionWorker" in memory_worker


def test_legacy_root_worker_modules_are_only_compatibility_wrappers():
    legacy_modules = [
        "astro_worker.py",
        "chat_worker.py",
        "command_router.py",
        "document_import_worker.py",
        "document_maintenance_worker.py",
        "gpu_monitor_worker.py",
        "memory_extraction_worker.py",
        "model_discovery_worker.py",
        "python_execution_worker.py",
        "seeing_worker.py",
        "solar_map_worker.py",
        "sun_now_worker.py",
        "web_decision_worker.py",
        "web_search_worker.py",
    ]

    for module_name in legacy_modules:
        text = (PROJECT_ROOT / "fzastro_ai" / module_name).read_text(
            encoding="utf-8-sig"
        )
        assert "Compatibility wrapper" in text
        assert "from .." not in text


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


def test_model_refresh_does_not_auto_start_local_ollama():
    worker_text = (
        PROJECT_ROOT / "fzastro_ai" / "workers" / "model_discovery_worker.py"
    ).read_text(encoding="utf-8-sig")
    model_controls_text = (PROJECT_ROOT / "fzastro_ai" / "model_controls.py").read_text(
        encoding="utf-8-sig"
    )

    assert "start_ollama_server_if_available" not in worker_text
    assert "should_auto_start_ollama" not in worker_text
    assert "Model refresh is intentionally read-only" in worker_text
    assert "is_local_ollama_listener_present" in worker_text
    assert (
        "not app_module.is_local_ollama_listener_present(base_url)"
        in model_controls_text
    )
    assert (
        "running = app_module.is_local_ollama_listener_present" in model_controls_text
    )
    assert "running = app_module.is_ollama_server_available" not in model_controls_text
    assert "OllamaRestartWorker" in model_controls_text


def test_web_model_refresh_does_not_auto_start_local_ollama():
    server_text = (
        PROJECT_ROOT / "fzastro_ai" / "web_companion" / "server.py"
    ).read_text(encoding="utf-8-sig")
    maybe_start_body = server_text.split("def _maybe_start_local_ollama", 1)[1].split(
        "_IMAGE_SUFFIXES", 1
    )[0]

    assert "start_ollama_server_if_available" not in maybe_start_body
    assert "should_auto_start_ollama" not in maybe_start_body
    assert "is_ollama_server_available" not in maybe_start_body
    assert "is_local_ollama_listener_present" in maybe_start_body
    assert "read-only status probe" in maybe_start_body
    assert "desktop power button" in maybe_start_body


def test_ollama_keep_alive_request_body_is_supported():
    request_builder = (
        PROJECT_ROOT / "fzastro_ai" / "llm" / "request_builder.py"
    ).read_text(encoding="utf-8-sig")
    chat_worker = (
        PROJECT_ROOT / "fzastro_ai" / "workers" / "chat_worker.py"
    ).read_text(encoding="utf-8-sig")
    app_text = (PROJECT_ROOT / "fzastro_ai" / "app.py").read_text(encoding="utf-8-sig")

    assert '"keep_alive"' in request_builder
    assert "normalize_ollama_keep_alive_value" in request_builder
    assert "self.keep_alive" in chat_worker
    assert "apply_ollama_model_keep_alive" in chat_worker
    assert "preload_ollama_model" in (
        PROJECT_ROOT / "fzastro_ai" / "runtime.py"
    ).read_text(encoding="utf-8-sig")
    assert "OllamaPreloadWorker" in (
        PROJECT_ROOT / "fzastro_ai" / "workers" / "__init__.py"
    ).read_text(encoding="utf-8-sig")
    assert "ollama_keep_alive_box" in app_text
    assert "current_ollama_keep_alive_value" in app_text
    assert "ollama_keep_alive_preloads_model" in app_text


def test_profile_menu_closed_state_uses_compact_icon_display():
    profile_text = (PROJECT_ROOT / "fzastro_ai" / "calibration_profiles.py").read_text(
        encoding="utf-8-sig"
    )
    app_text = (PROJECT_ROOT / "fzastro_ai" / "app.py").read_text(encoding="utf-8-sig")

    assert "{profile.get('icon')" in profile_text
    assert "{profile['name']} v" not in profile_text
    assert 'QPushButton("P ▾")' in app_text
    assert "self.profile_menu_button.setMenu(self.build_profile_menu())" in app_text
    assert "self.profile_menu_button.setText(" in profile_text
    assert "mode_menu_button" not in profile_text
    assert 'self.mode_menu_button = QPushButton("Mode ▾")' not in app_text
    assert "mode_group_layout.addWidget(self.mode_menu_button" not in app_text
    assert "QProgressDialog" in app_text


def test_shutdown_progress_and_llama_runner_cleanup_are_supported():
    shutdown_text = (
        PROJECT_ROOT / "fzastro_ai" / "controllers" / "shutdown_controller.py"
    ).read_text(encoding="utf-8-sig")
    runtime_text = (PROJECT_ROOT / "fzastro_ai" / "runtime.py").read_text(
        encoding="utf-8-sig"
    )

    assert "QProgressDialog" in shutdown_text
    assert "Stopping local Ollama and GPU runner" in shutdown_text
    assert "llama-server.exe" in runtime_text
    assert "is_local_ollama_process_present" in runtime_text
    assert "require_process_stop=force_process_stop" in runtime_text


def test_legacy_project_scanner_module_is_compatibility_wrapper():
    module_text = (PROJECT_ROOT / "fzastro_ai" / "project_scanner.py").read_text(
        encoding="utf-8-sig"
    )

    assert "Compatibility wrapper" in module_text
    assert "from .dev_agent.project_scanner import *" in module_text
    assert "from .." not in module_text


def test_legacy_project_scanner_import_exports_scan_project():
    from fzastro_ai.project_scanner import ProjectFile, ProjectScan, scan_project

    assert ProjectFile.__name__ == "ProjectFile"
    assert ProjectScan.__name__ == "ProjectScan"
    assert callable(scan_project)
