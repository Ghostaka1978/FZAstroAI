import os
from pathlib import Path

BASE_URL = "http://localhost:11434/v1"
API_KEY = "ollama"


def env_float(name: str, default: float, *, minimum: float | None = None) -> float:
    """Return a float environment value with a safe fallback."""

    raw_value = os.environ.get(name)

    if raw_value is None:
        value = float(default)
    else:
        try:
            value = float(str(raw_value).strip())
        except (TypeError, ValueError):
            value = float(default)

    if minimum is not None:
        value = max(float(minimum), value)

    return value


APP_NAME = "FZAstro AI"
APP_VERSION = "2.3.1"
APP_MILESTONE = "Imaging Production"
APP_VERSION_LABEL = f"{APP_NAME} v{APP_VERSION} ({APP_MILESTONE})"
DEFAULT_MODEL_NAME = (
    os.environ.get("FZASTRO_DEFAULT_MODEL", "qwen3:32b").strip() or "qwen3:32b"
)
RUNTIME_MODEL_LIST_TIMEOUT_SECONDS = env_float(
    "FZASTRO_MODEL_LIST_TIMEOUT_SECONDS", 10.0, minimum=1.0
)
RUNTIME_CHAT_TIMEOUT_SECONDS = env_float(
    "FZASTRO_CHAT_TIMEOUT_SECONDS", 300.0, minimum=5.0
)
RUNTIME_VISION_CHAT_TIMEOUT_SECONDS = env_float(
    "FZASTRO_VISION_CHAT_TIMEOUT_SECONDS", 65.0, minimum=10.0
)
RUNTIME_DECISION_TIMEOUT_SECONDS = env_float(
    "FZASTRO_DECISION_TIMEOUT_SECONDS", 45.0, minimum=5.0
)
RUNTIME_MEMORY_TIMEOUT_SECONDS = env_float(
    "FZASTRO_MEMORY_TIMEOUT_SECONDS", 300.0, minimum=5.0
)
_APP_DIR_OVERRIDE = os.environ.get("FZASTRO_APP_DIR")
APP_DIR = (
    Path(_APP_DIR_OVERRIDE).expanduser()
    if _APP_DIR_OVERRIDE
    else Path.home() / "AppData" / "Roaming" / "FZAstroAI"
)
APP_DIR.mkdir(parents=True, exist_ok=True)

LOG_DIR = APP_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "fzastroai.log"

HISTORY_FILE = APP_DIR / "history.json"
MEMORY_FILE = APP_DIR / "memory.json"
LEGACY_MEMORY_FILE = APP_DIR / "memory.txt"
CALIBRATION_PROFILES_FILE = APP_DIR / "calibration_profiles.json"
CALIBRATION_PROFILE_SCHEMA_VERSION = 1

MAX_MEMORY_CHARS = 16000
MAX_MEMORY_ENTRIES = 5000
MEMORY_MAX_RESULTS = 60
MEMORY_EXTRACTION_CHUNK_CHARS = 36000
MEMORY_EXTRACTION_CHUNK_OVERLAP = 400
MEMORY_CODE_CHUNK_CHARS = 12000
MEMORY_SCHEMA_VERSION = 1
MEMORY_CATEGORIES = (
    "preference",
    "identity",
    "project",
    "configuration",
    "procedure",
    "decision",
    "reference",
    "snapshot",
    "other",
)

SOURCE_CODE_EXTENSIONS = {
    ".py",
    ".pyw",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".java",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".cc",
    ".cs",
    ".go",
    ".rs",
    ".rb",
    ".php",
    ".swift",
    ".kt",
    ".kts",
    ".scala",
    ".sh",
    ".bash",
    ".zsh",
    ".ps1",
    ".bat",
    ".cmd",
    ".sql",
    ".html",
    ".htm",
    ".css",
    ".scss",
    ".sass",
    ".less",
    ".xml",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
}

SOURCE_CODE_LANGUAGE_BY_EXTENSION = {
    ".py": "python",
    ".pyw": "python",
    ".js": "javascript",
    ".jsx": "jsx",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cc": "cpp",
    ".cs": "csharp",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".scala": "scala",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "zsh",
    ".ps1": "powershell",
    ".bat": "batch",
    ".cmd": "batch",
    ".sql": "sql",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".sass": "sass",
    ".less": "less",
    ".xml": "xml",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".conf": "ini",
}

KNOWLEDGE_DB_FILE = APP_DIR / "document_knowledge.sqlite3"
KNOWLEDGE_ASSET_DIR = APP_DIR / "document_knowledge_assets"
KNOWLEDGE_ASSET_DIR.mkdir(parents=True, exist_ok=True)
KNOWLEDGE_CHUNK_CHARS = 5000
KNOWLEDGE_CHUNK_OVERLAP = 500
KNOWLEDGE_MAX_CONTEXT_CHARS = 64000
KNOWLEDGE_MAX_RESULTS = 18
KNOWLEDGE_EXHAUSTIVE_MAX_CONTEXT_CHARS = 180000
KNOWLEDGE_EXHAUSTIVE_MAX_RESULTS = 80
KNOWLEDGE_PDF_RENDER_DPI = 160
KNOWLEDGE_PDF_OCR_DPI = 220
KNOWLEDGE_MAX_OCR_CHARS_PER_PAGE = 12000
KNOWLEDGE_MIN_TEXT_CHARS_FOR_PDF_PAGE = 80
KNOWLEDGE_OCR_MIN_CONFIDENCE = 55.0
KNOWLEDGE_OCR_MIN_UNIQUE_TOKEN_RATIO = 0.45
KNOWLEDGE_OCR_MAX_TOKEN_SHARE = 0.22
KNOWLEDGE_VECTOR_DRAWING_THRESHOLD = 12
KNOWLEDGE_MAX_VISUALS_PER_REQUEST = 4

WEB_IMAGE_CACHE_DIR = APP_DIR / "web_images"
WEB_IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
WEB_IMAGE_DOWNLOAD_MAX_BYTES = 20 * 1024 * 1024
RENDERED_PAGE_IMAGE_PREVIEW_MAX_BYTES = 12 * 1024 * 1024
WEB_SEARCH_HTML_MAX_BYTES = 3 * 1024 * 1024
WEB_SEARCH_JSON_MAX_BYTES = 2 * 1024 * 1024
MARKET_JSON_MAX_BYTES = 2 * 1024 * 1024
DAILY_NEWS_RSS_MAX_BYTES = 2 * 1024 * 1024

CHAT_ATTACHMENT_MAX_BYTES = 25 * 1024 * 1024
CHAT_IMAGE_ATTACHMENT_MAX_BYTES = 8 * 1024 * 1024

DAILY_NEWS_CACHE_FILE = APP_DIR / "daily_news_cache.json"
DAILY_NEWS_CACHE_MAX_AGE_SECONDS = 10 * 60
DAILY_NEWS_RSS_TIMEOUT_SECONDS = 4.5
DAILY_NEWS_MAX_ITEMS_PER_SECTION = 20
DAILY_NEWS_BRIEF_ITEMS_PER_SECTION = 8

PYTHON_EXECUTION_TIMEOUT_SECONDS = 15
PYTHON_EXECUTION_MAX_OUTPUT_CHARS = 20000


def env_flag_enabled(name: str, default: bool = False) -> bool:
    """Return a boolean environment flag using common truthy/falsy values."""

    value = os.environ.get(name)
    if value is None:
        return bool(default)

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return bool(default)


def startup_gpu_monitor_enabled() -> bool:
    """Return whether the main window should start the GPU telemetry worker."""

    return not env_flag_enabled("FZASTRO_DISABLE_STARTUP_GPU_MONITOR", default=False)


def startup_model_refresh_enabled() -> bool:
    """Return whether the main window should refresh models on startup."""

    return not env_flag_enabled("FZASTRO_DISABLE_STARTUP_MODEL_REFRESH", default=False)


PYTHON_APPLICATION_CAPABILITY_PROMPT = r"""
APPLICATION PYTHON EXECUTION CONTEXT

This desktop app has a local Python subprocess runner. It can run Python code only when the user explicitly triggers the Run button on a Python code block, uses /run-python, /run-py, /py, or makes a natural request that clearly asks to generate Python code and test/run/execute/check it.

Do not say that no code-execution tool is available inside this app. Also do not claim that you personally executed code unless the app has returned a Python execution result message. When asked to create Python code and test it, provide one self-contained runnable Python code block fenced as ```python. The app will execute that generated code after your response and then show stdout/stderr as a separate Python execution result.

This runner is local subprocess execution with timeout, not a secure sandbox.
"""

RESPONSE_STYLE_PROMPT = r"""
APPLICATION RESPONSE STYLE

- Answer the user directly first; avoid filler and generic capability disclaimers.
- For data-heavy replies, use compact Markdown headings, bullets, or tables so facts are scannable.
- Preserve important numbers, dates, units, sources, and caveats; do not hide useful details.
- Use Markdown links like [source](https://example.com) instead of raw HTML, href attributes, SourceURL fields, or long pasted URLs.
- Do not include debug/API URLs unless the user asks for the raw endpoint; cite them as a labeled source link when relevant.
"""

PYTHON_AUTO_TEST_PROMPT = r"""
APPLICATION PYTHON AUTO-TEST MODE

The current user request asks for Python code and asks for it to be tested/run/checked. Reply with exactly one self-contained runnable Python code block fenced as ```python. Keep any explanation short. Do not say you cannot execute it. Do not claim verified output in this reply; the app will run the code after this reply and show the real execution result separately.
"""
