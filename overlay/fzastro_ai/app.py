import base64
import hashlib
import html
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import requests

from PySide6.QtCore import (
    QPoint,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QIcon,
    QKeyEvent,
    QKeySequence,
    QDesktopServices,
    QPainter,
    QPen,
    QPixmap,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .composer_actions import (
    CODE_MENU_GROUPS,
    COMPOSER_ACTION_BY_ID,
    LIBRARY_MENU_GROUPS,
    TEXT_ACTION_MENU_GROUPS,
    build_composer_action_prompt,
    composer_actions_by_group,
)
from .skill_registry import (
    SKILLS,
    SKILL_ACTION_BY_ID,
    SKILL_BY_ID,
    SkillAction,
    skill_actions_by_section,
)
from .config import (
    API_KEY,
    APP_DIR,
    APP_VERSION,
    APP_VERSION_LABEL,
    BASE_URL,
    CALIBRATION_PROFILES_FILE,
    CALIBRATION_PROFILE_SCHEMA_VERSION,
    DAILY_NEWS_BRIEF_ITEMS_PER_SECTION,
    DAILY_NEWS_CACHE_FILE,
    DAILY_NEWS_CACHE_MAX_AGE_SECONDS,
    DAILY_NEWS_MAX_ITEMS_PER_SECTION,
    DAILY_NEWS_RSS_TIMEOUT_SECONDS,
    DEFAULT_MODEL_NAME,
    HISTORY_FILE,
    KNOWLEDGE_ASSET_DIR,
    KNOWLEDGE_CHUNK_CHARS,
    KNOWLEDGE_CHUNK_OVERLAP,
    KNOWLEDGE_DB_FILE,
    KNOWLEDGE_EXHAUSTIVE_MAX_CONTEXT_CHARS,
    KNOWLEDGE_EXHAUSTIVE_MAX_RESULTS,
    KNOWLEDGE_MAX_CONTEXT_CHARS,
    KNOWLEDGE_MAX_OCR_CHARS_PER_PAGE,
    KNOWLEDGE_MAX_RESULTS,
    KNOWLEDGE_MAX_VISUALS_PER_REQUEST,
    KNOWLEDGE_MIN_TEXT_CHARS_FOR_PDF_PAGE,
    KNOWLEDGE_OCR_MAX_TOKEN_SHARE,
    KNOWLEDGE_OCR_MIN_CONFIDENCE,
    KNOWLEDGE_OCR_MIN_UNIQUE_TOKEN_RATIO,
    KNOWLEDGE_PDF_OCR_DPI,
    KNOWLEDGE_PDF_RENDER_DPI,
    KNOWLEDGE_VECTOR_DRAWING_THRESHOLD,
    LEGACY_MEMORY_FILE,
    LOG_DIR,
    LOG_FILE,
    MAX_MEMORY_CHARS,
    MAX_MEMORY_ENTRIES,
    MEMORY_CATEGORIES,
    MEMORY_CODE_CHUNK_CHARS,
    MEMORY_EXTRACTION_CHUNK_CHARS,
    MEMORY_EXTRACTION_CHUNK_OVERLAP,
    MEMORY_FILE,
    MEMORY_MAX_RESULTS,
    MEMORY_SCHEMA_VERSION,
    PYTHON_APPLICATION_CAPABILITY_PROMPT,
    PYTHON_AUTO_TEST_PROMPT,
    PYTHON_EXECUTION_MAX_OUTPUT_CHARS,
    PYTHON_EXECUTION_TIMEOUT_SECONDS,
    RUNTIME_MODEL_LIST_TIMEOUT_SECONDS,
    SOURCE_CODE_EXTENSIONS,
    SOURCE_CODE_LANGUAGE_BY_EXTENSION,
    WEB_IMAGE_CACHE_DIR,
    startup_gpu_monitor_enabled,
    startup_model_refresh_enabled,
)
from .controllers import ShutdownControllerMixin
from .logging_utils import log_exception, log_warning
from .prompts import DEFAULT_CORE_SYSTEM_PROMPT
from .knowledge_library import DocumentKnowledgeLibrary
from .runtime import (
    is_local_ollama_base_url,
    is_ollama_base_url,
    is_runtime_connection_error,
    make_runtime_client,
    normalize_runtime_api_key,
    normalize_runtime_base_url,
)

from .workers import (
    ChatWorker,
    DocumentKnowledgeImportWorker,
    DocumentKnowledgeMaintenanceWorker,
    GpuMonitorWorker,
    MemoryExtractionWorker,
    ModelDiscoveryWorker,
    OllamaRestartWorker,
    PythonExecutionWorker,
    WebDecisionWorker,
    WebSearchWorker,
    resolve_python_execution_interpreter,
)

from .ui.diagnostics_dialog import (
    build_diagnostics_report,
    format_path_for_diagnostics,
    open_diagnostics_window,
    open_local_path,
    read_recent_log_lines,
)
from .ui.help_dialog import open_help_cheat_sheet_dialog
from .ui.about_dialog import open_about_window
from .ui.llm_benchmark_dialog import open_llm_benchmark_dialog
from .ui.source_chips import add_source_header_widget
from .ui.styles import get_main_stylesheet
from .ui.main_layout import MainLayoutMixin
from .ui.attachment_controls import AttachmentControlsMixin


from .ui.message_widgets import (
    AttachmentChip,
    AutoHeightRichText,
    DropScrollArea,
    EnterSendTextEdit,
    ImagePreview,
    MessageWidget,
    SystemPromptTextEdit,
)

from .history_store import create_chat_record, load_chat_history, save_chat_history
from .ui.memory_dialog import (
    add_persistent_memory_entry as _add_persistent_memory_entry,
    clear_persistent_memory_library as _clear_persistent_memory_library,
    delete_selected_persistent_memory_entries as _delete_selected_persistent_memory_entries,
    edit_selected_persistent_memory_entry as _edit_selected_persistent_memory_entry,
    format_persistent_memory_item as _format_persistent_memory_item,
    open_persistent_memory_library as _open_persistent_memory_library,
    refresh_persistent_memory_list as _refresh_persistent_memory_list,
    save_persistent_memory_from_ui as _save_persistent_memory_from_ui,
    selected_persistent_memory_entry_ids as _selected_persistent_memory_entry_ids,
    show_persistent_memory_entry_editor as _show_persistent_memory_entry_editor,
    test_persistent_memory_search as _test_persistent_memory_search,
)
from .ui.history_panel import (
    build_history_memory_transcript as _build_history_memory_transcript,
    clear_all_history as _clear_all_history,
    clear_history_selection as _clear_history_selection,
    handle_history_selection_toggle as _handle_history_selection_toggle,
    history_message_to_text as _history_message_to_text,
    load_chat as _load_chat,
    render_history as _render_history,
    save_current_chat as _save_current_chat,
    toggle_history_panel as _toggle_history_panel,
    update_history_selection as _update_history_selection,
    update_history_selection_ui as _update_history_selection_ui,
)
from .ui.history_memory_review import (
    commit_history_memory as _commit_history_memory,
    finish_memory_extraction_worker as _finish_memory_extraction_worker,
    handle_memory_extraction_error as _handle_memory_extraction_error,
    handle_memory_extraction_ready as _handle_memory_extraction_ready,
    handle_memory_extraction_stopped as _handle_memory_extraction_stopped,
    remember_selected_history as _remember_selected_history,
    stop_memory_extraction as _stop_memory_extraction,
    update_memory_extraction_progress as _update_memory_extraction_progress,
)

from .calibration_profiles import (
    apply_calibration_profile as _apply_calibration_profile,
    create_calibration_profiles as _create_calibration_profiles,
    mark_custom_calibration as _mark_custom_calibration,
    persist_calibration_profile_store as _persist_calibration_profile_store,
    refresh_system_prompt_summary as _refresh_system_prompt_summary,
)
from .model_controls import (
    current_api_key as _current_api_key,
    current_base_url as _current_base_url,
    current_model_name as _current_model_name,
    refresh_models as _refresh_models,
    restart_ollama as _restart_ollama,
    refresh_workspace_context as _refresh_workspace_context,
    sync_runtime_client as _sync_runtime_client,
)
from .ui.calibration_dialog import (
    open_system_prompt_editor as _open_system_prompt_editor,
)

from .actions import (
    ChatLifecycleMixin,
    MarketActionsMixin,
    PythonActionsMixin,
    WebNewsActionsMixin,
    AstroActionsMixin,
    VoiceActionsMixin,
    DevActionsMixin,
)
from .file_tools import (
    IMAGE_FILE_EXTENSIONS,
    extract_file_text,
    file_to_data_url,
    has_image_attachments,
    prepare_content,
)

from .memory_store import (
    empty_calibration_profile_store,
    load_calibration_profile_store,
    save_calibration_profile_store,
    empty_persistent_memory,
    normalize_memory_entry,
    normalize_persistent_memory,
    load_persistent_memory,
    compact_memory_entry_for_context,
    _persistent_memory_query_terms,
    search_persistent_memory_entries,
    build_persistent_memory_context,
    parse_memory_extraction_payload,
    extract_news_article_entries,
    is_news_memory_section,
    remove_deterministic_news_sections,
    source_code_language_for_filename,
    make_fenced_code,
    preserve_source_attachments_for_memory,
    extract_fenced_code_blocks,
    split_code_for_memory,
    iter_history_transcript_messages,
    extract_history_code_entries,
    remove_deterministic_code_blocks,
)


from .market_sources import (
    _stock_number,
    _stock_market_state,
    _format_stock_epoch,
    _format_stock_quote_markdown,
    parse_stock_quote_payload,
    stock_quote_plain_text,
    _fetch_yahoo_stock_quote,
    _fetch_nasdaq_stock_quote,
    perform_stock_quote,
)

from .routing.source_tags import (
    normalize_response_source_tags,
    infer_response_source_tags,
    source_tags_tooltip,
    build_response_source_tags,
)

from .routing.intent_detection import (
    build_web_query as _routing_build_web_query,
    explicitly_or_contextually_references_documents as _routing_explicitly_or_contextually_references_documents,
    explicitly_requests_external_information as _routing_explicitly_requests_external_information,
    extract_last_python_code_block_from_text as _routing_extract_last_python_code_block_from_text,
    extract_python_code_from_text as _routing_extract_python_code_from_text,
    has_explicit_http_url as _routing_has_explicit_http_url,
    is_ambiguous_follow_up as _routing_is_ambiguous_follow_up,
    is_clearly_web_only_request as _routing_is_clearly_web_only_request,
    is_deterministic_url_tool_request as _routing_is_deterministic_url_tool_request,
    is_local_document_direct_request as _routing_is_local_document_direct_request,
    is_python_execution_request as _routing_is_python_execution_request,
    is_python_generate_and_test_request as _routing_is_python_generate_and_test_request,
    is_rendered_page_extraction_display_request as _routing_is_rendered_page_extraction_display_request,
    is_rendered_page_request as _routing_is_rendered_page_request,
    is_web_image_request as _routing_is_web_image_request,
    is_website_screenshot_request as _routing_is_website_screenshot_request,
    looks_like_python_code as _routing_looks_like_python_code,
    python_code_has_risky_auto_actions as _routing_python_code_has_risky_auto_actions,
    references_document_knowledge as _routing_references_document_knowledge,
    references_recent_image as _routing_references_recent_image,
)


from .news_tools import (
    daily_news_rss_map,
    load_daily_news_cache,
    save_daily_news_cache,
    fetch_daily_news_section,
    format_daily_news_context_from_sections,
    perform_daily_news_search,
)


from .ui.window_utils import apply_window_defaults

from .web_tools import (
    perform_web_search,
    perform_web_image_search,
    perform_website_screenshot,
    safe_markdown_link_label,
    download_rendered_page_image_previews,
    perform_rendered_page_extraction,
)


from .news_tools import (
    parse_news_sources,
    clean_daily_news_title,
    build_deterministic_daily_news_brief,
)


def resource_path(relative_path):
    # PyInstaller exposes sys._MEIPASS only inside a bundled executable.
    # In source-tree execution, resolve from the project root rather than the
    # current working directory so icons/resources still load from shortcuts,
    # tests, and alternate launch folders.
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return str(base_path / relative_path)


client = make_runtime_client(
    BASE_URL, API_KEY, timeout=RUNTIME_MODEL_LIST_TIMEOUT_SECONDS
)


def configure_runtime_client(base_url=None, api_key=None):
    global client
    client = make_runtime_client(
        base_url, api_key, timeout=RUNTIME_MODEL_LIST_TIMEOUT_SECONDS
    )
    return client


def get_available_models(base_url=None, api_key=None):
    try:
        runtime_client = (
            make_runtime_client(
                base_url, api_key, timeout=RUNTIME_MODEL_LIST_TIMEOUT_SECONDS
            )
            if base_url is not None or api_key is not None
            else client
        )
        response = runtime_client.models.list()
        models = [str(model.id).strip() for model in response.data if model.id]
        return models if models else [DEFAULT_MODEL_NAME]
    except Exception as exc:
        if is_runtime_connection_error(exc):
            log_warning("get_available_models provider unavailable", exc)
        else:
            log_exception("get_available_models", exc)
        return [DEFAULT_MODEL_NAME]


_MODEL_CAPABILITY_CACHE = {}
_MODEL_CONTEXT_LIMIT_CACHE = {}


def estimate_token_count(text):
    """Fast UI estimate for token budget display.

    Ollama's OpenAI-compatible stream does not reliably return live prompt and
    completion token counts for every local model, so the status bar uses the
    same practical approximation already used elsewhere in the app: roughly four
    characters per token. Treat this as a context-budget estimate, not an exact
    tokenizer measurement.
    """
    clean_text = str(text or "")

    if not clean_text:
        return 0

    return max(1, len(clean_text) // 4)


def format_token_budget_count(value):
    """Compact token count for the status bar."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return "?"

    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}m"

    if number >= 10_000:
        return f"{number / 1000:.1f}k"

    if number >= 1000:
        return f"{number / 1000:.2f}k"

    return str(max(0, number))


def estimate_model_content_tokens(content):
    """Estimate prompt tokens for string or OpenAI content-array messages."""
    if isinstance(content, list):
        total = 0

        for part in content:
            if not isinstance(part, dict):
                total += estimate_token_count(part)
                continue

            part_type = str(part.get("type") or "").strip().lower()

            if part_type in {"text", "input_text"}:
                total += estimate_token_count(part.get("text") or "")
            elif part_type in {"image", "image_url", "input_image"}:
                # Image-token cost differs by model and resolution. Use a small
                # fixed reserve so the context bar warns users that visual
                # requests are heavier without claiming exact tokenizer data.
                total += 1024
            else:
                total += estimate_token_count(json.dumps(part, ensure_ascii=False))

        return total

    return estimate_token_count(content)


def estimate_messages_context_tokens(messages):
    """Estimate total input-context tokens for the request sent to the model."""
    total = 0

    for message in messages or []:
        if not isinstance(message, dict):
            total += estimate_token_count(message)
            continue

        # Small per-message overhead for role separators / chat template tokens.
        total += 4
        total += estimate_token_count(message.get("role") or "")
        total += estimate_model_content_tokens(message.get("content") or "")

    return max(0, int(total))


def parse_ollama_context_limit(payload):
    """Extract configured or advertised context length from /api/show payload."""
    if not isinstance(payload, dict):
        return None

    # Prefer explicit Modelfile runtime setting because that is what the app will
    # actually use when no per-request num_ctx override is sent.
    for field_name in ("parameters", "modelfile"):
        field_text = str(payload.get(field_name) or "")

        for match in re.finditer(
            r"(?im)^\s*(?:PARAMETER\s+)?num_ctx\s+(?P<value>\d{3,9})\s*$",
            field_text,
        ):
            try:
                value = int(match.group("value"))
            except (TypeError, ValueError):
                continue

            if value > 0:
                return value

    candidates = []
    model_info = payload.get("model_info") or {}

    if isinstance(model_info, dict):
        for key, value in model_info.items():
            key_text = str(key or "").casefold()

            if "context_length" not in key_text and "context length" not in key_text:
                continue

            try:
                number = int(value)
            except (TypeError, ValueError):
                continue

            if number > 0:
                candidates.append(number)

    return max(candidates) if candidates else None


def get_ollama_model_context_limit(model_name, base_url=None):
    """Return estimated context-window size for an Ollama model, if available."""
    clean_model = str(model_name or "").strip()
    clean_base_url = normalize_runtime_base_url(base_url)
    cache_key = (clean_base_url, clean_model)

    if not clean_model:
        return None

    if cache_key in _MODEL_CONTEXT_LIMIT_CACHE:
        return _MODEL_CONTEXT_LIMIT_CACHE[cache_key]

    if not is_ollama_base_url(clean_base_url):
        _MODEL_CONTEXT_LIMIT_CACHE[cache_key] = None
        return None

    try:
        ollama_root = clean_base_url.rstrip("/").rsplit("/v1", 1)[0].rstrip("/")
        response = requests.post(
            f"{ollama_root}/api/show",
            json={"model": clean_model},
            timeout=3,
        )
        response.raise_for_status()
        context_limit = parse_ollama_context_limit(response.json())
    except Exception as exc:
        log_exception("get_ollama_model_context_limit line 4555", exc)
        context_limit = None

    _MODEL_CONTEXT_LIMIT_CACHE[cache_key] = context_limit
    return context_limit


def normalize_content_for_model(content, allow_images=True):
    """Normalize OpenAI content arrays for the target Ollama model.

    Text-only arrays are always flattened to a normal string. When the target
    model has no vision capability, historical image parts are replaced by a
    short placeholder so one old image cannot break every later text reply.
    """
    if not isinstance(content, list):
        return content

    text_parts = []
    contains_image = False

    for part in content:
        if not isinstance(part, dict):
            if allow_images:
                return content
            continue

        part_type = str(part.get("type") or "").strip().lower()

        if part_type in {"text", "input_text"}:
            text_parts.append(str(part.get("text") or ""))
            continue

        if part_type in {"image", "image_url", "input_image"}:
            contains_image = True
            continue

        if allow_images:
            return content

    if contains_image and allow_images:
        return content

    if contains_image:
        text_parts.append(
            "[An image was attached in this earlier message, but it is omitted "
            "from this request because the selected model does not support vision.]"
        )

    return "\n".join(value for value in text_parts if value).strip()


_QWEN_TEXT_ONLY_PREFIXES = (
    "qwen:",
    "qwen1",
    "qwen2",
    "qwen2.5",
    "qwen3",
)


def ollama_model_name_has_reliable_vision_hint(model_name):
    """Return True when the model name itself looks like a vision model.

    Ollama /api/show capabilities are the primary source, but some model
    wrappers can advertise vision too broadly.  For Qwen-family models, require
    an explicit VL marker so a text model such as qwen3:32b/qwen3.6:35b is not
    selected for image requests and left waiting forever before first token.
    """

    clean_name = str(model_name or "").strip().casefold()

    if not clean_name:
        return False

    reliable_markers = (
        "vision",
        "-vl",
        "_vl",
        ":vl",
        "vl:",
        "qwen3vl",
        "qwen2.5vl",
        "qwen2vl",
        "llava",
        "bakllava",
        "moondream",
        "minicpm-v",
        "minicpmv",
        "minicpm-o",
        "minicpmo",
        "gemma3",
        "gemma-3",
        "gemma4",
        "gemma-4",
        "granite3.2-vision",
        "granite-vision",
    )
    return any(marker in clean_name for marker in reliable_markers)


def ollama_model_name_is_qwen_text_only(model_name):
    """Return True for Qwen text-model names that should not inspect images."""

    clean_name = str(model_name or "").strip().casefold()

    if not clean_name:
        return False

    if "vl" in clean_name:
        return False

    return clean_name.startswith(_QWEN_TEXT_ONLY_PREFIXES)


def get_ollama_model_capabilities(model_name):
    """Return Ollama capabilities, or None when the local API is unavailable."""
    clean_model = str(model_name or "").strip()

    if not clean_model:
        return None

    if clean_model in _MODEL_CAPABILITY_CACHE:
        return _MODEL_CAPABILITY_CACHE[clean_model]

    try:
        active_base_url = str(getattr(client, "base_url", BASE_URL)).rstrip("/")

        if not is_ollama_base_url(active_base_url):
            return None

        ollama_root = active_base_url.rsplit("/v1", 1)[0].rstrip("/")
        response = requests.post(
            f"{ollama_root}/api/show",
            json={"model": clean_model},
            timeout=5,
        )
        response.raise_for_status()
        payload = response.json()
        capabilities = payload.get("capabilities") or []

        if isinstance(capabilities, str):
            capabilities = [capabilities]

        normalized = {
            str(value).strip().lower() for value in capabilities if str(value).strip()
        }

        if "vision" in normalized and ollama_model_name_is_qwen_text_only(clean_model):
            normalized = set(normalized)
            normalized.discard("vision")
            log_warning(
                "get_ollama_model_capabilities ignored unreliable vision capability",
                f"model={clean_model}",
            )

        _MODEL_CAPABILITY_CACHE[clean_model] = normalized
        return normalized
    except Exception as exc:
        log_exception("get_ollama_model_capabilities line 4646", exc)
        return None


def find_installed_vision_model(exclude_model=None):
    """Find an installed Ollama model that explicitly advertises vision."""
    excluded = str(exclude_model or "").strip()
    models = [
        str(model).strip() for model in get_available_models() if str(model).strip()
    ]

    vision_name_hints = (
        "vision",
        "qwen3-vl",
        "qwen2.5-vl",
        "qwen2-vl",
        "llava",
        "bakllava",
        "moondream",
        "minicpm-v",
        "gemma4",
        "gemma-4",
        "gemma3",
    )
    experimental_name_hints = (
        "abliterated",
        "uncensored",
        "uncen",
        "huihui",
    )

    models.sort(
        key=lambda name: (
            not any(hint in name.lower() for hint in vision_name_hints),
            any(hint in name.lower() for hint in experimental_name_hints),
            name.lower(),
        )
    )

    for model_name in models:
        if model_name == excluded:
            continue

        capabilities = get_ollama_model_capabilities(model_name)

        if capabilities is not None and "vision" in capabilities:
            if ollama_model_name_is_qwen_text_only(model_name):
                log_warning(
                    "find_installed_vision_model skipped Qwen text-only model",
                    f"model={model_name}",
                )
                continue

            return model_name

    return None


def is_experimental_vision_model(model_name):
    clean_name = str(model_name or "").strip().lower()
    return any(
        marker in clean_name
        for marker in ("abliterated", "uncensored", "uncen", "huihui")
    )


def make_microphone_icon(color="#e8ebef"):
    """Create a compact monochrome microphone icon for the composer button."""

    pixmap = QPixmap(28, 28)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)

    pen = QPen(QColor(color))
    pen.setWidth(2)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    painter.drawRoundedRect(QRectF(10.0, 4.0, 8.0, 14.0), 4.0, 4.0)
    painter.drawArc(QRectF(6.5, 10.0, 15.0, 11.0), 200 * 16, 140 * 16)
    painter.drawLine(14, 21, 14, 24)
    painter.drawLine(10, 24, 18, 24)
    painter.end()

    return QIcon(pixmap)


class FZAstroAI(
    ShutdownControllerMixin,
    AttachmentControlsMixin,
    MainLayoutMixin,
    ChatLifecycleMixin,
    PythonActionsMixin,
    MarketActionsMixin,
    WebNewsActionsMixin,
    AstroActionsMixin,
    VoiceActionsMixin,
    DevActionsMixin,
    QMainWindow,
):
    # History and persistent-memory UI methods are implemented in fzastro_ai.ui modules.
    format_persistent_memory_item = _format_persistent_memory_item
    refresh_persistent_memory_list = _refresh_persistent_memory_list
    save_persistent_memory_from_ui = _save_persistent_memory_from_ui
    open_persistent_memory_library = _open_persistent_memory_library
    test_persistent_memory_search = _test_persistent_memory_search
    show_persistent_memory_entry_editor = _show_persistent_memory_entry_editor
    add_persistent_memory_entry = _add_persistent_memory_entry
    selected_persistent_memory_entry_ids = _selected_persistent_memory_entry_ids
    edit_selected_persistent_memory_entry = _edit_selected_persistent_memory_entry
    delete_selected_persistent_memory_entries = (
        _delete_selected_persistent_memory_entries
    )
    clear_persistent_memory_library = _clear_persistent_memory_library
    save_current_chat = _save_current_chat
    load_chat = _load_chat
    render_history = _render_history
    handle_history_selection_toggle = _handle_history_selection_toggle
    update_history_selection = _update_history_selection
    update_history_selection_ui = _update_history_selection_ui
    clear_history_selection = _clear_history_selection
    history_message_to_text = _history_message_to_text
    build_history_memory_transcript = _build_history_memory_transcript
    clear_all_history = _clear_all_history
    toggle_history_panel = _toggle_history_panel
    remember_selected_history = _remember_selected_history
    update_memory_extraction_progress = _update_memory_extraction_progress
    stop_memory_extraction = _stop_memory_extraction
    handle_memory_extraction_stopped = _handle_memory_extraction_stopped
    finish_memory_extraction_worker = _finish_memory_extraction_worker
    handle_memory_extraction_error = _handle_memory_extraction_error
    handle_memory_extraction_ready = _handle_memory_extraction_ready
    commit_history_memory = _commit_history_memory
    # Calibration/settings/model-control methods are implemented in fzastro_ai modules.
    create_calibration_profiles = staticmethod(_create_calibration_profiles)
    persist_calibration_profile_store = _persist_calibration_profile_store
    apply_calibration_profile = _apply_calibration_profile
    mark_custom_calibration = _mark_custom_calibration
    refresh_system_prompt_summary = _refresh_system_prompt_summary
    open_system_prompt_editor = _open_system_prompt_editor
    refresh_workspace_context = _refresh_workspace_context
    current_base_url = _current_base_url
    current_api_key = _current_api_key
    current_model_name = _current_model_name
    sync_runtime_client = _sync_runtime_client
    refresh_models = _refresh_models
    restart_ollama = _restart_ollama

    def _format_path_for_diagnostics(self, path_value):
        return format_path_for_diagnostics(path_value)

    def _read_recent_log_lines(self, max_lines=80):
        return read_recent_log_lines(max_lines=max_lines)

    def _open_local_path(self, path_value):
        return open_local_path(self, path_value)

    def build_diagnostics_report(self):
        return build_diagnostics_report(self)

    def open_diagnostics_window(self):
        open_diagnostics_window(self)

    def open_help_cheat_sheet(self):
        open_help_cheat_sheet_dialog(self)

    def open_about_window(self):
        open_about_window(self)

    def open_llm_benchmark_dashboard(self):
        open_llm_benchmark_dialog(self)

    def open_project_repository(self):
        QDesktopServices.openUrl(QUrl("https://github.com/Ghostaka1978/FZAstroAI"))

    def _handle_brand_mark_click(self, event):
        if event.button() == Qt.LeftButton:
            self.open_project_repository()
            event.accept()
            return

        event.ignore()

    def __init__(self):
        super().__init__()

        self.setWindowIcon(QIcon(resource_path("favicon.ico")))
        self.setWindowTitle(APP_VERSION_LABEL)
        self.resize(1500, 950)
        self.setMinimumSize(1120, 720)
        apply_window_defaults(self)

        self.messages = []
        self.attached_files = []
        self.chat_history = load_chat_history()
        self.selected_history_ids = set()
        self.memory_worker = None
        self.model_discovery_worker = None
        self.model_provider_status_message = ""
        self._fzastro_owned_ollama_process = None
        self.memory_stop_button = None
        self.knowledge_worker = None
        self.knowledge_maintenance_worker = None
        self.knowledge_library = DocumentKnowledgeLibrary(KNOWLEDGE_DB_FILE)
        self.system_prompt_dialog = None
        self.system_prompt_editor = None
        self.system_prompt_editor_status = None
        self.system_prompt_character_label = None
        self.memory_dialog = None
        self.memory_list_widget = None
        self.memory_status_label = None
        self.memory_search_input = None
        self.memory_search_preview = None
        self.memory_add_button = None
        self.memory_edit_button = None
        self.memory_delete_button = None
        self.memory_clear_button = None
        self.memory_close_button = None
        self.knowledge_dialog = None
        self.knowledge_list_widget = None
        self.knowledge_status_label = None
        self.knowledge_current_status_text = ""
        self.knowledge_import_button = None
        self.knowledge_remove_button = None
        self.knowledge_clear_button = None
        self.knowledge_compact_button = None
        self.knowledge_close_button = None
        self.knowledge_search_input = None
        self.knowledge_search_preview = None
        self.pending_memory_source_records = []
        self.pending_memory_source_files = []
        self.active_chat_id = None
        self.current_stream_widget = None
        self.empty_state_widget = None
        self.current_assistant_message_id = None
        self.current_source_tags = []
        self.pending_python_auto_test = None
        self.last_tool_result = None
        self.current_prompt_context_tokens = 0
        self.current_context_limit_tokens = None
        self.current_generation_budget_tokens = 0
        self.pending_stream_text = ""
        self.current_prompt_context_tokens = 0
        self.current_context_limit_tokens = None
        self.current_generation_budget_tokens = 0
        self.last_stream_render = 0
        self.last_rendered_stream_text = ""
        self.current_generation_model = ""
        self.current_request_requires_vision = False
        self._next_no_token_log_at = 0.0
        self.stream_render_interval_ms = 100
        self.stream_render_timer = QTimer(self)
        self.stream_render_timer.setSingleShot(True)
        self.stream_render_timer.timeout.connect(self.render_pending_stream_message)
        self.response_char_count = 0
        self.worker = None
        self.ollama_restart_worker = None
        self.python_worker = None
        self.astro_worker = None
        self.voice_worker = None
        self.gpu_monitor = None
        self._busy_control_states = []
        self.stop_in_progress = False
        self.cancel_generation = False
        self.generation_timer = QTimer()
        self.generation_timer.timeout.connect(self.update_generation_timer)
        self.sidebar_visible = False

        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.sidebar = QWidget()
        self.sidebar.setFixedWidth(336)
        self.sidebar.setObjectName("sidebar")
        self.sidebar.hide()

        sidebar_root_layout = QVBoxLayout(self.sidebar)
        sidebar_root_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_root_layout.setSpacing(0)

        sidebar_header = QFrame()
        sidebar_header.setObjectName("sidebarHeader")
        sidebar_header_layout = QHBoxLayout(sidebar_header)
        sidebar_header_layout.setContentsMargins(18, 17, 16, 15)
        sidebar_header_layout.setSpacing(10)

        sidebar_mark = QLabel("FZ")
        sidebar_mark.setObjectName("sidebarBrandMark")
        sidebar_mark.setAlignment(Qt.AlignCenter)
        sidebar_mark.setFixedSize(36, 36)

        sidebar_title_box = QWidget()
        sidebar_title_layout = QVBoxLayout(sidebar_title_box)
        sidebar_title_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_title_layout.setSpacing(1)

        title = QLabel("Workspace")
        title.setObjectName("sidebarTitle")
        sidebar_subtitle = QLabel("Configuration & local knowledge")
        sidebar_subtitle.setObjectName("sidebarSubtitle")

        sidebar_title_layout.addWidget(title)
        sidebar_title_layout.addWidget(sidebar_subtitle)
        sidebar_header_layout.addWidget(sidebar_mark)
        sidebar_header_layout.addWidget(sidebar_title_box, 1)

        sidebar_root_layout.addWidget(sidebar_header)

        self.sidebar_scroll = QScrollArea()
        self.sidebar_scroll.setObjectName("sidebarConfigScroll")
        self.sidebar_scroll.setWidgetResizable(True)
        self.sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sidebar_scroll.setFrameShape(QFrame.NoFrame)

        sidebar_content = QWidget()
        sidebar_content.setObjectName("sidebarContent")
        sidebar_layout = QVBoxLayout(sidebar_content)
        sidebar_layout.setContentsMargins(14, 14, 14, 16)
        sidebar_layout.setSpacing(10)
        self.sidebar_scroll.setWidget(sidebar_content)
        sidebar_root_layout.addWidget(self.sidebar_scroll, 1)

        sidebar_footer = QLabel("FZASTRO AI  •  Local workstation")
        sidebar_footer.setObjectName("sidebarFooter")
        sidebar_footer.setAlignment(Qt.AlignCenter)
        sidebar_root_layout.addWidget(sidebar_footer)
        self.system_prompt = QTextEdit()
        self.system_prompt.setObjectName("systemPromptBox")
        self.system_prompt.setFixedHeight(120)
        self.system_prompt.setPlainText(DEFAULT_CORE_SYSTEM_PROMPT)

        self.core_system_prompt = self.system_prompt.toPlainText().strip()
        self.calibration_profile_store = load_calibration_profile_store()
        self.calibration_profiles = self.create_calibration_profiles(
            self.core_system_prompt
        )

        stored_profile_prompts = self.calibration_profile_store.get("profiles") or {}

        for profile_key, profile in self.calibration_profiles.items():
            profile["default_prompt"] = profile["prompt"]
            stored_profile = stored_profile_prompts.get(profile_key) or {}
            stored_prompt = str(stored_profile.get("prompt") or "").strip()

            if stored_prompt:
                profile["prompt"] = stored_prompt
                profile["updated_at"] = stored_profile.get("updated_at")

            profile["customized"] = profile["prompt"] != profile["default_prompt"]

        self.calibration_buttons = {}
        self.active_calibration_profile = ""
        self._applying_calibration_profile = False

        self.calibration_status_label = QLabel("Active calibration: Precise")
        self.calibration_status_label.setObjectName("calibrationStatusLabel")

        self.system_prompt_summary_label = QLabel("")
        self.system_prompt_summary_label.setObjectName("webArticleBody")
        self.system_prompt_summary_label.setWordWrap(True)

        self.open_system_prompt_button = QPushButton("System Prompt Editor")
        self.open_system_prompt_button.setToolTip(
            "Open the complete AI role and system prompt in a dedicated editor window."
        )
        self.open_system_prompt_button.clicked.connect(self.open_system_prompt_editor)
        self.persistent_memory_data = load_persistent_memory()
        self.persistent_memory = None

        self.persistent_memory_summary_label = QLabel("")
        self.persistent_memory_summary_label.setObjectName("webArticleBody")
        self.persistent_memory_summary_label.setWordWrap(True)

        self.open_persistent_memory_button = QPushButton("Persistent Memory Library")
        self.open_persistent_memory_button.setToolTip(
            "Open the complete structured memory library, search it, and add, edit, or remove entries."
        )
        self.open_persistent_memory_button.clicked.connect(
            self.open_persistent_memory_library
        )

        self.refresh_persistent_memory_list()

        self.document_knowledge_summary_label = QLabel("")
        self.document_knowledge_summary_label.setObjectName("webArticleBody")
        self.document_knowledge_summary_label.setWordWrap(True)

        self.import_documents_memory_button = QPushButton("Document Knowledge Library")
        self.import_documents_memory_button.setToolTip(
            "Import document text plus PDF charts, figures, diagrams, and page images "
            "into a searchable local library. Relevant excerpts, visual pages, and OCR-enriched PDF pages are "
            "retrieved automatically for each question."
        )
        self.import_documents_memory_button.clicked.connect(
            self.open_document_knowledge_library
        )

        self.refresh_document_knowledge_view()
        self.server_url = QLineEdit()
        self.server_url.setText(BASE_URL)
        self.server_url.setPlaceholderText(
            "http://localhost:11434/v1 or https://api.openai.com/v1"
        )
        self.server_url.editingFinished.connect(self.sync_runtime_client)

        self.api_key_input = QLineEdit()
        self.api_key_input.setText(API_KEY)
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.api_key_input.setPlaceholderText(
            "ollama for local Ollama, or provider API key"
        )
        self.api_key_input.editingFinished.connect(self.sync_runtime_client)

        self.refresh_models_button = QPushButton("Refresh Models")
        self.refresh_models_button.clicked.connect(self.refresh_models)

        self.restart_ollama_button = QPushButton("Restart Local Ollama")
        self.restart_ollama_button.setToolTip(
            "Stop and restart the local Ollama server, then refresh the model list."
        )
        self.restart_ollama_button.clicked.connect(self.restart_ollama)

        self.quick_refresh_models_button = self._create_toolbar_button(
            "↻",
            "quickRefreshModelsButton",
            "Refresh model list",
            width=36,
            height=36,
        )
        self.quick_refresh_models_button.clicked.connect(self.refresh_models)
        self.quick_refresh_models_button.setAccessibleName("Refresh model list")

        self.quick_restart_ollama_button = self._create_toolbar_button(
            "⏻",
            "quickRestartOllamaButton",
            "Restart local Ollama server",
            width=36,
            height=36,
        )
        self.quick_restart_ollama_button.clicked.connect(self.restart_ollama)
        self.quick_restart_ollama_button.setAccessibleName(
            "Restart local Ollama server"
        )

        self.model_box = QComboBox()
        self.model_box.setObjectName("quickModelBox")
        self.model_box.addItems([DEFAULT_MODEL_NAME])
        self.model_box.setFixedHeight(36)
        # Keep the active model selector compact in the quick bar.
        # Full model names remain available in the tooltip and the opened list.
        self.model_box.setMinimumWidth(210)
        self.model_box.setMaximumWidth(320)
        self.model_box.setFixedWidth(320)
        self.model_box.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.model_box.view().setMinimumWidth(440)

        self.web_box = QComboBox()
        self.web_box.setObjectName("quickWebBox")
        self.web_box.addItems(["Off", "Auto", "Always"])
        self.web_box.setCurrentText("Auto")
        self.web_box.setFixedHeight(36)
        self.web_box.setFixedWidth(104)
        self.web_box.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        identity_card, identity_layout = self._create_settings_card(
            "AI behavior", "Calibration profile and complete system instructions."
        )
        identity_layout.addWidget(self.calibration_status_label)
        identity_layout.addWidget(self.system_prompt_summary_label)
        identity_layout.addWidget(self.open_system_prompt_button)
        sidebar_layout.addWidget(identity_card)

        memory_card, memory_layout = self._create_settings_card(
            "Persistent memory",
            "Structured facts and preferences selected for long-term reuse.",
        )
        memory_layout.addWidget(self.persistent_memory_summary_label)
        memory_layout.addWidget(self.open_persistent_memory_button)
        sidebar_layout.addWidget(memory_card)

        knowledge_card, knowledge_layout = self._create_settings_card(
            "Document knowledge",
            "Searchable local document library used automatically during chat.",
        )
        knowledge_layout.addWidget(self.document_knowledge_summary_label)
        knowledge_layout.addWidget(self.import_documents_memory_button)
        sidebar_layout.addWidget(knowledge_card)

        runtime_card, runtime_layout = self._create_settings_card(
            "Runtime",
            "Configure the OpenAI-compatible API endpoint, API key, and model refresh. Active model and web mode are in the main toolbar.",
        )

        server_caption = QLabel("Server URL / API Base")
        server_caption.setObjectName("fieldCaption")
        runtime_layout.addWidget(server_caption)
        runtime_layout.addWidget(self.server_url)

        api_key_caption = QLabel("API Key")
        api_key_caption.setObjectName("fieldCaption")
        runtime_layout.addWidget(api_key_caption)
        runtime_layout.addWidget(self.api_key_input)

        runtime_layout.addWidget(self.refresh_models_button)
        runtime_layout.addWidget(self.restart_ollama_button)

        sidebar_layout.addWidget(runtime_card)
        sidebar_layout.addStretch()

        main = QWidget()
        main.setObjectName("main")

        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(16, 14, 16, 14)
        main_layout.setSpacing(10)

        top_bar = QFrame()
        top_bar.setObjectName("topBar")
        top_bar_layout = QHBoxLayout(top_bar)
        top_bar_layout.setContentsMargins(12, 10, 12, 10)
        top_bar_layout.setSpacing(8)

        self.sidebar_button = self._create_toolbar_button(
            "☰", "sidebarToggle", "Configuration"
        )
        self.sidebar_button.setCheckable(True)
        self.sidebar_button.clicked.connect(self.toggle_sidebar)

        brand_mark = QLabel("FZ")
        brand_mark.setObjectName("brandMark")
        brand_mark.setAlignment(Qt.AlignCenter)
        brand_mark.setFixedSize(38, 38)
        brand_mark.setCursor(Qt.PointingHandCursor)
        brand_mark.setToolTip("Open the FZAstro AI GitHub repository")
        brand_mark.setAccessibleName("Open FZAstro AI GitHub repository")
        brand_mark.mousePressEvent = self._handle_brand_mark_click

        title_box = QWidget()
        title_box_layout = QVBoxLayout(title_box)
        title_box_layout.setContentsMargins(0, 0, 0, 0)
        title_box_layout.setSpacing(0)

        header = QLabel("FZASTRO AI")
        header.setObjectName("header")

        subtitle = QLabel(f"Engineering LLM workstation • v{APP_VERSION}")
        subtitle.setObjectName("subtitle")

        title_box_layout.addWidget(header)
        title_box_layout.addWidget(subtitle)

        self.new_chat_button = self._create_toolbar_button(
            "＋", "newChatButton", "New chat", width=48, height=36
        )
        self.new_chat_button.clicked.connect(self.new_chat)

        self.history_button = self._create_toolbar_button(
            "◷", "historyToggle", "Chat history"
        )
        self.history_button.setCheckable(True)
        self.history_button.clicked.connect(self.toggle_history_panel)
        self.history_button.setAccessibleName("Open chat history")

        self.help_button = self._create_toolbar_button(
            "?", "helpButton", "Open help cheat sheet"
        )
        self.help_button.clicked.connect(self.open_help_cheat_sheet)
        self.help_button.setAccessibleName("Open help cheat sheet")

        self.diagnostics_button = self._create_toolbar_button(
            "ⓘ", "diagnosticsButton", "Open diagnostics and error log"
        )
        self.diagnostics_button.clicked.connect(self.open_diagnostics_window)
        self.diagnostics_button.setAccessibleName("Open diagnostics and error log")

        self.about_button = self._create_toolbar_button(
            "v", "aboutButton", "About FZAstro AI / version"
        )
        self.about_button.clicked.connect(self.open_about_window)
        self.about_button.setAccessibleName("About FZAstro AI")

        profile_order = ("precise", "architect", "explorer", "companion")

        self.calibration_buttons = {}

        for profile_key in profile_order:
            profile = self.calibration_profiles[profile_key]
            button = self._create_toolbar_button(
                profile["icon"],
                "calibrationProfileButton",
                profile["tooltip"],
                width=40,
                height=40,
            )
            button.setCheckable(True)
            button.setAccessibleName(f"{profile['name']} calibration profile")
            button.clicked.connect(
                lambda _checked=False, key=profile_key: self.apply_calibration_profile(
                    key
                )
            )
            self.calibration_buttons[profile_key] = button

        mode_label = QLabel("MODE")
        mode_label.setObjectName("toolbarCaption")

        separator = QFrame()
        separator.setObjectName("toolbarDivider")
        separator.setFrameShape(QFrame.VLine)
        separator.setFixedWidth(1)

        top_bar_layout.addWidget(self.sidebar_button)
        top_bar_layout.addWidget(brand_mark)
        top_bar_layout.addWidget(title_box)
        top_bar_layout.addStretch(1)
        top_bar_layout.addWidget(mode_label)

        for profile_key in profile_order:
            top_bar_layout.addWidget(self.calibration_buttons[profile_key])

        top_bar_layout.addSpacing(4)
        top_bar_layout.addWidget(separator)
        top_bar_layout.addSpacing(4)
        top_bar_layout.addWidget(self.history_button)
        top_bar_layout.addWidget(self.help_button)
        top_bar_layout.addWidget(self.diagnostics_button)
        top_bar_layout.addWidget(self.about_button)

        quick_bar = QFrame()
        quick_bar.setObjectName("quickActionsBar")
        quick_bar_layout = QHBoxLayout(quick_bar)
        quick_bar_layout.setContentsMargins(12, 8, 12, 8)
        quick_bar_layout.setSpacing(7)

        quick_label = QLabel("SKILLS")
        quick_label.setObjectName("toolbarCaption")

        self.news_button = QPushButton("Daily News")
        self.news_button.setObjectName("dailyNewsButton")
        self.news_button.setFixedHeight(36)
        self.news_button.setMinimumWidth(108)
        self.news_button.setCursor(Qt.PointingHandCursor)
        self.news_button.clicked.connect(self.daily_news)
        self.news_button.setToolTip("Generate the daily news briefing")

        self.llm_benchmark_button = QPushButton("LLM BENCH")
        self.llm_benchmark_button.setObjectName("stockPriceButton")
        self.llm_benchmark_button.setFixedSize(96, 36)
        self.llm_benchmark_button.setCursor(Qt.PointingHandCursor)
        self.llm_benchmark_button.clicked.connect(self.open_llm_benchmark_dashboard)
        self.llm_benchmark_button.setToolTip(
            "Open latency, throughput, and model comparison benchmarks"
        )
        self.llm_benchmark_button.setAccessibleName("Open LLM benchmark dashboard")

        self.dev_workbench_button = QPushButton("DEV")
        self.dev_workbench_button.setObjectName("stockPriceButton")
        self.dev_workbench_button.setFixedSize(62, 36)
        self.dev_workbench_button.setCursor(Qt.PointingHandCursor)
        self.dev_workbench_button.clicked.connect(self.open_dev_workbench)
        self.dev_workbench_button.setToolTip(
            "Open the AI Developer Workbench for project scanning, context building, plans, and checks"
        )
        self.dev_workbench_button.setAccessibleName("Open AI Developer Workbench")

        self.crm_stock_button = QPushButton("CRM")
        self.crm_stock_button.setObjectName("stockPriceButton")
        self.crm_stock_button.setFixedSize(54, 36)
        self.crm_stock_button.setCursor(Qt.PointingHandCursor)
        self.crm_stock_button.clicked.connect(lambda: self.retrieve_stock_price("CRM"))
        self.crm_stock_button.setToolTip("Retrieve the current Salesforce stock price")
        self.crm_stock_button.setAccessibleName("Retrieve CRM stock price")

        self.dbx_stock_button = QPushButton("DBX")
        self.dbx_stock_button.setObjectName("stockPriceButton")
        self.dbx_stock_button.setFixedSize(54, 36)
        self.dbx_stock_button.setCursor(Qt.PointingHandCursor)
        self.dbx_stock_button.clicked.connect(lambda: self.retrieve_stock_price("DBX"))
        self.dbx_stock_button.setToolTip("Retrieve the current Dropbox stock price")
        self.dbx_stock_button.setAccessibleName("Retrieve DBX stock price")

        self.crude_oil_button = QPushButton("OIL")
        self.crude_oil_button.setObjectName("stockPriceButton")
        self.crude_oil_button.setFixedSize(54, 36)
        self.crude_oil_button.setCursor(Qt.PointingHandCursor)
        self.crude_oil_button.clicked.connect(lambda: self.retrieve_stock_price("CL=F"))
        self.crude_oil_button.setToolTip("Retrieve the current crude oil futures price")
        self.crude_oil_button.setAccessibleName("Retrieve crude oil price")

        self.gold_button = QPushButton("GOLD")
        self.gold_button.setObjectName("stockPriceButton")
        self.gold_button.setFixedSize(62, 36)
        self.gold_button.setCursor(Qt.PointingHandCursor)
        self.gold_button.clicked.connect(lambda: self.retrieve_stock_price("GC=F"))
        self.gold_button.setToolTip("Retrieve the current gold futures price")
        self.gold_button.setAccessibleName("Retrieve gold price")

        self.astro_lookup_button = QPushButton("LOOKUP")
        self.astro_lookup_button.setObjectName("stockPriceButton")
        self.astro_lookup_button.setFixedSize(72, 36)
        self.astro_lookup_button.setCursor(Qt.PointingHandCursor)
        self.astro_lookup_button.clicked.connect(self.open_astro_lookup_dialog)
        self.astro_lookup_button.setToolTip(
            "Astro object lookup with optional sky image"
        )
        self.astro_lookup_button.setAccessibleName("Run astro object lookup")

        self.astro_sun_now_button = QPushButton("SUN NOW")
        self.astro_sun_now_button.setObjectName("stockPriceButton")
        self.astro_sun_now_button.setFixedSize(88, 36)
        self.astro_sun_now_button.setCursor(Qt.PointingHandCursor)
        self.astro_sun_now_button.clicked.connect(self.open_sun_now_dialog)
        self.astro_sun_now_button.setToolTip(
            "Show latest NASA/SDO Sun images with Helioviewer metadata"
        )
        self.astro_sun_now_button.setAccessibleName("Show latest Sun images")

        self.astro_targets_button = QPushButton("TARGETS")
        self.astro_targets_button.setObjectName("stockPriceButton")
        self.astro_targets_button.setFixedSize(86, 36)
        self.astro_targets_button.setCursor(Qt.PointingHandCursor)
        self.astro_targets_button.clicked.connect(self.open_astro_targets_dialog)
        self.astro_targets_button.setToolTip(
            "Find best astrophotography targets for a location"
        )
        self.astro_targets_button.setAccessibleName(
            "Find best astrophotography targets"
        )

        self.astro_see_button = QPushButton("SEEING")
        self.astro_see_button.setObjectName("stockPriceButton")
        self.astro_see_button.setFixedSize(86, 36)
        self.astro_see_button.setCursor(Qt.PointingHandCursor)
        self.astro_see_button.clicked.connect(self.open_astro_forecast_dialog)
        self.astro_see_button.setToolTip(
            "Open SEEING: true astronomy seeing and transparency from 7Timer ASTRO"
        )
        self.astro_see_button.setAccessibleName(
            "Open true astronomy seeing and transparency forecast"
        )

        self.astro_solar_button = QPushButton("SOLAR MAP")
        self.astro_solar_button.setObjectName("stockPriceButton")
        self.astro_solar_button.setFixedSize(112, 36)
        self.astro_solar_button.setCursor(Qt.PointingHandCursor)
        self.astro_solar_button.clicked.connect(self.open_solar_system_map)
        self.astro_solar_button.setToolTip(
            "Open the native interactive 2D solar-system map"
        )
        self.astro_solar_button.setAccessibleName(
            "Open native interactive solar-system map"
        )

        self.astro_location_button = QPushButton("SITE")
        self.astro_location_button.setObjectName("stockPriceButton")
        self.astro_location_button.setFixedSize(96, 36)
        self.astro_location_button.setCursor(Qt.PointingHandCursor)
        self.astro_location_button.clicked.connect(self.open_astro_location_dialog)
        self.astro_location_button.setToolTip(
            "Pick the observing site used by SEEING and TARGETS"
        )
        self.astro_location_button.setAccessibleName("Pick astro observing location")

        self.astro_location_label = QLabel(self.astro_location_summary())
        self.astro_location_label.setObjectName("toolbarCaption")
        self.astro_location_label.setMinimumWidth(220)
        self.astro_location_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.astro_location_label.setToolTip(
            "Current observing site used by SEEING and TARGETS"
        )
        try:
            self.astro_location_label.destroyed.connect(
                lambda *_: setattr(self, "astro_location_label", None)
            )
        except Exception:
            pass

        self.astro_imaging_button = QPushButton("IMAGING")
        self.astro_imaging_button.setObjectName("stockPriceButton")
        self.astro_imaging_button.setFixedSize(88, 36)
        self.astro_imaging_button.setCursor(Qt.PointingHandCursor)
        self.astro_imaging_button.clicked.connect(self.open_astro_imaging_dialog)
        self.astro_imaging_button.setToolTip(
            "Select camera preset, focal length, FOV, and rotation for LOOKUP"
        )
        self.astro_imaging_button.setAccessibleName("Select astro imaging setup")

        self.astro_imaging_label = QLabel(self.astro_imaging_summary())
        self.astro_imaging_label.setObjectName("toolbarCaption")
        self.astro_imaging_label.setMinimumWidth(270)
        self.astro_imaging_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.astro_imaging_label.setToolTip(
            "Current camera preset, focal length, FOV, and rotation used by LOOKUP"
        )

        self.workspace_context_label = QLabel("")
        self.workspace_context_label.setObjectName("workspaceContextLabel")
        self.workspace_context_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.workspace_context_label.hide()

        model_quick_label = QLabel("MODEL")
        model_quick_label.setObjectName("toolbarCaption")
        model_quick_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        web_quick_label = QLabel("WEB")
        web_quick_label.setObjectName("toolbarCaption")
        web_quick_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.skill_buttons = {}
        for skill in SKILLS:
            skill_button = QPushButton(skill.label)
            skill_button.setObjectName("stockPriceButton")
            skill_button.setFixedHeight(36)
            skill_button.setMinimumWidth(max(82, len(skill.label) * 9 + 24))
            skill_button.setCursor(Qt.PointingHandCursor)
            skill_button.setToolTip(skill.description)
            skill_button.setAccessibleName(f"Open {skill.label} skill")
            skill_button.setMenu(self.build_skill_menu(skill.skill_id))
            self.skill_buttons[skill.skill_id] = skill_button

        quick_bar_layout.addWidget(quick_label)
        quick_bar_layout.addSpacing(4)
        quick_bar_layout.addWidget(self.new_chat_button)
        quick_bar_layout.addWidget(self.dev_workbench_button)
        for skill_button in self.skill_buttons.values():
            quick_bar_layout.addWidget(skill_button)
        quick_bar_layout.addStretch(1)
        quick_bar_layout.addWidget(model_quick_label)
        quick_bar_layout.addWidget(self.model_box)
        quick_bar_layout.addWidget(self.quick_refresh_models_button)
        quick_bar_layout.addWidget(self.quick_restart_ollama_button)
        quick_bar_layout.addWidget(web_quick_label)
        quick_bar_layout.addWidget(self.web_box)

        astro_bar = QFrame()
        astro_bar.setObjectName("quickActionsBar")
        astro_bar_layout = QHBoxLayout(astro_bar)
        astro_bar_layout.setContentsMargins(12, 7, 12, 7)
        astro_bar_layout.setSpacing(7)

        astro_tools_label = QLabel("ASTRO TOOLS")
        astro_tools_label.setObjectName("toolbarCaption")
        astro_tools_label.setMinimumWidth(96)

        astro_bar_layout.addWidget(astro_tools_label)
        astro_bar_layout.addSpacing(4)
        astro_bar_layout.addWidget(self.astro_location_button)
        astro_bar_layout.addWidget(self.astro_location_label)
        astro_bar_layout.addSpacing(12)
        astro_bar_layout.addWidget(self.astro_imaging_button)
        astro_bar_layout.addWidget(self.astro_imaging_label)
        astro_bar_layout.addSpacing(12)
        astro_bar_layout.addWidget(self.astro_lookup_button)
        astro_bar_layout.addWidget(self.astro_sun_now_button)
        astro_bar_layout.addWidget(self.astro_see_button)
        astro_bar_layout.addWidget(self.astro_targets_button)
        astro_bar_layout.addWidget(self.astro_solar_button)
        astro_bar_layout.addStretch(1)

        self.model_box.currentTextChanged.connect(self.refresh_workspace_context)
        self.web_box.currentTextChanged.connect(self.refresh_workspace_context)
        self.sync_runtime_client()
        self.refresh_workspace_context()

        if startup_model_refresh_enabled():
            self.refresh_models()

        self.system_prompt.textChanged.connect(self.mark_custom_calibration)
        initial_profile_key = (
            str(self.calibration_profile_store.get("active_profile") or "precise")
            .strip()
            .lower()
        )

        if initial_profile_key not in self.calibration_profiles:
            initial_profile_key = "precise"

        self.apply_calibration_profile(initial_profile_key, announce=False)
        self.refresh_system_prompt_summary()

        self.chat_scroll = DropScrollArea()
        self.chat_scroll.setObjectName("chatScroll")
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.files_dropped.connect(self.add_files)

        self.chat_container = QWidget()
        self.chat_container.setObjectName("chatContainer")
        self.chat_container.setMaximumWidth(16777215)
        self.chat_container.setSizePolicy(
            self.chat_container.sizePolicy().horizontalPolicy(), QSizePolicy.Minimum
        )
        self.chat_layout = QVBoxLayout(self.chat_container)
        self.chat_layout.setContentsMargins(24, 20, 24, 26)
        self.chat_layout.setSpacing(14)
        self.chat_layout.setAlignment(Qt.AlignTop)
        # Only constrain the minimum content size.  A maximum-size constraint can
        # preserve an oversized rich-text height hint and create a phantom scroll gap.
        self.chat_layout.setSizeConstraint(QLayout.SetMinimumSize)
        self.chat_scroll.setWidget(self.chat_container)
        self.show_empty_chat_state()

        self.attachment_row_container = QWidget()
        self.attachment_row_container.setObjectName("attachmentRowContainer")
        attachment_row_layout = QHBoxLayout(self.attachment_row_container)
        attachment_row_layout.setContentsMargins(0, 0, 0, 0)
        attachment_row_layout.setSpacing(0)

        self.attachment_scroll = QScrollArea()
        self.attachment_scroll.setObjectName("attachmentScroll")
        self.attachment_scroll.setWidgetResizable(True)
        self.attachment_scroll.setFixedHeight(34)
        self.attachment_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.attachment_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.attachment_widget = QWidget()
        self.attachment_layout = QHBoxLayout(self.attachment_widget)
        self.attachment_layout.setContentsMargins(0, 0, 0, 0)
        self.attachment_layout.setSpacing(7)
        self.attachment_layout.addStretch()

        self.attachment_scroll.setWidget(self.attachment_widget)
        attachment_row_layout.addWidget(self.attachment_scroll)
        self.attachment_row_container.hide()

        self.time_label = QLabel("")
        self.time_label.setObjectName("timeLabel")
        self.time_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.time_label.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        self.time_label.setToolTip("Local date and time")

        self.gpu_label = QLabel("GPU --% • VRAM --/-- GB")
        self.gpu_label.setObjectName("gpuLabel")
        self.gpu_label.setAlignment(Qt.AlignCenter)
        self.gpu_label.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        self.gpu_label.setToolTip(
            "NVIDIA GPU load, temperature and dedicated memory usage"
        )

        self.system_label = QLabel("CPU --% • RAM --/-- GB")
        self.system_label.setObjectName("systemLabel")
        self.system_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.system_label.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        self.system_label.setToolTip(
            "CPU load, best-effort CPU temperature and system RAM usage"
        )

        self.stats_label = QLabel("")
        self.stats_label.setObjectName("statsLabel")
        self.stats_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.stats_label.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)

        self.status_row = QWidget()
        self.status_row.setObjectName("statusRow")

        status_row_layout = QHBoxLayout(self.status_row)
        status_row_layout.setContentsMargins(2, 0, 2, 0)
        status_row_layout.setSpacing(8)
        status_row_layout.addWidget(self.time_label, 0, Qt.AlignLeft | Qt.AlignVCenter)
        status_row_layout.addStretch(1)
        status_row_layout.addWidget(self.gpu_label, 0, Qt.AlignCenter)
        status_row_layout.addStretch(1)
        status_row_layout.addWidget(
            self.system_label, 0, Qt.AlignRight | Qt.AlignVCenter
        )
        status_row_layout.addWidget(
            self.stats_label, 0, Qt.AlignRight | Qt.AlignVCenter
        )

        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.update_clock_label)
        self.clock_timer.start(1000)
        self.update_clock_label()

        if startup_gpu_monitor_enabled():
            self.gpu_monitor = GpuMonitorWorker(interval_ms=1000, parent=self)
            self.gpu_monitor.metrics_ready.connect(self.update_gpu_metrics)
            self.gpu_monitor.system_metrics_ready.connect(self.update_system_metrics)
            self.gpu_monitor.unavailable.connect(self.show_gpu_unavailable)
            self.gpu_monitor.start()
        else:
            self.gpu_monitor = None
            self.gpu_label.setText("GPU telemetry disabled")
            self.system_label.setText("CPU/RAM telemetry disabled")

        composer_control_height = 48
        composer_button_width = 108

        self.attach_button = QPushButton("Attach")
        self.attach_button.setObjectName("attachButton")
        self.attach_button.setFixedWidth(composer_button_width)
        self.attach_button.setFixedHeight(composer_control_height)
        self.attach_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.attach_button.setCursor(Qt.PointingHandCursor)
        self.attach_button.setToolTip("Attach files")
        # Keep the control monochrome; native folder icons are coloured on Windows.
        self.attach_button.setIcon(QIcon())
        self.attach_button.clicked.connect(self.attach_files)

        self.input_box = EnterSendTextEdit(self.send_message, self.add_files)
        self.input_box.setObjectName("inputBox")
        self.input_box.setFixedHeight(composer_control_height)
        self.input_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.input_box.setPlaceholderText(
            "Message FZASTRO AI — Enter to send, Shift+Enter for a new line"
        )

        self.action_button = QPushButton("Send")
        self.action_button.setObjectName("sendButton")
        self.action_button.setFixedWidth(composer_button_width)
        self.action_button.setFixedHeight(composer_control_height)
        self.action_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.action_button.setCursor(Qt.PointingHandCursor)
        self.action_button.setToolTip("Send message")
        self.action_button.setIcon(QIcon())
        self.action_button.clicked.connect(self.action_button_clicked)

        self._voice_icon_idle = make_microphone_icon("#e8ebef")
        self._voice_icon_recording = make_microphone_icon("#ffe2e6")
        self.voice_button = QPushButton("")
        self.voice_button.setObjectName("voiceButton")
        self.voice_button.setFixedSize(composer_control_height, composer_control_height)
        self.voice_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.voice_button.setCursor(Qt.PointingHandCursor)
        self.voice_button.setToolTip("Offline push-to-talk voice command")
        self.voice_button.setAccessibleName("Offline voice command")
        self.voice_button.setCheckable(True)
        self.voice_button.setIcon(self._voice_icon_idle)
        self.voice_button.setIconSize(QSize(24, 24))
        self.voice_button.clicked.connect(self.toggle_offline_voice_command)

        composer_toolbar = QFrame()
        composer_toolbar.setObjectName("composerToolbar")
        composer_toolbar_layout = QHBoxLayout(composer_toolbar)
        composer_toolbar_layout.setContentsMargins(0, 0, 0, 0)
        composer_toolbar_layout.setSpacing(6)

        composer_tools_label = QLabel("COMPOSER")
        composer_tools_label.setObjectName("composerToolsLabel")

        self.composer_code_button = QPushButton("Code Lab")
        self.composer_code_button.setObjectName("composerToolButton")
        self.composer_code_button.setCursor(Qt.PointingHandCursor)
        self.composer_code_button.setToolTip(
            "Code tools: wrap/paste code, run Python, debug, refactor, test, patch, and review."
        )
        self.composer_code_button.setShortcut(QKeySequence("Ctrl+K"))
        self.composer_code_button.setMenu(self.build_skill_menu("code_lab"))

        self.composer_paste_code_button = QPushButton("Add")
        self.composer_paste_code_button.setObjectName("composerToolButton")
        self.composer_paste_code_button.setCursor(Qt.PointingHandCursor)
        self.composer_paste_code_button.setToolTip(
            "Add content: paste code, attach files, import documents, or insert context."
        )
        self.composer_paste_code_button.setMenu(self.build_composer_add_menu())

        self.composer_actions_button = QPushButton("Skills")
        self.composer_actions_button.setObjectName("composerToolButton")
        self.composer_actions_button.setCursor(Qt.PointingHandCursor)
        self.composer_actions_button.setToolTip(
            "Open all skill groups from the composer."
        )
        self.composer_actions_button.setMenu(self.build_composer_skills_menu())

        self.composer_context_button = QPushButton("Knowledge")
        self.composer_context_button.setObjectName("composerToolButton")
        self.composer_context_button.setCursor(Qt.PointingHandCursor)
        self.composer_context_button.setToolTip(
            "Open imported documents, search the knowledge library, brief books, and browse PDF pages."
        )
        self.composer_context_button.setMenu(self.build_skill_menu("knowledge"))

        self.composer_persona_button = QPushButton("Model Lab")
        self.composer_persona_button.setObjectName("composerToolButton")
        self.composer_persona_button.setCursor(Qt.PointingHandCursor)
        self.composer_persona_button.setToolTip(
            "Show the current persona/calibration or open persona-related tools."
        )
        self.composer_persona_button.setMenu(self.build_skill_menu("model_lab"))

        self.composer_clear_button = QPushButton("Clear")
        self.composer_clear_button.setObjectName("composerToolButton")
        self.composer_clear_button.setCursor(Qt.PointingHandCursor)
        self.composer_clear_button.setToolTip("Clear the composer and attachments.")
        self.composer_clear_button.clicked.connect(self.clear_composer)

        composer_toolbar_layout.addWidget(composer_tools_label, 0, Qt.AlignVCenter)
        composer_toolbar_layout.addWidget(self.composer_code_button, 0, Qt.AlignVCenter)
        composer_toolbar_layout.addWidget(
            self.composer_paste_code_button, 0, Qt.AlignVCenter
        )
        composer_toolbar_layout.addWidget(
            self.composer_actions_button, 0, Qt.AlignVCenter
        )
        composer_toolbar_layout.addWidget(
            self.composer_context_button, 0, Qt.AlignVCenter
        )
        composer_toolbar_layout.addWidget(
            self.composer_persona_button, 0, Qt.AlignVCenter
        )
        composer_toolbar_layout.addWidget(
            self.composer_clear_button, 0, Qt.AlignVCenter
        )
        composer_toolbar_layout.addStretch(1)

        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(9)
        input_row.setAlignment(Qt.AlignVCenter)
        input_row.addWidget(self.attach_button, 0, Qt.AlignVCenter)
        input_row.addWidget(self.input_box, 1, Qt.AlignVCenter)
        input_row.addWidget(self.voice_button, 0, Qt.AlignVCenter)
        input_row.addWidget(self.action_button, 0, Qt.AlignVCenter)

        self.thought_panel = QFrame()
        self.thought_panel.setObjectName("thoughtPanel")
        thought_panel_layout = QVBoxLayout(self.thought_panel)
        thought_panel_layout.setContentsMargins(12, 9, 12, 10)
        thought_panel_layout.setSpacing(5)

        thought_header_row = QHBoxLayout()
        thought_header_row.setContentsMargins(0, 0, 0, 0)
        thought_header_row.setSpacing(6)

        thought_indicator = QLabel("●")
        thought_indicator.setObjectName("thoughtIndicator")
        thought_title = QLabel("MODEL ACTIVITY")
        thought_title.setObjectName("thoughtTitle")
        thought_hint = QLabel("latest reasoning / output stream")
        thought_hint.setObjectName("thoughtHint")

        thought_header_row.addWidget(thought_indicator)
        thought_header_row.addWidget(thought_title)
        thought_header_row.addWidget(thought_hint)
        thought_header_row.addStretch()

        self.global_thought_box = QTextBrowser()
        self.global_thought_box.setObjectName("thoughtBox")
        self.global_thought_box.setFixedHeight(54)
        self.global_thought_box.setReadOnly(True)
        self.global_thought_box.setFrameShape(QFrame.NoFrame)
        self.global_thought_box.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.global_thought_box.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.global_thought_box.document().setDocumentMargin(0)
        self.global_thought_box.setMarkdown("")
        self.global_thought_box.textChanged.connect(
            self.refresh_thought_panel_visibility
        )

        thought_panel_layout.addLayout(thought_header_row)
        thought_panel_layout.addWidget(self.global_thought_box)
        self.thought_panel.hide()

        chat_surface = QFrame()
        chat_surface.setObjectName("chatSurface")
        chat_surface_layout = QVBoxLayout(chat_surface)
        chat_surface_layout.setContentsMargins(0, 0, 0, 0)
        chat_surface_layout.setSpacing(0)
        chat_surface_layout.addWidget(self.chat_scroll)

        composer_shell = QFrame()
        composer_shell.setObjectName("composerShell")
        composer_layout = QVBoxLayout(composer_shell)
        composer_layout.setContentsMargins(11, 8, 11, 8)
        composer_layout.setSpacing(5)
        composer_layout.addWidget(self.attachment_row_container)
        composer_layout.addWidget(composer_toolbar)
        composer_layout.addLayout(input_row)
        composer_layout.addWidget(self.status_row)

        main_layout.addWidget(top_bar)
        main_layout.addWidget(quick_bar)
        # Astro actions now live under the Astro skill menu.
        main_layout.addWidget(self.thought_panel)
        main_layout.addWidget(chat_surface, 1)
        main_layout.addWidget(composer_shell)
        self.history_panel = QWidget()
        self.history_panel.setFixedWidth(368)
        self.history_panel.setObjectName("historyPanel")
        self.history_panel.hide()

        history_panel_layout = QVBoxLayout(self.history_panel)
        history_panel_layout.setContentsMargins(14, 14, 14, 14)
        history_panel_layout.setSpacing(10)

        history_header = QFrame()
        history_header.setObjectName("historyHeader")
        history_header_layout = QHBoxLayout(history_header)
        history_header_layout.setContentsMargins(12, 10, 10, 10)
        history_header_layout.setSpacing(8)

        history_title_box = QWidget()
        history_title_box_layout = QVBoxLayout(history_title_box)
        history_title_box_layout.setContentsMargins(0, 0, 0, 0)
        history_title_box_layout.setSpacing(1)

        history_title = QLabel("History")
        history_title.setObjectName("historyTitle")
        history_subtitle = QLabel("Saved conversations")
        history_subtitle.setObjectName("historySubtitle")
        history_title_box_layout.addWidget(history_title)
        history_title_box_layout.addWidget(history_subtitle)

        self.history_selection_label = QLabel("0 selected")
        self.history_selection_label.setObjectName("selectionPill")
        self.history_selection_label.setAlignment(Qt.AlignCenter)

        history_close_button = QPushButton("×")
        history_close_button.setObjectName("panelCloseButton")
        history_close_button.setFixedSize(30, 30)
        history_close_button.setCursor(Qt.PointingHandCursor)
        history_close_button.setToolTip("Close history")
        history_close_button.clicked.connect(self.toggle_history_panel)

        history_header_layout.addWidget(history_title_box, 1)
        history_header_layout.addWidget(self.history_selection_label)
        history_header_layout.addWidget(history_close_button)
        history_panel_layout.addWidget(history_header)

        history_actions = QFrame()
        history_actions.setObjectName("historyActions")
        history_actions_layout = QVBoxLayout(history_actions)
        history_actions_layout.setContentsMargins(10, 10, 10, 10)
        history_actions_layout.setSpacing(7)

        self.remember_selected_button = QPushButton("Remember Selected")
        self.remember_selected_button.setObjectName("primaryActionButton")
        self.remember_selected_button.setEnabled(False)
        self.remember_selected_button.clicked.connect(self.remember_selected_history)

        self.clear_history_selection_button = QPushButton("Clear Selection")
        self.clear_history_selection_button.setObjectName("secondaryActionButton")
        self.clear_history_selection_button.setEnabled(False)
        self.clear_history_selection_button.clicked.connect(
            self.clear_history_selection
        )

        self.memory_stop_button = QPushButton("Stop Extraction")
        self.memory_stop_button.setObjectName("dangerActionButton")
        self.memory_stop_button.setVisible(False)
        self.memory_stop_button.setEnabled(False)
        self.memory_stop_button.clicked.connect(self.stop_memory_extraction)

        selection_action_row = QHBoxLayout()
        selection_action_row.setContentsMargins(0, 0, 0, 0)
        selection_action_row.setSpacing(7)
        selection_action_row.addWidget(self.remember_selected_button, 1)
        selection_action_row.addWidget(self.clear_history_selection_button, 1)

        clear_all_button = QPushButton("Clear Unpinned History")
        clear_all_button.setObjectName("secondaryActionButton")
        clear_all_button.clicked.connect(self.clear_all_history)

        history_actions_layout.addLayout(selection_action_row)
        history_actions_layout.addWidget(self.memory_stop_button)
        history_actions_layout.addWidget(clear_all_button)
        history_panel_layout.addWidget(history_actions)

        self.history_scroll = QScrollArea()
        self.history_scroll.setObjectName("historyScroll")
        self.history_scroll.setWidgetResizable(True)
        self.history_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.history_scroll.setFrameShape(QFrame.NoFrame)

        self.history_widget = QWidget()
        self.history_widget.setObjectName("historyListSurface")
        self.history_list = QVBoxLayout(self.history_widget)
        self.history_list.setContentsMargins(0, 0, 0, 0)
        self.history_list.setSpacing(7)
        self.history_list.addStretch()

        self.history_scroll.setWidget(self.history_widget)
        history_panel_layout.addWidget(self.history_scroll, 1)
        self.render_history()
        root_layout.addWidget(self.sidebar)
        root_layout.addWidget(main, 1)
        root_layout.addWidget(self.history_panel)

        self.setCentralWidget(root)
        self.apply_styles()

    def open_document_knowledge_library(self):
        dialog = QDialog(self)
        apply_window_defaults(dialog)
        dialog.setWindowTitle("Document Knowledge Library")
        dialog.resize(920, 720)
        self.knowledge_dialog = dialog

        layout = QVBoxLayout(dialog)

        explanation = QLabel(
            "Documents are stored as searchable text. PDF pages containing charts, figures, "
            "diagrams, maps, or images are also rendered and stored locally. The app "
            "retrieves only relevant excerpts and visual pages for each question, so "
            "large PDFs do not consume the context window on every request."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        self.knowledge_list_widget = QListWidget()
        self.knowledge_list_widget.setObjectName("systemPromptBox")
        self.knowledge_list_widget.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.knowledge_list_widget.setToolTip(
            "Double-click a document title to open brief, reader, search, and ask options."
        )
        self.knowledge_list_widget.itemActivated.connect(
            lambda item: self.open_knowledge_document_options(
                item.data(Qt.ItemDataRole.UserRole)
            )
        )
        self.knowledge_list_widget.itemDoubleClicked.connect(
            lambda item: self.open_knowledge_document_options(
                item.data(Qt.ItemDataRole.UserRole)
            )
        )
        layout.addWidget(self.knowledge_list_widget, 1)

        document_action_row = QHBoxLayout()
        document_action_row.setSpacing(8)

        self.knowledge_options_button = QPushButton("Document Options")
        self.knowledge_options_button.setToolTip(
            "Open actions for the selected document: brief, reader, search, ask, or original file."
        )
        self.knowledge_options_button.clicked.connect(
            self.open_selected_knowledge_document_options
        )

        self.knowledge_brief_button = QPushButton("Brief Selected")
        self.knowledge_brief_button.clicked.connect(
            self.brief_selected_knowledge_document
        )

        self.knowledge_reader_button = QPushButton("Open as Book")
        self.knowledge_reader_button.clicked.connect(
            self.open_selected_knowledge_document_reader
        )

        self.knowledge_search_inside_button = QPushButton("Search Inside")
        self.knowledge_search_inside_button.clicked.connect(
            self.search_selected_knowledge_document
        )

        document_action_row.addWidget(self.knowledge_options_button)
        document_action_row.addWidget(self.knowledge_brief_button)
        document_action_row.addWidget(self.knowledge_reader_button)
        document_action_row.addWidget(self.knowledge_search_inside_button)
        document_action_row.addStretch()
        layout.addLayout(document_action_row)

        self.knowledge_status_label = QLabel()
        self.knowledge_status_label.setObjectName("documentKnowledgeStatusLabel")
        self.knowledge_status_label.setWordWrap(True)
        self.knowledge_status_label.setMinimumHeight(34)
        self.knowledge_status_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.knowledge_status_label)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        self.knowledge_import_button = QPushButton("Import Documents")
        self.knowledge_import_button.clicked.connect(
            self.start_document_knowledge_import
        )

        self.knowledge_remove_button = QPushButton("Remove Selected")
        self.knowledge_remove_button.clicked.connect(
            self.remove_selected_knowledge_documents
        )

        self.knowledge_clear_button = QPushButton("Clear Library")
        self.knowledge_clear_button.clicked.connect(
            self.clear_document_knowledge_library
        )

        self.knowledge_compact_button = QPushButton("Compact Storage")
        self.knowledge_compact_button.setToolTip(
            "Shrink document_knowledge.sqlite3 and its WAL files after removals."
        )
        self.knowledge_compact_button.clicked.connect(
            self.start_document_knowledge_compaction
        )

        action_row.addWidget(self.knowledge_import_button)
        action_row.addWidget(self.knowledge_remove_button)
        action_row.addWidget(self.knowledge_clear_button)
        action_row.addWidget(self.knowledge_compact_button)
        action_row.addStretch()
        layout.addLayout(action_row)

        search_label = QLabel("Test Library Search")
        layout.addWidget(search_label)

        search_row = QHBoxLayout()
        self.knowledge_search_input = QLineEdit()
        self.knowledge_search_input.setPlaceholderText(
            "Example: NGC 1333 magnitude distance description"
        )
        search_button = QPushButton("Search")
        search_button.clicked.connect(self.test_document_knowledge_search)
        self.knowledge_search_input.returnPressed.connect(
            self.test_document_knowledge_search
        )
        search_row.addWidget(self.knowledge_search_input, 1)
        search_row.addWidget(search_button)
        layout.addLayout(search_row)

        self.knowledge_search_preview = QTextEdit()
        self.knowledge_search_preview.setObjectName("systemPromptBox")
        self.knowledge_search_preview.setReadOnly(True)
        self.knowledge_search_preview.setPlaceholderText(
            "Search results will appear here with source and page or section labels."
        )
        self.knowledge_search_preview.setFixedHeight(220)
        layout.addWidget(self.knowledge_search_preview)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        self.knowledge_close_button = buttons.button(
            QDialogButtonBox.StandardButton.Close
        )

        if not (self.knowledge_worker and self.knowledge_worker.isRunning()):
            self.knowledge_current_status_text = ""

        self.refresh_document_knowledge_view()
        self.set_document_knowledge_busy(
            bool(self.knowledge_worker and self.knowledge_worker.isRunning())
        )

        dialog.exec()

        self.knowledge_dialog = None
        self.knowledge_list_widget = None
        self.knowledge_options_button = None
        self.knowledge_brief_button = None
        self.knowledge_reader_button = None
        self.knowledge_search_inside_button = None
        self.knowledge_status_label = None
        self.knowledge_import_button = None
        self.knowledge_remove_button = None
        self.knowledge_clear_button = None
        self.knowledge_compact_button = None
        self.knowledge_close_button = None
        self.knowledge_search_input = None
        self.knowledge_search_preview = None

    def set_document_knowledge_status(self, text, *, mirror_main=True):
        status_text = str(text or "").strip()
        self.knowledge_current_status_text = status_text

        if mirror_main:
            self.stats_label.setText(status_text)

        if self.knowledge_status_label is not None:
            try:
                self.knowledge_status_label.setText(status_text)
                self.knowledge_status_label.setToolTip(status_text)
            except RuntimeError:
                pass

    def set_document_knowledge_busy(self, busy):
        for button in (
            getattr(self, "knowledge_options_button", None),
            getattr(self, "knowledge_brief_button", None),
            getattr(self, "knowledge_reader_button", None),
            getattr(self, "knowledge_search_inside_button", None),
            self.knowledge_import_button,
            self.knowledge_remove_button,
            self.knowledge_clear_button,
            self.knowledge_compact_button,
            self.knowledge_close_button,
        ):
            if button is not None:
                try:
                    button.setEnabled(not busy)
                except RuntimeError:
                    pass

        if hasattr(self, "import_documents_memory_button"):
            memory_busy = bool(self.memory_worker and self.memory_worker.isRunning())
            self.import_documents_memory_button.setEnabled(not busy and not memory_busy)

    def refresh_document_knowledge_view(self):
        documents = self.knowledge_library.list_documents()
        total_characters = sum(document["character_count"] for document in documents)
        total_chunks = sum(document["chunk_count"] for document in documents)
        total_visuals = sum(
            int(document.get("visual_count", 0)) for document in documents
        )

        if hasattr(self, "document_knowledge_summary_label"):
            document_word = "document" if len(documents) == 1 else "documents"
            visual_word = "visual page" if total_visuals == 1 else "visual pages"
            self.document_knowledge_summary_label.setText(
                f"{len(documents):,} {document_word} • "
                f"{total_characters:,} characters • "
                f"{total_chunks:,} searchable chunks • "
                f"{total_visuals:,} {visual_word}\n"
                "Relevant excerpts, PDF visuals, and OCR text are retrieved automatically."
            )

        if self.knowledge_list_widget is not None:
            try:
                self.knowledge_list_widget.clear()

                for document in documents:
                    visual_count = int(document.get("visual_count", 0))
                    visual_word = "visual page" if visual_count == 1 else "visual pages"
                    file_icon = (
                        "📘"
                        if str(document.get("name", "")).lower().endswith(".pdf")
                        else "📄"
                    )
                    searchable_state = (
                        "Text searchable"
                        if int(document.get("character_count") or 0) > 0
                        else "No searchable text"
                    )
                    item = QListWidgetItem(
                        f"{file_icon} {document['name']}\n"
                        f"{document['character_count']:,} characters • "
                        f"{document['chunk_count']:,} chunks • "
                        f"{document['section_count']:,} sections • "
                        f"{visual_count:,} {visual_word} • "
                        f"{searchable_state} • Imported {document['imported_at']}\n"
                        "Double-click title for Brief, Open as Book, Search Inside, and Ask options."
                    )
                    item.setData(Qt.ItemDataRole.UserRole, document["id"])
                    item.setToolTip(
                        f"{document['original_path']}\n\nDouble-click to open document options."
                    )
                    self.knowledge_list_widget.addItem(item)
            except RuntimeError:
                pass

        if self.knowledge_status_label is not None:
            try:
                document_word = "document" if len(documents) == 1 else "documents"
                visual_word = "visual page" if total_visuals == 1 else "visual pages"
                summary_text = (
                    f"{len(documents):,} {document_word} • "
                    f"{total_characters:,} extracted characters • "
                    f"{total_chunks:,} searchable chunks • "
                    f"{total_visuals:,} {visual_word}"
                )
                visible_status = self.knowledge_current_status_text or summary_text
                self.knowledge_status_label.setText(visible_status)
                self.knowledge_status_label.setToolTip(visible_status)
            except RuntimeError:
                pass

    def selected_knowledge_document_id(self):
        if self.knowledge_list_widget is None:
            return None

        selected_items = self.knowledge_list_widget.selectedItems()

        if not selected_items:
            current_item = self.knowledge_list_widget.currentItem()
            selected_items = [current_item] if current_item is not None else []

        if not selected_items:
            return None

        return selected_items[0].data(Qt.ItemDataRole.UserRole)

    def selected_knowledge_document(self):
        document_id = self.selected_knowledge_document_id()

        if not document_id:
            return None

        return self.knowledge_library.get_document(document_id)

    def open_selected_knowledge_document_options(self):
        document_id = self.selected_knowledge_document_id()

        if not document_id:
            self.set_document_knowledge_status("Select a document first.")
            return

        self.open_knowledge_document_options(document_id)

    def brief_selected_knowledge_document(self):
        document_id = self.selected_knowledge_document_id()

        if not document_id:
            self.set_document_knowledge_status("Select a document first.")
            return

        self.show_knowledge_document_brief(document_id)

    def open_selected_knowledge_document_reader(self):
        document_id = self.selected_knowledge_document_id()

        if not document_id:
            self.set_document_knowledge_status("Select a document first.")
            return

        self.open_knowledge_document_reader(document_id)

    def search_selected_knowledge_document(self):
        document_id = self.selected_knowledge_document_id()

        if not document_id:
            self.set_document_knowledge_status("Select a document first.")
            return

        self.open_knowledge_document_search(document_id)

    def open_knowledge_document_options(self, document_id):
        document = self.knowledge_library.get_document(document_id)

        if document is None:
            self.set_document_knowledge_status(
                "Document no longer exists in the library."
            )
            return

        dialog = QDialog(self)
        apply_window_defaults(dialog)
        dialog.setWindowTitle(f"Document Options — {document.get('name', 'Document')}")
        dialog.resize(680, 360)

        layout = QVBoxLayout(dialog)
        title = QLabel(f"<b>{html.escape(str(document.get('name') or 'Document'))}</b>")
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setWordWrap(True)
        layout.addWidget(title)

        visual_count = int(document.get("visual_count") or 0)
        visual_word = "visual page" if visual_count == 1 else "visual pages"
        details = QLabel(
            f"{int(document.get('character_count') or 0):,} characters • "
            f"{int(document.get('chunk_count') or 0):,} chunks • "
            f"{int(document.get('section_count') or 0):,} sections • "
            f"{visual_count:,} {visual_word}\n"
            f"Imported {document.get('imported_at') or '(unknown)'}\n"
            f"{document.get('original_path') or ''}"
        )
        details.setWordWrap(True)
        details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(details)

        button_grid = QGridLayout()
        button_grid.setSpacing(8)

        actions = [
            (
                "Brief document",
                "Generate a local brief scaffold and opening excerpt.",
                lambda: self.show_knowledge_document_brief(document_id),
            ),
            (
                "Open as book",
                "Browse rendered PDF pages/images with previous/next controls.",
                lambda: self.open_knowledge_document_reader(document_id),
            ),
            (
                "Search inside",
                "Search only this document's indexed text and OCR text.",
                lambda: self.open_knowledge_document_search(document_id),
            ),
            (
                "Ask about this document",
                "Insert a document-scoped question prompt into the composer.",
                lambda: self.insert_document_question_prompt(document),
            ),
            (
                "Open original file",
                "Open the original PDF/document in the system viewer.",
                lambda: self.open_original_knowledge_document(document),
            ),
            (
                "Document details",
                "Show stored metadata for this imported document.",
                lambda: self.show_knowledge_document_details(document),
            ),
        ]

        for index, (label, tooltip, handler) in enumerate(actions):
            button = QPushButton(label)
            button.setToolTip(tooltip)
            button.clicked.connect(lambda checked=False, fn=handler: fn())
            button_grid.addWidget(button, index // 2, index % 2)

        layout.addLayout(button_grid)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def show_knowledge_document_brief(self, document_id):
        brief = self.knowledge_library.format_document_brief(document_id)
        document = self.knowledge_library.get_document(document_id) or {}
        self.show_text_dialog(
            f"Document Brief — {document.get('name', 'Document')}",
            brief,
        )

    def insert_document_question_prompt(self, document):
        title = str(document.get("name") or "this document").strip()
        self.insert_prompt_into_composer(
            f"Answer using only this imported document: {title}\n\nQuestion: "
        )
        self.stats_label.setText("Inserted document-scoped question prompt.")

    def ask_knowledge_document_with_llm(
        self,
        document_id,
        question,
        *,
        display_prompt=None,
        status_label="Using selected document with the LLM... • 0.00s",
    ):
        """Send a document-scoped question through the normal LLM/RAG path."""
        document = self.knowledge_library.get_document(document_id)

        if document is None:
            self.stats_label.setText("Document no longer exists in the library.")
            return False

        self.activate_knowledge_document_by_id(document_id, announce=False)
        title = str(document.get("name") or "this document").strip()
        prompt = (
            f"Answer using only this imported document: {title}\n\n"
            f"Question: {str(question or '').strip()}"
        ).strip()
        display_text = str(display_prompt or prompt).strip()

        self.stats_label.setText(status_label)
        self.send_message_after_web(
            prompt,
            [],
            display_text=display_text,
            files=[],
            show_user=True,
            include_document_knowledge=True,
        )
        return True

    def open_original_knowledge_document(self, document):
        path = str(document.get("original_path") or "").strip()

        if not path or not os.path.exists(path):
            QMessageBox.warning(
                self,
                "Open Original Document",
                "The original file path is missing or no longer exists.",
            )
            return

        open_local_path(self, path)

    def show_knowledge_document_details(self, document):
        details = json.dumps(document, indent=2, ensure_ascii=False)
        self.show_text_dialog(
            f"Document Details — {document.get('name', 'Document')}", details
        )

    def open_knowledge_document_reader(self, document_id, target_page=None):
        document = self.knowledge_library.get_document(document_id)

        if document is None:
            self.set_document_knowledge_status(
                "Document no longer exists in the library."
            )
            return

        visuals = self.knowledge_library.list_document_visuals(document_id)

        if not visuals:
            path = str(document.get("original_path") or "").strip()
            if path and os.path.exists(path):
                answer = QMessageBox.question(
                    self,
                    "Open as Book",
                    "No rendered page images are stored for this document. Open the original file instead?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )

                if answer == QMessageBox.StandardButton.Yes:
                    open_local_path(self, path)
                return

            QMessageBox.information(
                self,
                "Open as Book",
                "No rendered PDF page images are stored for this document.",
            )
            return

        dialog = QDialog(self)
        apply_window_defaults(dialog)
        dialog.setWindowTitle(f"Book Reader — {document.get('name', 'Document')}")
        dialog.resize(980, 760)

        layout = QVBoxLayout(dialog)
        heading = QLabel(
            f"<b>{html.escape(str(document.get('name') or 'Document'))}</b>"
        )
        heading.setTextFormat(Qt.TextFormat.RichText)
        heading.setWordWrap(True)
        layout.addWidget(heading)

        page_label = QLabel()
        page_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(page_label)

        image_label = QLabel()
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_label.setObjectName("imagePreview")
        image_label.setMinimumSize(620, 460)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(image_label)
        layout.addWidget(scroll, 1)

        state = {"index": 0}

        if target_page is not None:
            try:
                requested_page = int(target_page)
            except (TypeError, ValueError):
                requested_page = None

            if requested_page is not None:
                for index, visual in enumerate(visuals):
                    if int(visual.get("page_number") or 0) == requested_page:
                        state["index"] = index
                        break

        def show_page():
            index = max(0, min(state["index"], len(visuals) - 1))
            state["index"] = index
            visual = visuals[index]
            file_path = str(visual.get("file_path") or "")
            page_number = int(visual.get("page_number") or 0)
            page_label.setText(
                f"Page {page_number or index + 1} • {index + 1:,} of {len(visuals):,} rendered pages • {file_path}"
            )

            pixmap = QPixmap(file_path)
            if pixmap.isNull():
                image_label.setText("Page image could not be loaded.")
                return

            target_size = scroll.viewport().size()
            if target_size.width() > 80 and target_size.height() > 80:
                pixmap = pixmap.scaled(
                    target_size.width() - 24,
                    target_size.height() - 24,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )

            image_label.setPixmap(pixmap)

        nav_row = QHBoxLayout()
        previous_button = QPushButton("Previous")
        next_button = QPushButton("Next")
        open_original_button = QPushButton("Open Original")

        def previous_page():
            state["index"] = max(0, state["index"] - 1)
            show_page()

        def next_page():
            state["index"] = min(len(visuals) - 1, state["index"] + 1)
            show_page()

        previous_button.clicked.connect(lambda checked=False: previous_page())
        next_button.clicked.connect(lambda checked=False: next_page())
        open_original_button.clicked.connect(
            lambda checked=False: self.open_original_knowledge_document(document)
        )

        jump_spin = QSpinBox()
        jump_spin.setMinimum(1)
        jump_spin.setMaximum(max(1, len(visuals)))
        jump_spin.setValue(state["index"] + 1)
        jump_spin.setToolTip("Jump to rendered page index.")

        def jump_to_index():
            state["index"] = max(0, min(jump_spin.value() - 1, len(visuals) - 1))
            show_page()

        jump_button = QPushButton("Jump")
        jump_button.clicked.connect(lambda checked=False: jump_to_index())

        nav_row.addWidget(previous_button)
        nav_row.addWidget(next_button)
        nav_row.addWidget(QLabel("Rendered page:"))
        nav_row.addWidget(jump_spin)
        nav_row.addWidget(jump_button)
        nav_row.addWidget(open_original_button)
        nav_row.addStretch()
        layout.addLayout(nav_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        show_page()
        dialog.exec()

    def open_knowledge_document_search(self, document_id, initial_query=None):
        document = self.knowledge_library.get_document(document_id)

        if document is None:
            self.set_document_knowledge_status(
                "Document no longer exists in the library."
            )
            return

        dialog = QDialog(self)
        apply_window_defaults(dialog)
        dialog.setWindowTitle(f"Search Inside — {document.get('name', 'Document')}")
        dialog.resize(840, 640)

        layout = QVBoxLayout(dialog)
        title = QLabel(f"<b>{html.escape(str(document.get('name') or 'Document'))}</b>")
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setWordWrap(True)
        layout.addWidget(title)

        search_row = QHBoxLayout()
        query_input = QLineEdit()
        query_input.setPlaceholderText(
            "Search exact words, phrases, page topics, OCR text..."
        )
        search_button = QPushButton("Search")
        search_row.addWidget(query_input, 1)
        search_row.addWidget(search_button)
        layout.addLayout(search_row)

        results_view = QTextBrowser()
        results_view.setObjectName("systemPromptBox")
        results_view.setOpenExternalLinks(False)
        results_view.setPlaceholderText(
            "Search results from this document will appear here."
        )
        layout.addWidget(results_view, 1)

        def page_number_from_section(section_label):
            match = re.search(
                r"\bPage\s+(\d+)\b", str(section_label or ""), flags=re.IGNORECASE
            )
            if not match:
                return None
            try:
                return int(match.group(1))
            except (TypeError, ValueError):
                return None

        def render_results():
            query = query_input.text().strip()

            if not query:
                results_view.setPlainText(
                    "Type something to search for inside this document."
                )
                return

            results = self.knowledge_library.search_document(
                document_id, query, limit=10
            )

            if not results:
                results_view.setPlainText(
                    "No matching text was found inside this document."
                )
                return

            blocks = [
                "<p><b>Search results</b></p>",
                "<p>Use the page links to open the rendered PDF page when an image is available.</p>",
            ]

            for index, result in enumerate(results, start=1):
                section = str(result.get("section_label") or "Section")
                page_number = page_number_from_section(section)
                excerpt = re.sub(r"\s+", " ", str(result.get("content") or "")).strip()
                if len(excerpt) > 700:
                    excerpt = excerpt[:700].rstrip() + "…"

                page_link = ""
                if page_number is not None:
                    page_link = f' · <a href="fzdoc://page/{page_number}">Open page {page_number}</a>'

                blocks.append(
                    "<div style='margin-bottom:14px;'>"
                    f"<b>{index}. {html.escape(section)}</b>{page_link}<br>"
                    f"<span style='color:#9aa5b2;'>Score {float(result.get('score', 0.0) or 0.0):.1f}</span><br>"
                    f"{html.escape(excerpt)}"
                    "</div>"
                )

            results_view.setHtml("\n".join(blocks))

        def open_result_link(url):
            url_text = url.toString()
            match = re.match(r"fzdoc://page/(\d+)$", url_text)

            if not match:
                return

            self.open_knowledge_document_reader(
                document_id, target_page=int(match.group(1))
            )

        search_button.clicked.connect(lambda checked=False: render_results())
        query_input.returnPressed.connect(render_results)
        results_view.anchorClicked.connect(open_result_link)

        if initial_query:
            query_input.setText(str(initial_query).strip())
            render_results()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def start_document_knowledge_import(self):
        if self.knowledge_worker and self.knowledge_worker.isRunning():
            self.set_document_knowledge_status("Document indexing is already running")
            return

        if self.worker and self.worker.isRunning():
            self.set_document_knowledge_status(
                "Finish or stop the current response before indexing documents"
            )
            return

        if getattr(self, "decision_worker", None) and self.decision_worker.isRunning():
            self.set_document_knowledge_status(
                "Finish or stop the web decision before indexing documents"
            )
            return

        if getattr(self, "web_worker", None) and self.web_worker.isRunning():
            self.set_document_knowledge_status(
                "Finish or stop the web search before indexing documents"
            )
            return

        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Import Documents into Knowledge Library",
            "",
            (
                "Supported Documents "
                "(*.pdf *.txt *.md *.csv *.json *.xml *.docx *.xlsx *.pptx "
                "*.py *.js *.html *.htm *.yaml *.yml *.toml *.ini *.log);;"
                "PDF Documents (*.pdf);;"
                "Word Documents (*.docx);;"
                "Spreadsheets (*.xlsx);;"
                "Presentations (*.pptx);;"
                "Text and Code Files "
                "(*.txt *.md *.csv *.json *.xml *.py *.js *.html *.htm "
                "*.yaml *.yml *.toml *.ini *.log)"
            ),
        )

        valid_paths = [path for path in file_paths if os.path.isfile(path)]

        if not valid_paths:
            return

        self.knowledge_worker = DocumentKnowledgeImportWorker(
            self.knowledge_library, valid_paths
        )
        self.knowledge_worker.progress_updated.connect(
            self.handle_document_knowledge_progress
        )
        self.knowledge_worker.import_finished.connect(
            self.handle_document_knowledge_imported
        )
        self.knowledge_worker.error_received.connect(
            self.handle_document_knowledge_error
        )
        self.knowledge_worker.finished.connect(self.finish_document_knowledge_worker)

        self.set_document_knowledge_busy(True)
        self.set_document_knowledge_status(
            f"Indexing {len(valid_paths)} document(s)..."
        )
        self.knowledge_worker.start()

    def handle_document_knowledge_progress(self, text):
        self.set_document_knowledge_status(text)

    def handle_document_knowledge_imported(self, payload):
        results = list(payload.get("results", []))
        errors = list(payload.get("errors", []))
        imported = sum(1 for result in results if result.get("status") == "imported")
        updated = sum(1 for result in results if result.get("status") == "updated")
        duplicates = sum(1 for result in results if result.get("status") == "duplicate")
        characters = sum(
            int(result.get("character_count", 0))
            for result in results
            if result.get("status") != "duplicate"
        )
        chunks = sum(
            int(result.get("chunk_count", 0))
            for result in results
            if result.get("status") != "duplicate"
        )
        visuals = sum(
            int(result.get("visual_count", 0))
            for result in results
            if result.get("status") != "duplicate"
        )

        warning_lines = []

        for result in results:
            for warning in result.get("warnings", []):
                warning_lines.append(f"{result.get('name', 'Document')}: {warning}")

        final_status = (
            f"Knowledge library updated • {characters:,} characters • "
            f"{chunks:,} chunks • {visuals:,} PDF visual pages"
        )
        self.refresh_document_knowledge_view()
        self.set_document_knowledge_status(final_status)

        message_lines = [
            f"Imported: {imported}",
            f"Updated: {updated}",
            f"Already indexed: {duplicates}",
            f"Newly stored extracted text: {characters:,} characters",
            f"New searchable chunks: {chunks:,}",
            f"New PDF chart/image pages: {visuals:,}",
        ]

        if errors:
            message_lines.append(
                "\nFiles that could not be indexed:\n"
                + "\n".join(f"• {item}" for item in errors)
            )

        if warning_lines:
            shown = warning_lines[:20]
            message_lines.append(
                "\nExtraction warnings:\n" + "\n".join(f"• {item}" for item in shown)
            )

            if len(warning_lines) > len(shown):
                message_lines.append(
                    f"• ...and {len(warning_lines) - len(shown)} more warnings"
                )

        QMessageBox.information(
            self, "Document Knowledge Library", "\n".join(message_lines)
        )

    def handle_document_knowledge_error(self, error_text):
        self.set_document_knowledge_status("Document indexing failed")
        QMessageBox.warning(self, "Document Knowledge Library", str(error_text))

    def finish_document_knowledge_worker(self):
        worker = self.knowledge_worker
        self.knowledge_worker = None

        if worker is not None:
            worker.deleteLater()

        self.set_document_knowledge_busy(False)
        self.refresh_document_knowledge_view()
        if self.knowledge_current_status_text:
            self.set_document_knowledge_status(self.knowledge_current_status_text)
        self.update_history_selection_ui()

    def remove_selected_knowledge_documents(self):
        if self.knowledge_list_widget is None:
            return

        selected_items = self.knowledge_list_widget.selectedItems()

        if not selected_items:
            return

        answer = QMessageBox.question(
            self,
            "Remove Documents",
            f"Remove {len(selected_items)} selected document(s) from the "
            "knowledge library?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        removed = 0

        for item in selected_items:
            document_id = item.data(Qt.ItemDataRole.UserRole)

            if document_id and self.knowledge_library.remove_document(document_id):
                removed += 1

        self.refresh_document_knowledge_view()
        self.set_document_knowledge_status(
            f"Removed {removed} document(s) from knowledge library"
        )

    def clear_document_knowledge_library(self):
        documents = self.knowledge_library.list_documents()

        if not documents:
            self.set_document_knowledge_status(
                "Document knowledge library is already empty; compacting storage..."
            )
            self.start_document_knowledge_compaction()
            return

        answer = QMessageBox.question(
            self,
            "Clear Document Knowledge Library",
            f"Permanently remove all {len(documents)} indexed document(s) and compact the database?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            clear_stats = self.knowledge_library.clear()
        except Exception as exc:
            log_exception("FZAstroAI.clear_document_knowledge_library", exc)
            self.set_document_knowledge_status(
                "Document knowledge library clear failed"
            )
            QMessageBox.warning(self, "Document Knowledge Library", str(exc))
            return

        removed = int(clear_stats.get("removed_documents", len(documents)))
        self.refresh_document_knowledge_view()
        self.set_last_tool_result(
            "Document library cleared",
            "success",
            f"Removed {removed:,} document(s). Database compaction started.",
        )
        self.set_document_knowledge_status(
            f"Removed {removed:,} document(s) • compacting document database..."
        )
        self.start_document_knowledge_compaction(show_if_empty=False)

    def start_document_knowledge_compaction(self, show_if_empty=True):
        if self.knowledge_worker and self.knowledge_worker.isRunning():
            self.set_document_knowledge_status(
                "Document maintenance is already running"
            )
            return

        if show_if_empty:
            documents = self.knowledge_library.list_documents()
            stats = self.knowledge_library.storage_stats()

            if not documents and int(stats.get("total_size_bytes", 0)) <= 0:
                self.set_document_knowledge_status(
                    "Document knowledge storage is empty"
                )
                return

        self.knowledge_worker = DocumentKnowledgeMaintenanceWorker(
            self.knowledge_library, action="compact"
        )
        worker = self.knowledge_worker
        worker.progress_updated.connect(self.handle_document_knowledge_progress)
        worker.maintenance_finished.connect(
            self.handle_document_knowledge_maintenance_finished
        )
        worker.error_received.connect(self.handle_document_knowledge_error)
        worker.finished.connect(self.finish_document_knowledge_worker)

        self.set_document_knowledge_busy(True)
        self.set_document_knowledge_status("Compacting document knowledge database...")
        worker.start()

    def handle_document_knowledge_maintenance_finished(self, payload):
        result = dict((payload or {}).get("result") or {})
        before_total = int(result.get("before_total_size_bytes") or 0)
        after_total = int(result.get("total_size_bytes") or 0)
        reclaimed = int(result.get("reclaimed_bytes") or 0)

        status = (
            "Document knowledge database compacted • "
            f"{self.format_storage_size(before_total)} → "
            f"{self.format_storage_size(after_total)}"
        )

        if reclaimed > 0:
            status += f" • reclaimed {self.format_storage_size(reclaimed)}"
        else:
            status += " • no reclaimable space"

        self.refresh_document_knowledge_view()
        self.set_document_knowledge_status(status)
        self.set_last_tool_result(
            "Document database compacted",
            "success",
            status,
            details=(
                f"Database: {self.format_storage_size(result.get('database_size_bytes', 0))}\n"
                f"Assets: {self.format_storage_size(result.get('asset_size_bytes', 0))}\n"
                f"Documents: {int(result.get('document_count', 0))}\n"
                f"Chunks: {int(result.get('chunk_count', 0))}\n"
                f"Visual pages: {int(result.get('visual_count', 0))}"
            ),
        )

    def test_document_knowledge_search(self):
        if self.knowledge_search_input is None:
            return

        query = self.knowledge_search_input.text().strip()

        if not query:
            return

        results = self.knowledge_library.search(query, limit=6, max_characters=18000)
        visuals = self.knowledge_library.search_visuals(query, results, limit=6)

        if self.knowledge_search_preview is None:
            return

        if not results and not visuals:
            self.knowledge_search_preview.setPlainText(
                "No relevant document excerpts or PDF visual pages were found."
            )
            return

        preview_sections = []

        for index, result in enumerate(results, start=1):
            content = result["content"]

            if len(content) > 2500:
                content = content[:2500].rstrip() + "\n[...]"

            preview_sections.append(
                f"TEXT RESULT {index}\n"
                f"Source: {result['document_name']}\n"
                f"Location: {result['section_label']}\n"
                f"Relevance score: {result['score']:.1f}\n\n"
                f"{content}"
            )

        for index, visual in enumerate(visuals, start=1):
            preview_sections.append(
                f"PDF VISUAL {index}\n"
                f"Source: {visual['document_name']}\n"
                f"Page: {visual['page_number']}\n"
                f"Type: {visual['kind']}\n"
                f"Dimensions: {visual['width']}x{visual['height']}\n"
                f"Stored image: {visual['file_path']}\n"
                f"Relevance score: {visual['score']:.1f}"
            )

        self.knowledge_search_preview.setPlainText(
            "\n\n========================================\n\n".join(preview_sections)
        )

    def resolve_document_targets_for_query(self, current_text, recent_context=""):
        """Resolve ordinal document references for local-library follow-ups."""
        try:
            documents = self.knowledge_library.list_documents()
        except Exception as exc:
            log_exception(
                "FZAstroAI.resolve_document_targets_for_query line 17885", exc
            )
            documents = []

        documents = [dict(item) for item in documents]

        if not documents:
            return []

        current = re.sub(r"\s+", " ", str(current_text or "")).strip().casefold()
        recent = str(recent_context or "")
        targets = []

        ordinal_map = (
            (1, ("first", "1st")),
            (2, ("second", "2nd")),
            (3, ("third", "3rd")),
            (4, ("fourth", "4th")),
            (5, ("fifth", "5th")),
        )

        for number in self.knowledge_library._explicit_document_numbers_from_request(
            current
        ):
            index = number - 1

            if 0 <= index < len(documents):
                targets.append(str(documents[index].get("name") or "").strip())

        for position, words in ordinal_map:
            if any(
                re.search(
                    rf"\b{re.escape(word)}\s+(?:book|manual|document|doc|pdf|file)s?\b",
                    current,
                    flags=re.IGNORECASE,
                )
                for word in words
            ):
                index = position - 1

                if 0 <= index < len(documents):
                    targets.append(str(documents[index].get("name") or "").strip())

        if (
            re.search(
                r"\b(?:last|final)\s+(?:book|manual|document|doc|pdf|file)s?\b",
                current,
                flags=re.IGNORECASE,
            )
            and documents
        ):
            targets.append(str(documents[-1].get("name") or "").strip())

        active_document_id = self.active_knowledge_document_id_or_none()
        if active_document_id and re.search(
            r"\b(?:this|that|same|selected|current)\s+"
            r"(?:book|manual|document|doc|pdf|file)s?\b|"
            r"^answer\s+using\s+only\s+this\s+"
            r"(?:imported\s+)?(?:document|book|pdf)\s*:",
            current,
            flags=re.IGNORECASE,
        ):
            for document in documents:
                if str(document.get("id") or "") == active_document_id:
                    targets.append(str(document.get("name") or "").strip())
                    break

        other_match = re.search(
            r"\bother\s+(?P<count>\d+|one|two|three|four|five)?\s*"
            r"(?:book|manual|document|doc|pdf|file)s?\b",
            current,
            flags=re.IGNORECASE,
        )

        if other_match:
            number_words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
            raw_count = str(other_match.group("count") or "").casefold()

            try:
                requested_count = (
                    int(raw_count) if raw_count else max(1, len(documents) - 1)
                )
            except ValueError:
                requested_count = number_words.get(
                    raw_count, max(1, len(documents) - 1)
                )

            excluded_ids = set()
            recent_lower = recent.casefold()
            normalized_recent = self.knowledge_library._normalized_document_name(recent)
            mention_positions = []

            for document in documents:
                document_id = str(document.get("id") or "")
                document_name = str(document.get("name") or "")
                normalized_name = self.knowledge_library._normalized_document_name(
                    document_name
                )
                raw_position = (
                    recent_lower.rfind(document_name.casefold())
                    if document_name
                    else -1
                )
                normalized_position = (
                    normalized_recent.rfind(normalized_name) if normalized_name else -1
                )
                position = max(raw_position, normalized_position)

                if document_id and position >= 0:
                    mention_positions.append((position, document_id))

            if mention_positions:
                # Exclude only the most recently discussed document.  The
                # inventory list may contain every title, so excluding every
                # mention would make "the other books" resolve to nothing.
                mention_positions.sort(reverse=True)
                excluded_ids.add(mention_positions[0][1])

            if not excluded_ids and documents:
                excluded_ids.add(str(documents[0].get("id") or ""))

            for document in documents:
                document_id = str(document.get("id") or "")

                if document_id in excluded_ids:
                    continue

                targets.append(str(document.get("name") or "").strip())

                if len(targets) >= requested_count:
                    break

        clean_targets = []
        seen = set()

        for target in targets:
            target = re.sub(r"\s+", " ", target).strip()
            key = target.casefold()

            if target and key not in seen:
                seen.add(key)
                clean_targets.append(target)

        return clean_targets[:5]

    def build_document_knowledge_query(self, current_text):
        current_request = str(current_text or "").strip()
        recent_parts = []

        for message in self.messages[-5:-1]:
            text = self.history_message_to_text(message.get("content", "")).strip()

            if not text:
                continue

            if len(text) > 1200:
                text = text[-1200:]

            recent_parts.append(text)

        recent_context_text = "\n".join(recent_parts)
        resolved_document_targets = self.resolve_document_targets_for_query(
            current_request,
            recent_context_text,
        )

        if resolved_document_targets:
            target_lines = [
                "The current request refers to these imported document(s):",
                *[f"- {name}" for name in resolved_document_targets],
                "Use these title(s) as retrieval anchors for the local Document Knowledge Library.",
            ]
            current_request = (
                current_request
                + "\n\n[RESOLVED DOCUMENT TARGETS]\n"
                + "\n".join(target_lines)
            )

        current_section = f"[CURRENT REQUEST]\n{current_request}"
        sections = [current_section]

        if recent_parts:
            sections.append("[RECENT CONTEXT]\n" + recent_context_text)

        combined = "\n".join(sections)

        if len(combined) > 5000:
            # Always retain the complete current request; trim only older context.
            remaining = max(0, 5000 - len(current_section) - 20)
            recent_text = "\n".join(recent_parts)
            combined = current_section

            if remaining and recent_text:
                combined += "\n[RECENT CONTEXT]\n" + recent_text[-remaining:]

        return combined

    def toggle_pin_chat(self, chat_id):
        for record in self.chat_history:
            if record.get("id") == chat_id:
                record["pinned"] = not record.get("pinned", False)
                record["updated"] = datetime.now().isoformat()
                break

        save_chat_history(self.chat_history)
        self.render_history()

    def rename_chat(self, chat_id):
        for record in self.chat_history:
            if record.get("id") != chat_id:
                continue

            current_title = record.get("title", "New Chat")

            new_title, ok = QInputDialog.getText(
                self, "Rename Chat", "New title:", text=current_title
            )

            if ok and new_title.strip():
                record["title"] = new_title.strip()
                record["updated"] = datetime.now().isoformat()
                save_chat_history(self.chat_history)
                self.render_history()

            break

    def delete_chat(self, chat_id):
        self.selected_history_ids.discard(chat_id)
        self.chat_history = [
            record for record in self.chat_history if record.get("id") != chat_id
        ]

        if self.active_chat_id == chat_id:
            self.active_chat_id = None
            self.messages.clear()
            self.current_stream_widget = None
            self.current_assistant_message_id = None
            self._last_thoughts_text = ""
            self.global_thought_box.setMarkdown("")

            while self.chat_layout.count() > 0:
                item = self.chat_layout.takeAt(0)

                if item.widget():
                    item.widget().deleteLater()

            self.empty_state_widget = None
            self.show_empty_chat_state()

        save_chat_history(self.chat_history)
        self.render_history()

    def new_chat(self):
        if self.worker and self.worker.isRunning():
            return

        python_worker = getattr(self, "python_worker", None)

        if python_worker is not None and python_worker.isRunning():
            return

        if (
            hasattr(self, "web_worker")
            and self.web_worker
            and self.web_worker.isRunning()
        ):
            return

        self.save_current_chat()
        self.messages.clear()
        self.attached_files.clear()
        self.active_chat_id = None

        while self.chat_layout.count() > 0:
            item = self.chat_layout.takeAt(0)

            if item.widget():
                item.widget().deleteLater()

        self.empty_state_widget = None
        self.current_stream_widget = None
        self.current_assistant_message_id = None
        self._last_thoughts_text = ""
        self.global_thought_box.setMarkdown("")

        self.input_box.clear()
        self.render_attachments()
        self.show_empty_chat_state()

        # A new chat must not retain request-specific status text from the
        # previous conversation. The independent local clock remains visible.
        self.set_idle_ui_state("")
        self.update_clock_label()

    def _add_skill_actions_to_menu(self, menu, skill_id):
        """Populate *menu* from the user-facing skill registry."""
        for section_name, actions in skill_actions_by_section(skill_id).items():
            if menu.actions():
                menu.addSeparator()

            if section_name:
                section_action = QAction(section_name, self)
                section_action.setEnabled(False)
                menu.addAction(section_action)

            for action_spec in actions:
                action = QAction(action_spec.label, self)
                action.setToolTip(action_spec.description)
                action.triggered.connect(
                    lambda checked=False, action_id=action_spec.action_id: (
                        self.run_skill_action(action_id)
                    )
                )
                menu.addAction(action)

    def build_skill_menu(self, skill_id):
        menu = QMenu(self)
        skill = SKILL_BY_ID.get(skill_id)

        if skill is None:
            missing_action = QAction("Unknown skill", self)
            missing_action.setEnabled(False)
            menu.addAction(missing_action)
            return menu

        self._add_skill_actions_to_menu(menu, skill_id)
        return menu

    def build_composer_skills_menu(self):
        menu = QMenu(self)

        for skill in SKILLS:
            skill_menu = menu.addMenu(skill.label)
            skill_menu.setToolTipsVisible(True)
            self._add_skill_actions_to_menu(skill_menu, skill.skill_id)

        return menu

    def run_skill_action(self, action_id):
        """Dispatch one user-facing Skill action to the existing execution layer."""
        action_spec = SKILL_ACTION_BY_ID.get(action_id)

        if action_spec is None:
            self.stats_label.setText("Unknown skill action.")
            return

        if action_spec.kind == "composer":
            composer_action_id = action_spec.composer_action_id or action_id
            self.run_composer_action(composer_action_id)
            return

        if action_spec.kind != "direct":
            self.stats_label.setText(f"Unsupported skill action: {action_spec.kind}")
            return

        handler_name = action_spec.handler_name
        handler = getattr(self, str(handler_name or ""), None)

        if not callable(handler):
            self.stats_label.setText(
                f"No handler for skill action: {action_spec.label}"
            )
            return

        handler(*action_spec.handler_args, **action_spec.kwargs)

    def _add_registry_actions_to_menu(self, menu, groups=None):
        for group_name, actions in composer_actions_by_group(groups).items():
            group_menu = menu.addMenu(group_name)

            for action_spec in actions:
                action = QAction(action_spec.label, self)
                action.setToolTip(action_spec.description)
                action.triggered.connect(
                    lambda checked=False, action_id=action_spec.action_id: (
                        self.run_composer_action(action_id)
                    )
                )
                group_menu.addAction(action)

    def build_composer_code_menu(self):
        menu = QMenu(self)

        wrap_action = QAction("Wrap selection as code", self)
        wrap_action.setToolTip(
            "Wrap selected composer text as a Markdown code fence. Ctrl+K also runs this."
        )
        wrap_action.triggered.connect(
            lambda checked=False: self.mark_input_selection_as_code()
        )
        menu.addAction(wrap_action)

        paste_action = QAction("Paste clipboard as code", self)
        paste_action.setToolTip("Paste clipboard text directly as a code fence.")
        paste_action.triggered.connect(
            lambda checked=False: self.paste_clipboard_as_code()
        )
        menu.addAction(paste_action)
        menu.addSeparator()
        self._add_registry_actions_to_menu(menu, CODE_MENU_GROUPS)
        return menu

    def build_composer_add_menu(self):
        menu = QMenu(self)

        actions = [
            (
                "Paste code",
                self.paste_clipboard_as_code,
                "Paste clipboard text as a Markdown code fence.",
            ),
            ("Attach files", self.attach_files, "Attach files to the current message."),
            (
                "Import PDF/document",
                self.open_document_knowledge_library,
                "Open the Document Knowledge Library and import searchable documents.",
            ),
            (
                "Add project/context prompt",
                self.show_active_context_dialog,
                "Inspect current context before adding or sending more information.",
            ),
            (
                "Add screenshot",
                self.attach_files,
                "Attach an image or screenshot file.",
            ),
        ]

        for label, handler, tooltip in actions:
            action = QAction(label, self)
            action.setToolTip(tooltip)
            action.triggered.connect(lambda checked=False, fn=handler: fn())
            menu.addAction(action)

        return menu

    def build_composer_actions_menu(self):
        menu = QMenu(self)
        self._add_registry_actions_to_menu(menu, TEXT_ACTION_MENU_GROUPS)
        return menu

    def build_composer_library_menu(self):
        menu = QMenu(self)

        open_library = QAction("Imported documents", self)
        open_library.setToolTip("Open the Document Knowledge Library.")
        open_library.triggered.connect(
            lambda checked=False: self.open_document_knowledge_library()
        )
        menu.addAction(open_library)

        menu.addSeparator()
        self._add_registry_actions_to_menu(menu, LIBRARY_MENU_GROUPS)

        menu.addSeparator()
        context_action = QAction("Show active context", self)
        context_action.triggered.connect(
            lambda checked=False: self.show_active_context_dialog()
        )
        menu.addAction(context_action)

        memory_action = QAction("Open persistent memory", self)
        memory_action.triggered.connect(
            lambda checked=False: self.open_persistent_memory_library()
        )
        menu.addAction(memory_action)

        runtime_action = QAction("Runtime/model status", self)
        runtime_action.triggered.connect(
            lambda checked=False: self.show_runtime_model_status_dialog()
        )
        menu.addAction(runtime_action)

        last_tool_action = QAction("Last tool result", self)
        last_tool_action.triggered.connect(
            lambda checked=False: self.show_last_tool_result_dialog()
        )
        menu.addAction(last_tool_action)
        return menu

    def build_composer_context_menu(self):
        menu = QMenu(self)

        actions = [
            ("Show active context", self.show_active_context_dialog),
            ("Show indexed documents", self.show_indexed_documents_context),
            ("Show persistent memory", self.open_persistent_memory_library),
            ("Show runtime/model status", self.show_runtime_model_status_dialog),
            ("Show last tool result", self.show_last_tool_result_dialog),
        ]

        for label, handler in actions:
            action = QAction(label, self)
            action.triggered.connect(lambda checked=False, fn=handler: fn())
            menu.addAction(action)

        return menu

    def build_composer_persona_menu(self):
        menu = QMenu(self)

        actions = [
            ("Show assistant persona", self.show_current_persona_dialog),
            ("Insert assistant persona question", self.insert_current_persona_question),
            ("Open System Prompt Editor", self.open_system_prompt_editor),
            ("Open Persistent Memory", self.open_persistent_memory_library),
        ]

        for label, handler in actions:
            action = QAction(label, self)
            action.triggered.connect(lambda checked=False, fn=handler: fn())
            menu.addAction(action)

        return menu

    def selected_or_full_composer_text(self):
        cursor = self.input_box.textCursor()
        selected_text = cursor.selectedText().replace("\u2029", "\n").strip()

        if selected_text:
            return selected_text

        return self.input_box.toPlainText().strip()

    def run_composer_action(self, action_id):
        action_spec = COMPOSER_ACTION_BY_ID.get(action_id)

        if action_spec is None:
            self.stats_label.setText("Unknown composer action.")
            return

        if action_id == "python.run_input":
            self.run_python_from_input()
            return

        if action_id == "python.run_selection":
            self.run_selected_python_from_composer()
            return

        values = {}

        for field in action_spec.fields:
            if field.name in {"code", "text"}:
                value = self.selected_or_full_composer_text()

                if not value:
                    if field.name == "code":
                        message = "Select or paste code/error text before using this Code action."
                    else:
                        message = "Select or type text in the composer before using this action."

                    self.stats_label.setText(message)
                    self.input_box.setFocus()
                    return
            elif field.kind == "int":
                value, accepted = QInputDialog.getInt(
                    self,
                    action_spec.label,
                    field.label,
                    int(field.default or field.minimum),
                    field.minimum,
                    field.maximum,
                )

                if not accepted:
                    self.input_box.setFocus()
                    return
            else:
                value, accepted = QInputDialog.getText(
                    self,
                    action_spec.label,
                    field.label,
                    text=str(field.default or ""),
                )

                if not accepted:
                    self.input_box.setFocus()
                    return

            value = str(value).strip()

            if not value:
                self.stats_label.setText("Composer action cancelled: missing input.")
                self.input_box.setFocus()
                return

            values[field.name] = value

        if action_spec.mode == "direct":
            self.run_direct_composer_action(action_id, values)
            self.input_box.setFocus()
            return

        try:
            prompt = build_composer_action_prompt(action_id, values)
        except (KeyError, ValueError) as exc:
            self.stats_label.setText(str(exc))
            self.input_box.setFocus()
            return

        self.insert_prompt_into_composer(prompt)
        self.stats_label.setText(f"Inserted action prompt: {action_spec.label}.")

    def run_direct_composer_action(self, action_id, values):
        """Run app/UI composer actions without sending text to the LLM."""
        values = values or {}

        if action_id == "documents.list_documents":
            self.show_knowledge_documents_in_chat()
            return

        if action_id == "documents.brief_document":
            self.brief_knowledge_document_by_reference(values.get("title"))
            return

        if action_id == "documents.open_as_book":
            self.open_knowledge_document_reader_by_reference(values.get("title"))
            return

        if action_id == "documents.search_inside":
            self.search_knowledge_document_by_reference(
                values.get("title"), initial_query=values.get("query")
            )
            return

        if action_id == "documents.show_page_image":
            self.open_knowledge_document_reader_by_reference(
                values.get("title"), target_page=values.get("page")
            )
            return

        self.stats_label.setText(f"No direct handler for composer action: {action_id}")

    def resolve_knowledge_document_id(self, reference):
        """Resolve a user-facing document reference to a stored document id.

        Accepts the document id, exact title, stem, case-insensitive partial
        title, or a 1-based list number such as ``1`` for the first imported
        document.  This lets local UI actions like "Open as book: 1" execute
        deterministically instead of being sent to the model.
        """
        documents = list(self.knowledge_library.list_documents())

        if not documents:
            QMessageBox.information(
                self,
                "Document Library",
                "No documents are currently imported in the Document Knowledge Library.",
            )
            self.stats_label.setText("No imported documents available.")
            return None

        raw_reference = str(reference or "").strip()
        normalized_reference = re.sub(r"\s+", " ", raw_reference).strip()
        lowered_reference = normalized_reference.casefold()

        if lowered_reference in {
            "",
            "this",
            "this document",
            "selected",
            "selected document",
            "current",
        }:
            selected_id = self.selected_knowledge_document_id()

            if selected_id:
                return selected_id

            if len(documents) == 1:
                return documents[0]["id"]

        if normalized_reference.isdigit():
            index = int(normalized_reference) - 1

            if 0 <= index < len(documents):
                return documents[index]["id"]

        for document in documents:
            if normalized_reference == str(document.get("id") or ""):
                return document["id"]

        def document_names(document):
            name = str(document.get("name") or "").strip()
            stem = Path(name).stem.strip()
            return [value.casefold() for value in (name, stem) if value]

        exact_matches = [
            document
            for document in documents
            if lowered_reference and lowered_reference in document_names(document)
        ]

        if len(exact_matches) == 1:
            return exact_matches[0]["id"]

        partial_matches = [
            document
            for document in documents
            if lowered_reference
            and any(
                lowered_reference in candidate or candidate in lowered_reference
                for candidate in document_names(document)
            )
        ]

        if len(partial_matches) == 1:
            return partial_matches[0]["id"]

        preview_lines = [
            f"{index + 1}. {document.get('name', 'Document')}"
            for index, document in enumerate(documents[:12])
        ]
        suffix = (
            "" if len(documents) <= 12 else f"\n...and {len(documents) - 12:,} more."
        )
        QMessageBox.warning(
            self,
            "Document Not Found",
            (
                f"Could not match '{raw_reference or '(blank)'}' to one imported document.\n\n"
                "Use the document title or its number from this list:\n"
                + "\n".join(preview_lines)
                + suffix
            ),
        )
        self.stats_label.setText("Document action cancelled: document not found.")
        return None

    def open_knowledge_document_reader_by_reference(self, reference, target_page=None):
        document_id = self.resolve_knowledge_document_id(reference)

        if not document_id:
            return False

        self.open_knowledge_document_reader(document_id, target_page=target_page)
        self.stats_label.setText("Opened document locally as a book.")
        return True

    def brief_knowledge_document_by_reference(self, reference):
        document_id = self.resolve_knowledge_document_id(reference)

        if not document_id:
            return False

        return self.ask_knowledge_document_with_llm(
            document_id,
            "Give me a concise brief of this imported document. Include what it is, "
            "the main topics, useful sections, and key takeaways.",
            display_prompt="Brief this imported document.",
            status_label="Generating selected document brief with the LLM... • 0.00s",
        )

    def search_knowledge_document_by_reference(self, reference, initial_query=None):
        document_id = self.resolve_knowledge_document_id(reference)

        if not document_id:
            return False

        self.open_knowledge_document_search(document_id, initial_query=initial_query)
        self.stats_label.setText("Opened local document search.")
        return True

    def try_handle_local_composer_command(self, text):
        """Intercept local document UI commands before chat generation.

        This protects prompts inserted by older builds, such as
        ``Open this document as a book: 1``, from entering the LLM/RAG path and
        producing a summary instead of opening the reader.
        """
        original_text = str(text or "").strip()

        if not original_text:
            return False

        clean = re.sub(r"\s+", " ", original_text).strip()
        clean_lower = clean.casefold()

        if clean_lower in {"/docs", "/documents", "/books", "/library"}:
            self.show_knowledge_documents_in_chat()
            return True

        if re.fullmatch(
            r"(?:list|show|display|give|tell|name)\s+"
            r"(?:the\s+)?(?:imported\s+|indexed\s+|available\s+|loaded\s+)?"
            r"(?:books|documents|docs|pdfs|files)"
            r"(?:\s+(?:we|i)\s+have)?\s*\??",
            clean,
            flags=re.IGNORECASE,
        ) or re.fullmatch(
            r"(?:what|which)\s+(?:books|documents|docs|pdfs|files)\s+"
            r"(?:(?:do\s+)?(?:we|i)\s+have|"
            r"are\s+(?:imported|indexed|stored|available|loaded))\s*\??",
            clean,
            flags=re.IGNORECASE,
        ):
            self.show_knowledge_documents_in_chat()
            return True

        select_match = re.match(
            r"^/(?:select|use|doc|document|book)\s+(?P<title>.+)$",
            clean,
            flags=re.IGNORECASE,
        )

        if select_match:
            return self.activate_knowledge_document_by_reference(
                select_match.group("title")
            )

        if clean_lower in {"/book", "/reader", "/openbook", "/open book"}:
            document_id = self.active_knowledge_document_id_or_none()
            if not document_id:
                self._show_active_knowledge_document_required("open a book")
                return True
            self.open_knowledge_document_reader(document_id)
            self.stats_label.setText("Opened selected document locally as a book.")
            return True

        if clean_lower == "/brief":
            document_id = self.active_knowledge_document_id_or_none()
            if not document_id:
                self._show_active_knowledge_document_required("brief a document")
                return True
            self.ask_knowledge_document_with_llm(
                document_id,
                "Give me a concise brief of this imported document. Include what it is, "
                "the main topics, useful sections, and key takeaways.",
                display_prompt="Brief the selected imported document.",
                status_label="Generating selected document brief with the LLM... • 0.00s",
            )
            return True

        selected_search_match = re.match(
            r"^/search(?:\s+(?P<query>.+))?$",
            clean,
            flags=re.IGNORECASE,
        )

        if selected_search_match:
            document_id = self.active_knowledge_document_id_or_none()
            if not document_id:
                self._show_active_knowledge_document_required(
                    "search inside a document"
                )
                return True
            self.open_knowledge_document_search(
                document_id, initial_query=selected_search_match.group("query")
            )
            self.stats_label.setText("Opened selected document search.")
            return True

        open_match = re.match(
            r"^open\s+(?:(?:this|the)\s+)?(?:document|book|pdf)"
            r"(?:\s+as\s+(?:a\s+)?(?:book|reader))?\s*:\s*(?P<title>.+)$",
            clean,
            flags=re.IGNORECASE,
        ) or re.match(
            r"^open\s+(?:as\s+)?(?:a\s+)?(?:book|reader)\s*:\s*(?P<title>.+)$",
            clean,
            flags=re.IGNORECASE,
        )

        if open_match:
            return self.open_knowledge_document_reader_by_reference(
                open_match.group("title")
            )

        brief_match = re.match(
            r"^brief\s+(?:(?:this|the)\s+)?(?:document|book|pdf)\s*:\s*(?P<title>.+)$",
            clean,
            flags=re.IGNORECASE,
        )

        if brief_match:
            return self.brief_knowledge_document_by_reference(
                brief_match.group("title")
            )

        search_match = re.match(
            r"^search\s+inside\s+(?:(?:this|the)\s+)?(?:document|book|pdf)"
            r"\s*:\s*(?P<title>.+?)\s+find\s*:\s*(?P<query>.+)$",
            clean,
            flags=re.IGNORECASE,
        )

        if search_match:
            return self.search_knowledge_document_by_reference(
                search_match.group("title"), initial_query=search_match.group("query")
            )

        page_match = re.match(
            r"^show\s+page\s+(?P<page>\d+)\s+of\s+(?P<title>.+?)"
            r"\s+as\s+(?:an?\s+)?image\.?$",
            clean,
            flags=re.IGNORECASE,
        )

        if page_match:
            return self.open_knowledge_document_reader_by_reference(
                page_match.group("title"), target_page=page_match.group("page")
            )

        return False

    def run_selected_python_from_composer(self):
        cursor = self.input_box.textCursor()
        code = cursor.selectedText().replace("\u2029", "\n").strip()

        if not code:
            self.stats_label.setText("Select Python code in the composer first.")
            self.input_box.setFocus()
            return

        self.execute_python_code(make_fenced_code("python", code), force=True)

    def show_text_dialog(self, title, body, *, html_body=False):
        dialog = QDialog(self)
        apply_window_defaults(dialog)
        dialog.setWindowTitle(title)
        dialog.resize(760, 560)

        layout = QVBoxLayout(dialog)
        viewer = QTextBrowser()
        viewer.setObjectName("systemPromptBox")
        viewer.setOpenExternalLinks(True)

        if html_body:
            viewer.setHtml(str(body or ""))
        else:
            viewer.setPlainText(str(body or ""))

        layout.addWidget(viewer, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    @staticmethod
    def format_storage_size(byte_count):
        value = float(max(0, int(byte_count or 0)))

        for unit in ("B", "KB", "MB", "GB", "TB"):
            if value < 1024 or unit == "TB":
                if unit == "B":
                    return f"{int(value)} {unit}"
                return f"{value:.1f} {unit}"
            value /= 1024.0

        return f"{value:.1f} TB"

    def set_last_tool_result(self, title, status="info", body="", details=""):
        self.last_tool_result = {
            "title": str(title or "Tool result"),
            "status": str(status or "info"),
            "body": str(body or ""),
            "details": str(details or ""),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def current_persona_summary(self):
        active_key = str(getattr(self, "active_calibration_profile", "") or "")
        profile = (self.calibration_profiles or {}).get(active_key, {})
        profile_name = profile.get("name") or active_key or "Custom"
        prompt_text = self.system_prompt.toPlainText().strip()

        return (
            f"Active persona/calibration: {profile_name}\n"
            f"Profile key: {active_key or 'custom'}\n"
            f"System prompt characters: {len(prompt_text):,}\n\n"
            "Current system prompt:\n\n"
            f"{prompt_text or '(empty)'}"
        )

    def current_persona_chat_summary(self):
        active_key = str(getattr(self, "active_calibration_profile", "") or "")
        profile = (self.calibration_profiles or {}).get(active_key, {})
        profile_name = profile.get("name") or active_key or "Custom"
        prompt_text = self.system_prompt.toPlainText().strip()

        return (
            "This is FZAstro AI's assistant persona/profile, not the user's "
            "personal profile.\n\n"
            f"- Active calibration: {profile_name}\n"
            f"- Profile key: {active_key or 'custom'}\n"
            f"- System prompt size: {len(prompt_text):,} characters\n\n"
            "Use Persona → Show assistant persona to view the full active "
            "system prompt."
        )

    def show_current_persona_dialog(self):
        self.show_text_dialog("Assistant Persona", self.current_persona_summary())

    def insert_current_persona_question(self):
        from .persona_routing import ASSISTANT_PERSONA_PROMPT

        self.insert_prompt_into_composer(ASSISTANT_PERSONA_PROMPT)
        self.stats_label.setText("Inserted assistant persona question.")

    def show_active_context_dialog(self):
        documents = self.knowledge_library.list_documents()
        memory_entries = self.persistent_memory_data.get("entries", [])
        attachments = list(getattr(self, "attached_files", []) or [])
        active_profile = str(getattr(self, "active_calibration_profile", "") or "")
        profile_name = (
            (self.calibration_profiles or {})
            .get(active_profile, {})
            .get("name", active_profile or "Custom")
        )
        last_tool = getattr(self, "last_tool_result", None) or {}

        lines = [
            "Active Context",
            "==============",
            f"Model: {self.current_model_name()}",
            f"Provider URL: {self.server_url.text().strip()}",
            f"Persona/calibration: {profile_name}",
            f"Attached files pending: {len(attachments)}",
            f"Indexed documents: {len(documents)}",
            f"Persistent memory entries: {len(memory_entries)}",
            f"Last tool result: {last_tool.get('title', 'None')}",
        ]

        if attachments:
            lines.extend(["", "Pending attachments:"])
            lines.extend(f"- {Path(path).name}" for path in attachments)

        self.show_text_dialog("Active Context", "\n".join(lines))

    def show_indexed_documents_context(self):
        body = self.knowledge_library.format_document_inventory_response()
        self.show_text_dialog("Indexed Documents", body, html_body=body.startswith("<"))

    @staticmethod
    def _knowledge_document_chat_link(action, document_id, label):
        safe_action = html.escape(str(action or "").strip().lower(), quote=True)
        safe_document_id = html.escape(str(document_id or "").strip(), quote=True)
        safe_label = html.escape(str(label or "").strip())
        return (
            f'<a href="fzastro://document?action={safe_action}&amp;id={safe_document_id}">'
            f"{safe_label}</a>"
        )

    def format_knowledge_documents_chat_picker(self):
        documents = list(self.knowledge_library.list_documents())

        if not documents:
            return (
                '<div class="document-inventory">'
                "<p><strong>Imported documents</strong></p>"
                "<p>No documents are currently imported in the Document Knowledge Library.</p>"
                "<p>Use <strong>Document Knowledge Library → Import Documents</strong> first.</p>"
                "</div>"
            )

        active_document_id = str(
            getattr(self, "active_knowledge_document_id", "") or ""
        )
        total_visuals = sum(
            int(document.get("visual_count") or 0) for document in documents
        )

        lines = [
            '<div class="document-inventory">',
            "<p><strong>Imported documents</strong></p>",
            (
                f"<p>{len(documents):,} document(s) indexed · "
                f"{total_visuals:,} visual page(s). Click a title or action below; "
                "these are local UI actions, not LLM prompts.</p>"
            ),
        ]

        for index, document in enumerate(documents, start=1):
            document_id = str(document.get("id") or "").strip()
            name = str(document.get("name") or "Untitled document").strip()
            title_link = self._knowledge_document_chat_link(
                "options", document_id, name
            )
            character_count = int(document.get("character_count") or 0)
            chunk_count = int(document.get("chunk_count") or 0)
            section_count = int(document.get("section_count") or 0)
            visual_count = int(document.get("visual_count") or 0)
            searchable_state = (
                "Text searchable" if character_count > 0 else "No searchable text"
            )
            selected_badge = (
                " · <strong>Selected</strong>"
                if document_id == active_document_id
                else ""
            )
            actions = " · ".join(
                [
                    self._knowledge_document_chat_link("select", document_id, "Select"),
                    self._knowledge_document_chat_link("brief", document_id, "Brief"),
                    self._knowledge_document_chat_link(
                        "open", document_id, "Open as Book"
                    ),
                    self._knowledge_document_chat_link(
                        "search", document_id, "Search Inside"
                    ),
                    self._knowledge_document_chat_link("ask", document_id, "Ask"),
                ]
            )
            lines.append(
                "<p>"
                f"<strong>{index}. {title_link}</strong>{selected_badge}<br>"
                f"{character_count:,} characters · {chunk_count:,} chunks · "
                f"{section_count:,} sections · {visual_count:,} visual pages · "
                f"{html.escape(searchable_state)}<br>"
                f"{actions}"
                "</p>"
            )

        lines.append(
            "<p>Commands: <code>/docs</code>, <code>/select 1</code>, "
            "<code>/book</code>, <code>/brief</code>, "
            "<code>/search moon phases</code>.</p>"
        )
        lines.append("</div>")
        return "\n".join(lines).strip()

    def show_knowledge_documents_in_chat(self):
        body = self.format_knowledge_documents_chat_picker()
        self.add_message_widget(
            "Assistant",
            body,
            source_tags=["Docs"],
            animate=True,
        )
        self.stats_label.setText("Displayed imported documents in chat.")

    def _show_active_knowledge_document_required(self, action_label="run that action"):
        self.stats_label.setText(f"Select a document before trying to {action_label}.")
        self.add_message_widget(
            "Assistant",
            "Select a document first from the imported document list, then run the action again.",
            source_tags=["Docs"],
            animate=True,
        )
        self.show_knowledge_documents_in_chat()

    def activate_knowledge_document_by_id(self, document_id, *, announce=True):
        document = self.knowledge_library.get_document(document_id)

        if document is None:
            self.stats_label.setText("Document no longer exists in the library.")
            return False

        self.active_knowledge_document_id = str(document_id)
        title = str(document.get("name") or "Document")
        self.stats_label.setText(f"Selected document: {title}")

        if announce:
            self.add_message_widget(
                "Assistant",
                (
                    f"Active document: **{title}**\n\n"
                    "Now you can use `/book`, `/brief`, or `/search your query`."
                ),
                source_tags=["Docs"],
                animate=True,
            )

        return True

    def activate_knowledge_document_by_reference(self, reference, *, announce=True):
        document_id = self.resolve_knowledge_document_id(reference)

        if not document_id:
            return False

        return self.activate_knowledge_document_by_id(document_id, announce=announce)

    def active_knowledge_document_id_or_none(self):
        document_id = str(
            getattr(self, "active_knowledge_document_id", "") or ""
        ).strip()

        if not document_id:
            return None

        if self.knowledge_library.get_document(document_id) is None:
            self.active_knowledge_document_id = ""
            return None

        return document_id

    def handle_knowledge_document_chat_action(self, action, document_id):
        action = str(action or "").strip().lower()
        document_id = str(document_id or "").strip()
        document = self.knowledge_library.get_document(document_id)

        if document is None:
            self.stats_label.setText("Document no longer exists in the library.")
            return

        if action == "select":
            self.activate_knowledge_document_by_id(document_id)
            return

        if action == "options":
            self.open_knowledge_document_options(document_id)
            return

        if action in {"open", "book", "reader"}:
            self.open_knowledge_document_reader(document_id)
            self.stats_label.setText("Opened document locally as a book.")
            return

        if action == "brief":
            self.ask_knowledge_document_with_llm(
                document_id,
                "Give me a concise brief of this imported document. Include what it is, "
                "the main topics, useful sections, and key takeaways.",
                display_prompt=f"Brief imported document: {document.get('name', 'Document')}",
                status_label="Generating selected document brief with the LLM... • 0.00s",
            )
            return

        if action == "search":
            self.open_knowledge_document_search(document_id)
            self.stats_label.setText("Opened local document search.")
            return

        if action == "ask":
            self.activate_knowledge_document_by_id(document_id, announce=False)
            self.insert_document_question_prompt(document)
            return

        self.stats_label.setText(f"Unknown document action: {action or '(blank)'}")

    def show_runtime_model_status_dialog(self):
        base_url = self.server_url.text().strip()
        model_name = self.current_model_name()
        is_local_ollama = is_local_ollama_base_url(base_url)
        owned_ollama = getattr(self, "_fzastro_owned_ollama_process", None)
        owned_status = "started by FZAstro" if owned_ollama is not None else "not owned"
        gpu_text = (
            self.gpu_label.text() if hasattr(self, "gpu_label") else "Unavailable"
        )
        system_text = (
            self.system_label.text() if hasattr(self, "system_label") else "Unavailable"
        )

        lines = [
            "Runtime / Model Status",
            "======================",
            f"Selected model: {model_name}",
            f"Provider URL: {base_url}",
            f"Local Ollama endpoint: {'yes' if is_local_ollama else 'no'}",
            f"Ollama ownership: {owned_status}",
            f"Auto-start Ollama: {os.environ.get('FZASTRO_AUTO_START_OLLAMA', '1')}",
            f"Stop owned Ollama on exit: {os.environ.get('FZASTRO_STOP_OLLAMA_ON_EXIT', '0')}",
            "",
            f"GPU: {gpu_text}",
            f"System: {system_text}",
        ]
        self.show_text_dialog("Runtime / Model Status", "\n".join(lines))

    def show_last_tool_result_dialog(self):
        result = getattr(self, "last_tool_result", None)

        if not result:
            self.show_text_dialog(
                "Last Tool Result", "No tool result has been recorded yet."
            )
            return

        lines = [
            f"Title: {result.get('title', '')}",
            f"Status: {result.get('status', '')}",
            f"Time: {result.get('timestamp', '')}",
            "",
            str(result.get("body") or ""),
        ]

        details = str(result.get("details") or "").strip()

        if details:
            lines.extend(["", "Details:", details])

        self.show_text_dialog("Last Tool Result", "\n".join(lines))

    def insert_prompt_into_composer(self, prompt):
        prompt_text = str(prompt or "").strip()

        if not prompt_text:
            return

        current_text = self.input_box.toPlainText()

        if current_text.strip():
            if current_text.endswith("\n\n"):
                separator = ""
            elif current_text.endswith("\n"):
                separator = "\n"
            else:
                separator = "\n\n"

            cursor = self.input_box.textCursor()
            cursor.movePosition(QTextCursor.End)
            cursor.insertText(f"{separator}{prompt_text}")
            self.input_box.setTextCursor(cursor)
        else:
            self.input_box.setPlainText(prompt_text)
            cursor = self.input_box.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.input_box.setTextCursor(cursor)

        self.input_box.setFocus()

    def mark_input_selection_as_code(self):
        if self.input_box.wrap_selection_as_code():
            self.input_box.setFocus()
            self.stats_label.setText("Composer marked as code fence.")

    def paste_clipboard_as_code(self):
        if self.input_box.paste_clipboard_text_as_code():
            self.input_box.setFocus()
            self.stats_label.setText("Clipboard pasted as code fence.")
        else:
            self.input_box.setFocus()
            self.stats_label.setText(
                "Clipboard does not contain text to paste as code."
            )

    def clear_composer(self):
        self.input_box.clear()
        self.attached_files = []
        self.render_attachments()
        self.input_box.setFocus()
        self.set_idle_ui_state("")

    def stop_generation(self):
        if self.stop_in_progress:
            return

        self.stop_in_progress = True
        self.cancel_generation = True

        self.set_action_button_mode("stopping")
        self.input_box.setEnabled(False)
        self.attach_button.setEnabled(False)
        self.new_chat_button.setEnabled(False)
        self.history_button.setEnabled(False)
        self.news_button.setEnabled(False)
        if hasattr(self, "import_documents_memory_button"):
            self.import_documents_memory_button.setEnabled(False)
        self.stats_label.setText("Stopping.")

        if self.worker and self.worker.isRunning():
            self.worker.stop()
            return

        self.finish_stopped_response(self.pending_stream_text)

    def run_astro_lookup_from_link(self, object_name):
        object_name = str(object_name or "").strip()
        if not object_name:
            return

        self.execute_astro_direct_request(f"/astro {object_name}")

    def add_message_widget(
        self,
        role,
        text="",
        files=None,
        web_articles=None,
        news_sources=None,
        message_id="",
        response_time=None,
        source_tags=None,
        content_blocks=None,
        animate=True,
        streaming=False,
    ):
        self.hide_empty_chat_state()

        widget = MessageWidget(
            role,
            text,
            files or [],
            web_articles=web_articles or [],
            news_sources=news_sources or {},
            message_id=message_id,
            response_time=response_time,
            source_tags=source_tags,
            content_blocks=content_blocks,
            streaming=streaming,
        )
        widget.delete_requested.connect(self.delete_message)
        widget.run_python_requested.connect(self.run_python_code_block_from_chat)
        widget.astro_lookup_requested.connect(self.run_astro_lookup_from_link)
        widget.document_action_requested.connect(
            self.handle_knowledge_document_chat_action
        )

        if animate:
            opacity = QGraphicsOpacityEffect(widget)
            opacity.setOpacity(0.0)
            widget.setGraphicsEffect(opacity)
            widget.appearance_animations = []
        else:
            widget.setGraphicsEffect(None)

        self.chat_layout.addWidget(widget)

        if animate:

            def start_message_appearance(
                current_widget=widget, current_opacity=opacity
            ):
                try:
                    final_position = current_widget.pos()
                    start_position = QPoint(final_position.x(), final_position.y() + 10)
                    current_widget.move(start_position)

                    fade_animation = QPropertyAnimation(
                        current_opacity, b"opacity", current_widget
                    )
                    fade_animation.setDuration(190)
                    fade_animation.setStartValue(0.0)
                    fade_animation.setEndValue(1.0)

                    slide_animation = QPropertyAnimation(
                        current_widget, b"pos", current_widget
                    )
                    slide_animation.setDuration(190)
                    slide_animation.setStartValue(start_position)
                    slide_animation.setEndValue(final_position)

                    def finish_appearance():
                        try:
                            # Keeping graphics effects on every restored message can
                            # produce blank repaint regions while QScrollArea scrolls.
                            current_widget.setGraphicsEffect(None)
                            current_widget.move(final_position)
                        except RuntimeError:
                            pass

                    fade_animation.finished.connect(finish_appearance)
                    fade_animation.start()
                    slide_animation.start()
                    current_widget.appearance_animations = [
                        fade_animation,
                        slide_animation,
                    ]
                except RuntimeError:
                    pass

            QTimer.singleShot(0, start_message_appearance)

        return widget

    def bind_latest_unbound_message_widget(self, message_id, user_role=False):
        for index in range(self.chat_layout.count() - 1, -1, -1):
            item = self.chat_layout.itemAt(index)
            widget = item.widget()

            if not isinstance(widget, MessageWidget):
                continue

            is_user_widget = widget.role in ("You", ":ME:")

            if is_user_widget != bool(user_role):
                continue

            if widget.message_id:
                continue

            widget.set_message_id(message_id)
            return widget

        return None

    def delete_message(self, message_id, widget):
        active_workers = (
            (self.worker is not None and self.worker.isRunning())
            or (
                getattr(self, "decision_worker", None) is not None
                and self.decision_worker.isRunning()
            )
            or (
                getattr(self, "web_worker", None) is not None
                and self.web_worker.isRunning()
            )
            or (
                getattr(self, "python_worker", None) is not None
                and self.python_worker.isRunning()
            )
        )

        if active_workers or self.stop_in_progress:
            self.stats_label.setText(
                "Stop the current operation before deleting messages"
            )
            return

        confirmation = QMessageBox.question(
            self,
            "Delete message",
            "Delete this message from the conversation and saved history?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )

        if confirmation != QMessageBox.StandardButton.Yes:
            return

        message_id = str(message_id or "")
        deleted_index = None
        deleted_role = ""

        for index, message in enumerate(self.messages):
            if str(message.get("id", "")) == message_id and message_id:
                deleted_index = index
                deleted_role = str(message.get("role", ""))
                del self.messages[index]
                break

        if widget is not None:
            try:
                self.chat_layout.removeWidget(widget)
                widget.deleteLater()
            except RuntimeError:
                pass

        if (
            deleted_index is not None
            and deleted_role == "assistant"
            and deleted_index >= len(self.messages)
        ):
            self._last_thoughts_text = ""
            self.global_thought_box.setMarkdown("")

        if not self.messages:
            self.show_empty_chat_state()

        self.save_current_chat()
        self.chat_container.adjustSize()
        self.chat_container.updateGeometry()
        self.stats_label.setText("Message deleted")

    def force_scroll_to_bottom(self):
        self.chat_scroll.verticalScrollBar().setValue(
            self.chat_scroll.verticalScrollBar().maximum()
        )

    def force_thought_scroll_to_bottom(self):
        scroll_bar = self.global_thought_box.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())

    def build_model_activity_fallback(self, answer_text, completed=False):
        """Return a truthful activity-panel fallback for models without thought streams.

        Some models, including many Gemma 3 builds, do not expose a separate
        Ollama/OpenAI-compatible `thinking` or `reasoning_content` stream even
        when think=True is requested.  In that case the panel should stay useful
        without pretending that visible answer text is hidden reasoning.
        """
        clean_answer = re.sub(r"\s+", " ", str(answer_text or "")).strip()

        if not clean_answer:
            return ""

        max_preview_chars = 900

        if len(clean_answer) > max_preview_chars:
            clean_answer = clean_answer[: max_preview_chars - 3].rstrip() + "..."

        model_name = "current model"
        model_box = getattr(self, "model_box", None)

        if model_box is not None:
            try:
                model_name = self.current_model_name() or model_name
            except RuntimeError:
                pass

        preview_label = (
            "Final visible answer preview"
            if completed
            else "Visible output stream preview"
        )

        return (
            f"* `{model_name}` did not emit a separate reasoning stream for this reply.\n"
            "* The panel is showing a live output preview instead of hidden thoughts.\n\n"
            f"**{preview_label}:** {clean_answer}"
        )

    def clean_model_activity_text(self, activity_text):
        """Remove prompt/setup echoes from the model-activity panel.

        Some local reasoning models echo calibration/profile instructions inside
        their thinking stream before producing useful reasoning.  That makes the
        activity panel look like it is leaking the app prompt instead of showing
        the useful model activity.  Keep the panel helpful by filtering those
        setup lines while preserving normal reasoning/output-preview content.
        """
        raw_text = re.sub(r"\r\n?", "\n", str(activity_text or ""))

        if not raw_text.strip():
            return ""

        prompt_echo_patterns = (
            r"address\s+the\s+user\s+as",
            r"start\s+with\s+[\"']?greetings",
            r"use\s+[\"']?(?:precise|architect|explorer|companion)[\"']?\s+persona",
            r"\bterminology\s*:",
            r"\bstructure\s*:",
            r"\bstyle\s*:",
            r"\btone\s*:",
            r"\bcalibration\b",
            r"\bsystem\s+prompt\b",
            r"\bdeveloper\s+message\b",
            r"\bnon-negotiable\b",
            r"private\s+chain[- ]of[- ]thought",
            r"do\s+not\s+expose",
            r"do\s+not\s+reveal",
            r"follow\s+the\s+instructions",
            r"the\s+user\s+wants\s+an\s+explanation",
        )
        prompt_echo_re = re.compile("|".join(prompt_echo_patterns), re.IGNORECASE)

        kept_lines = []
        removed_count = 0

        for line in raw_text.split("\n"):
            clean_line = line.strip()

            if prompt_echo_re.search(clean_line):
                removed_count += 1
                continue

            # Remove very instruction-looking bullets that often appear when a
            # model echoes the active profile prompt. Normal reasoning bullets
            # are kept unless they match the setup vocabulary above.
            if re.match(
                r"^[-*•]\s*(?:mode|persona|rules?|profile)\s*:",
                clean_line,
                flags=re.IGNORECASE,
            ):
                removed_count += 1
                continue

            kept_lines.append(line)

        cleaned = "\n".join(kept_lines)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

        if cleaned:
            return cleaned

        if removed_count:
            return (
                "* Model activity contained mostly prompt/profile setup echo, "
                "so it was hidden from this panel. Waiting for useful reasoning "
                "or visible-output activity..."
            )

        return ""

    def show_latest_thoughts(self, thoughts):
        clean_thoughts = self.clean_model_activity_text(thoughts)
        self.global_thought_box.setMarkdown(clean_thoughts or "")

        # setMarkdown() updates the document layout asynchronously, so scroll
        # again after Qt has recalculated the scrollbar range.
        QTimer.singleShot(0, self.force_thought_scroll_to_bottom)
        QTimer.singleShot(30, self.force_thought_scroll_to_bottom)

    def update_streaming_message(self, text):
        """Coalesce streamed snapshots before touching expensive Qt layouts."""
        self.pending_stream_text = text

        # The worker already throttles emissions, but this single-shot timer
        # also collapses bursts into one render of the newest complete snapshot.
        if not self.stream_render_timer.isActive():
            self.stream_render_timer.start(self.stream_render_interval_ms)

    def render_pending_stream_message(self):
        stream_widget = self.current_stream_widget

        if stream_widget is None:
            return

        snapshot = self.pending_stream_text

        if snapshot == self.last_rendered_stream_text:
            return

        self.last_rendered_stream_text = snapshot
        self.last_stream_render = time.perf_counter()

        try:
            stream_widget.set_stream_text(snapshot)

            thoughts, _answer = stream_widget.split_thoughts(snapshot)

            if thoughts:
                if thoughts != getattr(self, "_last_thoughts_text", ""):
                    self._last_thoughts_text = thoughts
                    self.show_latest_thoughts(thoughts)
            else:
                fallback_activity = self.build_model_activity_fallback(
                    _answer, completed=False
                )

                if fallback_activity and fallback_activity != getattr(
                    self, "_last_thoughts_text", ""
                ):
                    self._last_thoughts_text = fallback_activity
                    self.show_latest_thoughts(fallback_activity)

            # Activate only the affected layout chain.  The old code adjusted
            # the same scroll widget multiple times and queued four extra scroll
            # callbacks on every refresh, which accumulated during long news.
            stream_widget.updateGeometry()
            self.chat_layout.activate()
            self.chat_container.updateGeometry()
            QTimer.singleShot(0, self.force_scroll_to_bottom)

        except RuntimeError:
            self.current_stream_widget = None
            return

        # A newer snapshot may have arrived while this render was running.
        if self.pending_stream_text != self.last_rendered_stream_text:
            self.stream_render_timer.start(self.stream_render_interval_ms)

    def prepare_current_context_budget(self, model, api_messages, num_predict=0):
        """Cache estimated prompt/context data for the live status label."""
        self.current_prompt_context_tokens = estimate_messages_context_tokens(
            api_messages
        )
        self.current_context_limit_tokens = get_ollama_model_context_limit(
            model,
            self.current_base_url(),
        )

        try:
            self.current_generation_budget_tokens = max(0, int(num_predict))
        except (TypeError, ValueError):
            self.current_generation_budget_tokens = 0

    def context_budget_status_fragment(self, output_tokens=0):
        """Return compact estimated context usage for the bottom status bar."""
        prompt_tokens = max(
            0, int(getattr(self, "current_prompt_context_tokens", 0) or 0)
        )
        completion_tokens = max(0, int(output_tokens or 0))
        used_tokens = prompt_tokens + completion_tokens
        context_limit = getattr(self, "current_context_limit_tokens", None)

        try:
            context_limit = int(context_limit) if context_limit else None
        except (TypeError, ValueError):
            context_limit = None

        if context_limit and context_limit > 0:
            remaining_tokens = max(0, context_limit - used_tokens)
            return (
                f"ctx left ~{format_token_budget_count(remaining_tokens)}/"
                f"{format_token_budget_count(context_limit)}"
            )

        return f"ctx used ~{format_token_budget_count(used_tokens)}"

    def update_generation_timer(self):
        if not hasattr(self, "request_start_time"):
            return

        elapsed = time.perf_counter() - self.request_start_time

        python_worker = getattr(self, "python_worker", None)

        if python_worker is not None and python_worker.isRunning():
            self.stats_label.setText(f"Python • {elapsed:.2f}s • running")
            return

        chars = len(self.pending_stream_text)
        approx_tokens = estimate_token_count(self.pending_stream_text) if chars else 0
        tokens_per_second = (
            approx_tokens / elapsed if elapsed > 0 and approx_tokens else 0.0
        )
        context_fragment = self.context_budget_status_fragment(approx_tokens)

        stream_widget = self.current_stream_widget

        if stream_widget is not None:
            try:
                stream_widget.set_reply_elapsed(elapsed)
            except RuntimeError:
                pass

        generation_model = (
            str(getattr(self, "current_generation_model", "") or "").strip()
            or self.current_model_name()
        )

        if chars == 0 and self.worker is not None and self.worker.isRunning():
            if getattr(self, "current_request_requires_vision", False):
                wait_state = (
                    "waiting for first token • vision model may still be loading image"
                )
            else:
                wait_state = "waiting for first token"

            if elapsed >= 35:
                wait_state += " • use Stop, then Restart Ollama if it remains stuck"

            next_log_at = float(getattr(self, "_next_no_token_log_at", 0.0) or 0.0)

            if elapsed >= 15 and elapsed >= next_log_at:
                log_warning(
                    "FZAstroAI generation still waiting for first token",
                    (
                        f"model={generation_model}, "
                        f"vision={getattr(self, 'current_request_requires_vision', False)}, "
                        f"elapsed={elapsed:.1f}s"
                    ),
                )
                self._next_no_token_log_at = elapsed + 20.0

            self.stats_label.setText(
                f"{generation_model} • {elapsed:.2f}s • {wait_state} • "
                f"{context_fragment}"
            )
            return

        self.stats_label.setText(
            f"{generation_model} • "
            f"{elapsed:.2f}s • "
            f"out {chars} chars/~{approx_tokens} tok • "
            f"{context_fragment} • "
            f"~{tokens_per_second:.1f} tok/s"
        )

    @staticmethod
    def is_web_image_request(text):
        return _routing_is_web_image_request(text)

    @staticmethod
    def references_recent_image(text):
        return _routing_references_recent_image(text)

    @staticmethod
    def has_explicit_http_url(text):
        return _routing_has_explicit_http_url(text)

    @staticmethod
    def is_website_screenshot_request(text):
        return _routing_is_website_screenshot_request(text)

    @staticmethod
    def is_rendered_page_request(text):
        return _routing_is_rendered_page_request(text)

    @staticmethod
    def is_rendered_page_extraction_display_request(text):
        return _routing_is_rendered_page_extraction_display_request(text)

    @staticmethod
    def is_deterministic_url_tool_request(text):
        return _routing_is_deterministic_url_tool_request(text)

    def latest_assistant_image_files(self, max_messages=8):
        """Return the newest still-existing assistant image attachment."""
        for message in reversed(self.messages[-max_messages:]):
            if str(message.get("role") or "").strip().lower() != "assistant":
                continue

            image_files = []

            for file_path in message.get("files") or []:
                clean_path = str(file_path or "").strip()

                if not clean_path.lower().endswith(IMAGE_FILE_EXTENSIONS):
                    continue

                if not os.path.exists(clean_path):
                    continue

                image_files.append(clean_path)

            if image_files:
                return image_files[:1]

        return []

    @staticmethod
    def explicitly_requests_external_information(text):
        return _routing_explicitly_requests_external_information(text)

    def build_recent_conversation_context(self, max_messages=8, max_characters=6000):
        lines = []

        for message in self.messages[-max_messages:]:
            role = str(message.get("role", "unknown")).strip().upper()
            content = self.history_message_to_text(message.get("content", "")).strip()

            if not content:
                continue

            if len(content) > 1400:
                content = content[-1400:]

            lines.append(f"{role}: {content}")

        context = "\n\n".join(lines)

        if len(context) > max_characters:
            context = context[-max_characters:]

        return context

    @staticmethod
    def references_document_knowledge(text):
        return _routing_references_document_knowledge(text)

    @staticmethod
    def is_ambiguous_follow_up(text):
        return _routing_is_ambiguous_follow_up(text)

    def is_clearly_web_only_request(self, text, files=None, force_search=False):
        return _routing_is_clearly_web_only_request(
            text,
            recent_context=self.build_recent_conversation_context(),
            files=files,
            force_search=force_search,
        )

    def find_strong_document_knowledge(self, text):
        query = self.build_document_knowledge_query(text)
        results = self.knowledge_library.search(
            query, limit=5, max_characters=min(KNOWLEDGE_MAX_CONTEXT_CHARS, 24000)
        )
        return query, results, self.knowledge_library.has_strong_match(query, results)

    def explicitly_or_contextually_references_documents(self, text):
        return _routing_explicitly_or_contextually_references_documents(
            text, recent_context=self.build_recent_conversation_context()
        )

    def is_local_document_direct_request(self, text, files=None):
        return _routing_is_local_document_direct_request(
            text,
            self.knowledge_library,
            files=files,
            log_exception_func=log_exception,
        )

    def apply_styles(self):
        self.setStyleSheet(get_main_stylesheet())


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = FZAstroAI()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
