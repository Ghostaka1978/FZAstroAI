from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .logging_utils import log_exception


def atomic_write_text(
    path: Path | str,
    text: str,
    *,
    encoding: str = "utf-8",
    final_newline: bool = True,
) -> None:
    """Write text through a unique temp file, fsync it, then replace the target."""

    target = Path(path)
    temporary_file = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with temporary_file.open("w", encoding=encoding) as handle:
            handle.write(text)
            if final_newline:
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        temporary_file.replace(target)
    finally:
        if temporary_file.exists():
            try:
                temporary_file.unlink()
            except Exception as exc:
                log_exception("atomic_write_text cleanup", exc)


def atomic_write_json(
    path: Path | str,
    payload: Any,
    *,
    ensure_ascii: bool = False,
    indent: int | None = 2,
    sort_keys: bool = False,
    final_newline: bool = True,
) -> None:
    serialized = json.dumps(
        payload,
        ensure_ascii=ensure_ascii,
        indent=indent,
        sort_keys=sort_keys,
    )
    atomic_write_text(path, serialized, final_newline=final_newline)


def corrupt_sibling_path(path: Path | str) -> Path:
    target = Path(path)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = target.suffix or ".json"
    corrupt_path = target.with_name(f"{target.stem}.corrupt-{timestamp}{suffix}")

    counter = 1
    while corrupt_path.exists():
        corrupt_path = target.with_name(
            f"{target.stem}.corrupt-{timestamp}-{counter}{suffix}"
        )
        counter += 1

    return corrupt_path


def preserve_corrupt_file(path: Path | str, context: str) -> Path | None:
    target = Path(path)

    if not target.exists():
        return None

    try:
        corrupt_path = corrupt_sibling_path(target)
        target.replace(corrupt_path)
        return corrupt_path
    except Exception as exc:
        log_exception(context, exc)
        return None
