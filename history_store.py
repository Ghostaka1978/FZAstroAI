import json
import os
import re
import uuid
from datetime import datetime

from .config import HISTORY_FILE
from .logging_utils import log_exception


def _history_corrupt_path():
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = HISTORY_FILE.suffix or ".json"
    base_name = f"{HISTORY_FILE.stem}.corrupt-{timestamp}{suffix}"
    corrupt_path = HISTORY_FILE.with_name(base_name)

    counter = 1
    while corrupt_path.exists():
        corrupt_path = HISTORY_FILE.with_name(
            f"{HISTORY_FILE.stem}.corrupt-{timestamp}-{counter}{suffix}"
        )
        counter += 1

    return corrupt_path


def _preserve_corrupt_history_file():
    if not HISTORY_FILE.exists():
        return None

    try:
        corrupt_path = _history_corrupt_path()
        HISTORY_FILE.replace(corrupt_path)
        return corrupt_path
    except Exception as exc:
        log_exception("preserve_corrupt_history_file", exc)
        return None


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
    temporary_file = None

    try:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        serialized_history = json.dumps(history, indent=2, ensure_ascii=False)
        temporary_file = HISTORY_FILE.with_name(
            f"{HISTORY_FILE.name}.{uuid.uuid4().hex}.tmp"
        )

        with open(temporary_file, "w", encoding="utf-8") as f:
            f.write(serialized_history)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())

        temporary_file.replace(HISTORY_FILE)
    except Exception as exc:
        log_exception("save_chat_history", exc)
    finally:
        if temporary_file is not None and temporary_file.exists():
            try:
                temporary_file.unlink()
            except Exception as exc:
                log_exception("cleanup_chat_history_temporary_file", exc)


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
