import json
import re
import uuid
from datetime import datetime

from .config import HISTORY_FILE
from .json_store import atomic_write_json, corrupt_sibling_path, preserve_corrupt_file
from .logging_utils import log_exception


def _history_corrupt_path():
    return corrupt_sibling_path(HISTORY_FILE)


def _preserve_corrupt_history_file():
    return preserve_corrupt_file(HISTORY_FILE, "preserve_corrupt_history_file")


def load_chat_history():
    if not HISTORY_FILE.exists():
        return []

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        log_exception("load_chat_history", exc)
        _preserve_corrupt_history_file()
        return []


def save_chat_history(history):
    try:
        atomic_write_json(HISTORY_FILE, history, indent=2, ensure_ascii=False)
    except Exception as exc:
        log_exception("save_chat_history", exc)


def create_chat_record(messages):
    preview = "New Chat"

    for msg in messages:
        if msg.get("role") != "user":
            continue

        content = msg.get("content", "")

        if isinstance(content, list):
            if content and isinstance(content[0], dict):
                preview = content[0].get("text", "New Chat")
        else:
            preview = str(content)

        for pattern in (
            r"\n\n\[INTERNET CONTEXT\].*",
            r"\n\n\[STOCK QUOTE\].*",
            r"\n\nAttached file:.*",
        ):
            preview = re.sub(pattern, "", preview, flags=re.DOTALL).strip()

        preview = preview[:80]
        break

    return {
        "id": str(uuid.uuid4()),
        "title": preview,
        "created": datetime.now().isoformat(),
        "messages": messages,
    }
