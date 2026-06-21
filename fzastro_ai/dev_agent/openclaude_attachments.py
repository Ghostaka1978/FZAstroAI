"""Screenshot and image handoff helpers for the embedded OpenClaude terminal.

OpenClaude runs as a normal terminal process inside the selected workspace.  The
terminal cannot reliably receive binary image data directly, so FZAstro stores
user-approved screenshots/images inside the selected workspace and sends a small
text handoff prompt that points OpenClaude at the file.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import time

from .openclaude_bridge import validate_openclaude_project_root

SUPPORTED_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
ATTACHMENT_DIR_PARTS = (".fzastro", "openclaude_attachments")


class OpenClaudeAttachmentError(RuntimeError):
    """Raised when an OpenClaude image handoff cannot be prepared safely."""


@dataclass(frozen=True)
class OpenClaudeImageAttachment:
    """Image file prepared for OpenClaude inside the selected workspace."""

    path: Path
    project_root: Path
    source_label: str = "image"

    @property
    def relative_path(self) -> str:
        try:
            return (
                self.path.resolve().relative_to(self.project_root.resolve()).as_posix()
            )
        except Exception:
            return self.path.as_posix()


def is_supported_image_path(path: Path | str) -> bool:
    """Return True when *path* has an image extension FZAstro will hand off."""

    return Path(path).suffix.casefold() in SUPPORTED_IMAGE_EXTENSIONS


def openclaude_attachment_dir(project_root: Path | str) -> Path:
    """Return the workspace-local attachment directory, creating it if needed."""

    root = validate_openclaude_project_root(project_root)
    directory = root
    for part in ATTACHMENT_DIR_PARTS:
        directory = directory / part
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _clean_name(value: str, *, fallback: str = "image") -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
    clean = clean.strip("._-")
    return clean[:80] or fallback


def attachment_target_path(
    project_root: Path | str,
    *,
    source_name: str = "image.png",
    prefix: str = "image",
    suffix: str | None = None,
) -> Path:
    """Build a unique workspace-local image attachment target path."""

    source = Path(str(source_name or "image.png"))
    ext = str(suffix or source.suffix or ".png").casefold()
    if ext not in SUPPORTED_IMAGE_EXTENSIONS:
        raise OpenClaudeAttachmentError(
            "Unsupported image type. Supported: "
            + ", ".join(SUPPORTED_IMAGE_EXTENSIONS)
        )
    stamp = time.strftime("%Y%m%d_%H%M%S")
    safe_prefix = _clean_name(prefix, fallback="image")
    safe_stem = _clean_name(source.stem, fallback="image")
    return (
        openclaude_attachment_dir(project_root)
        / f"{safe_prefix}_{stamp}_{safe_stem}{ext}"
    )


def _ensure_inside_workspace(path: Path, project_root: Path) -> None:
    try:
        path.resolve().relative_to(project_root.resolve())
    except Exception as exc:
        raise OpenClaudeAttachmentError(
            f"Attachment target escaped selected workspace: {path}"
        ) from exc


def copy_image_attachment(
    source_path: Path | str,
    project_root: Path | str,
    *,
    prefix: str = "image",
) -> OpenClaudeImageAttachment:
    """Copy an existing image into the selected workspace attachment folder."""

    source = Path(source_path).expanduser()
    if not source.exists() or not source.is_file():
        raise OpenClaudeAttachmentError(f"Image file does not exist: {source}")
    if not is_supported_image_path(source):
        raise OpenClaudeAttachmentError(
            "Unsupported image type. Supported: "
            + ", ".join(SUPPORTED_IMAGE_EXTENSIONS)
        )

    root = validate_openclaude_project_root(project_root)
    target = attachment_target_path(
        root, source_name=source.name, prefix=prefix, suffix=source.suffix
    )
    _ensure_inside_workspace(target, root)
    shutil.copy2(source, target)
    return OpenClaudeImageAttachment(
        path=target, project_root=root, source_label=prefix
    )


def make_clipboard_image_attachment_path(project_root: Path | str) -> Path:
    """Return a PNG target path for an image read from the system clipboard."""

    root = validate_openclaude_project_root(project_root)
    target = attachment_target_path(
        root,
        source_name="clipboard.png",
        prefix="clipboard",
        suffix=".png",
    )
    _ensure_inside_workspace(target, root)
    return target


def make_terminal_screenshot_attachment_path(project_root: Path | str) -> Path:
    """Return a PNG target path for a terminal screenshot handoff."""

    root = validate_openclaude_project_root(project_root)
    target = attachment_target_path(
        root,
        source_name="terminal.png",
        prefix="terminal",
        suffix=".png",
    )
    _ensure_inside_workspace(target, root)
    return target


def build_image_handoff_prompt(
    attachment: OpenClaudeImageAttachment,
    *,
    user_note: str = "",
) -> str:
    """Build the terminal text sent to OpenClaude for an image attachment."""

    note = str(user_note or "").strip()
    lines = [
        "FZAstro image attachment handoff.",
        "",
        f"Image file: {attachment.relative_path}",
        f"Absolute path: {attachment.path}",
        "",
        "Use this screenshot/image as visual evidence for the current task. Stay inside the selected workspace boundary.",
        "If your current OpenClaude/model/tooling cannot decode image pixels directly, say that clearly instead of guessing, then ask me for a text description or OCR/vision follow-up.",
    ]
    if note:
        lines.extend(["", "User note/task for this image:", note])
    return "\n".join(lines).rstrip() + "\n"
