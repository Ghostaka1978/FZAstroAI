"""Best-effort cleanup for FZAstro AI temporary runtime artifacts."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Iterable

from .logging_utils import log_debug, log_warning

FZASTRO_TEMP_DIR_NAMES: tuple[str, ...] = (
    "fzastro_clipboard",
    "fzastro_web_screenshots",
    "fzastro_rendered_pages",
)


def iter_fzastro_temp_dirs(temp_root: Path | None = None) -> Iterable[Path]:
    """Yield only the known FZAstro-owned temp cache directories."""
    root = Path(temp_root) if temp_root is not None else Path(tempfile.gettempdir())

    for dir_name in FZASTRO_TEMP_DIR_NAMES:
        yield root / dir_name


def cleanup_fzastro_temp_dirs(temp_root: Path | None = None) -> list[Path]:
    """Remove known FZAstro temp directories and return paths that could not be removed.

    The cleanup is intentionally conservative: it only removes directories with
    fixed FZAstro-owned names under the OS temp directory. Failures are logged and
    returned, but never raised, so Windows file-locks cannot block application exit.
    """
    failed: list[Path] = []

    for temp_dir in iter_fzastro_temp_dirs(temp_root):
        try:
            if not temp_dir.exists():
                continue

            if not temp_dir.is_dir():
                log_warning(f"FZAstro temp cleanup skipped non-directory: {temp_dir}")
                failed.append(temp_dir)
                continue

            shutil.rmtree(temp_dir, ignore_errors=False)
            log_debug(f"FZAstro temp cleanup removed: {temp_dir}")
        except Exception as exc:
            log_warning(f"FZAstro temp cleanup could not remove {temp_dir}: {exc}")
            failed.append(temp_dir)

    return failed


__all__ = [
    "FZASTRO_TEMP_DIR_NAMES",
    "cleanup_fzastro_temp_dirs",
    "iter_fzastro_temp_dirs",
]
