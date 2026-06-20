import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_web_companion_files_exist():
    expected = [
        "fzastro_ai/web_companion/__init__.py",
        "fzastro_ai/web_companion/__main__.py",
        "fzastro_ai/web_companion/server.py",
        "fzastro_ai/web_companion/launcher.py",
        "fzastro_ai/web_companion/static/index.html",
        "docs/WEB_COMPANION.md",
        "scripts/run_web_companion.ps1",
    ]

    for relative_path in expected:
        assert (PROJECT_ROOT / relative_path).exists(), relative_path


def test_web_companion_python_files_are_parseable():
    for relative_path in [
        "fzastro_ai/web_companion/__init__.py",
        "fzastro_ai/web_companion/__main__.py",
        "fzastro_ai/web_companion/server.py",
        "fzastro_ai/web_companion/launcher.py",
    ]:
        path = PROJECT_ROOT / relative_path
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_package_import_stays_web_companion_lazy():
    package_init = (PROJECT_ROOT / "fzastro_ai" / "__init__.py").read_text(
        encoding="utf-8-sig"
    )

    assert "web_companion" not in package_init
    assert "fastapi" not in package_init.casefold()
    assert "uvicorn" not in package_init.casefold()


def test_requirements_include_web_companion_dependencies():
    requirements = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert "fastapi" in requirements
    assert "uvicorn" in requirements


def test_web_companion_documents_safe_lan_token():
    docs = (PROJECT_ROOT / "docs" / "WEB_COMPANION.md").read_text(encoding="utf-8")
    runner = (PROJECT_ROOT / "scripts" / "run_web_companion.ps1").read_text(
        encoding="utf-8"
    )

    assert "FZASTRO_WEB_TOKEN" in docs
    assert "Do not expose this directly to the public internet" in docs
    assert "Write-Warning" in runner


def test_web_companion_request_annotation_imports_are_eager():
    server = (PROJECT_ROOT / "fzastro_ai" / "web_companion" / "server.py").read_text(
        encoding="utf-8"
    )

    assert "from __future__ import annotations" in server
    assert (
        "from fastapi import Depends, FastAPI, Header, HTTPException, Request, status"
        in server
    )
    assert "    from fastapi import" not in server


def test_desktop_keeps_manual_web_only_launch_path():
    runner = (PROJECT_ROOT / "scripts" / "run_web_companion.ps1").read_text(
        encoding="utf-8"
    )
    launcher = (
        PROJECT_ROOT / "fzastro_ai" / "web_companion" / "launcher.py"
    ).read_text(encoding="utf-8")

    assert "python.exe" in runner
    assert "-m fzastro_ai.web_companion" in runner
    assert "already running externally/manual" in launcher
    assert "will not stop it" in launcher


def test_desktop_config_panel_controls_web_companion():
    app = (PROJECT_ROOT / "fzastro_ai" / "app.py").read_text(encoding="utf-8")
    state_controller = (
        PROJECT_ROOT / "fzastro_ai" / "controllers" / "app_state_controller.py"
    ).read_text(encoding="utf-8")

    assert "Web Companion" in app
    assert "Start Local Web Server" in app
    assert "Start LAN / iPad Mode" in app
    assert "Auto-start local server with desktop" in app
    assert "web_companion_settings.json" in state_controller
    assert "AppStateController" in app
    assert "QTimer.singleShot(750, self.start_web_companion_background)" in app
    assert 'if self.web_companion_settings.get("auto_start_desktop")' in app


def test_web_companion_polished_ui_routes_and_layout():
    html = (
        PROJECT_ROOT / "fzastro_ai" / "web_companion" / "static" / "index.html"
    ).read_text(encoding="utf-8")
    server = (PROJECT_ROOT / "fzastro_ai" / "web_companion" / "server.py").read_text(
        encoding="utf-8"
    )

    assert "control-panel" in html
    assert "Advanced runtime" in html
    assert "Runtime base URL" not in html
    assert "Daily News Brief" in html
    assert "/api/news/daily" in html
    assert "weatherBtn" in html
    assert "marketsBtn" in html
    assert "renderTable" in html
    assert "markdownToHtml(finalText)" in html
    assert "with_image: true" in html
    assert "/api/assets/file" in html
    assert "asset_file" in server
    assert "daily_news_endpoint" in server
    assert "_web_chat_direct_tool_response" in server
    assert "detect_deterministic_tool_plan" in server
    assert "fetch_7timer_astro_forecast" in server
    assert "plan_targets" in server
    assert "_format_web_seeing_result" in server
    assert "_format_web_targets_result" in server
    assert "index_path.read_text" in server


def test_desktop_web_companion_lan_url_copy_is_exposed():
    app = (PROJECT_ROOT / "fzastro_ai" / "app.py").read_text(encoding="utf-8")
    launcher = (
        PROJECT_ROOT / "fzastro_ai" / "web_companion" / "launcher.py"
    ).read_text(encoding="utf-8")

    assert "Copy LAN/iPad URL" in app
    assert "copy_web_companion_lan_url" in app
    assert "URL copied to clipboard" in app
    assert "lan_web_url" in launcher
    assert "detect_lan_ip" in launcher


def test_desktop_web_companion_status_uses_color_state():
    app = (PROJECT_ROOT / "fzastro_ai" / "app.py").read_text(encoding="utf-8")
    styles = (PROJECT_ROOT / "fzastro_ai" / "ui" / "styles.py").read_text(
        encoding="utf-8"
    )

    assert "set_web_companion_visual_state" in app
    assert 'setProperty("webState", "off")' in app
    assert 'widget.setProperty("webState", clean_state)' in app
    assert 'visual_state = "on" if status.owned else "external"' in app
    assert 'QPushButton#cockpitWebButton[webState="on"]' in styles
    assert 'QPushButton#cockpitWebButton[webState="off"]' in styles
    assert 'QLabel#webArticleBody[webState="on"]' in styles
    assert 'QLabel#webArticleBody[webState="off"]' in styles
