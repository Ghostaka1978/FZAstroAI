from pathlib import Path

import pytest

from fzastro_ai.dev_agent.openclaude_attachments import (
    OpenClaudeAttachmentError,
    OpenClaudeImageAttachment,
    build_image_handoff_prompt,
    copy_image_attachment,
    is_supported_image_path,
    make_clipboard_image_attachment_path,
    make_terminal_screenshot_attachment_path,
    openclaude_attachment_dir,
)


def make_workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    return root


def test_openclaude_attachment_dir_is_workspace_local(tmp_path):
    root = make_workspace(tmp_path)

    directory = openclaude_attachment_dir(root)

    assert directory == root.resolve() / ".fzastro" / "openclaude_attachments"
    assert directory.exists()


def test_copy_image_attachment_copies_supported_image_inside_workspace(tmp_path):
    root = make_workspace(tmp_path)
    source = tmp_path / "issue screenshot.png"
    source.write_bytes(b"fakepng")

    attachment = copy_image_attachment(source, root)

    assert attachment.path.exists()
    assert attachment.path.read_bytes() == b"fakepng"
    assert attachment.project_root == root.resolve()
    assert attachment.relative_path.startswith(".fzastro/openclaude_attachments/image_")
    assert attachment.relative_path.endswith("issue_screenshot.png")


def test_copy_image_attachment_rejects_non_image(tmp_path):
    root = make_workspace(tmp_path)
    source = tmp_path / "notes.txt"
    source.write_text("not an image", encoding="utf-8")

    with pytest.raises(OpenClaudeAttachmentError, match="Unsupported image type"):
        copy_image_attachment(source, root)


def test_clipboard_and_terminal_screenshot_targets_are_pngs(tmp_path):
    root = make_workspace(tmp_path)

    clipboard_target = make_clipboard_image_attachment_path(root)
    terminal_target = make_terminal_screenshot_attachment_path(root)

    assert (
        clipboard_target.parent
        == root.resolve() / ".fzastro" / "openclaude_attachments"
    )
    assert terminal_target.parent == clipboard_target.parent
    assert clipboard_target.name.startswith("clipboard_")
    assert terminal_target.name.startswith("terminal_")
    assert clipboard_target.suffix == ".png"
    assert terminal_target.suffix == ".png"


def test_image_handoff_prompt_is_honest_about_non_vision_models(tmp_path):
    root = make_workspace(tmp_path)
    image = root / ".fzastro" / "openclaude_attachments" / "shot.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"fake")
    attachment = OpenClaudeImageAttachment(path=image, project_root=root.resolve())

    prompt = build_image_handoff_prompt(attachment, user_note="Fix what is shown.")

    assert "Image file: .fzastro/openclaude_attachments/shot.png" in prompt
    assert "Absolute path:" in prompt
    assert "cannot decode image pixels directly" in prompt
    assert "Fix what is shown." in prompt


def test_supported_image_extensions():
    assert is_supported_image_path("a.PNG")
    assert is_supported_image_path("a.jpeg")
    assert is_supported_image_path("a.webp")
    assert not is_supported_image_path("a.svg")
