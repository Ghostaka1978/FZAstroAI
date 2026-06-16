import base64

from fzastro_ai import file_tools


def test_file_tools_import_without_optional_extractors():
    assert file_tools.IMAGE_FILE_EXTENSIONS == (".jpg", ".jpeg", ".png", ".webp")


def test_file_to_data_url_encodes_small_image(tmp_path, monkeypatch):
    image_file = tmp_path / "tiny.png"
    image_file.write_bytes(b"image-bytes")
    monkeypatch.setattr(file_tools, "CHAT_IMAGE_ATTACHMENT_MAX_BYTES", 1024)

    data_url = file_tools.file_to_data_url(str(image_file))

    assert data_url == "data:image/png;base64," + base64.b64encode(
        b"image-bytes"
    ).decode("utf-8")


def test_prepare_content_reports_oversized_image_without_crashing(
    tmp_path, monkeypatch
):
    image_file = tmp_path / "large.png"
    image_file.write_bytes(b"12345")
    monkeypatch.setattr(file_tools, "CHAT_IMAGE_ATTACHMENT_MAX_BYTES", 4)

    content = file_tools.prepare_content("Look at this", [str(image_file)])

    assert isinstance(content, str)
    assert "Could not attach this image" in content
    assert "too large to attach directly" in content
    assert "knowledge library" in content


def test_prepare_content_reports_oversized_text_file_without_replacing_prompt(
    tmp_path, monkeypatch
):
    text_file = tmp_path / "large.txt"
    text_file.write_text("12345", encoding="utf-8")
    monkeypatch.setattr(file_tools, "CHAT_ATTACHMENT_MAX_BYTES", 4)

    content = file_tools.prepare_content("Read this", [str(text_file)])

    assert isinstance(content, str)
    assert content.startswith("Read this")
    assert "Could not read this file" in content
    assert "too large to attach directly" in content



def test_prepare_content_wraps_python_attachment_in_explicit_context(tmp_path):
    source_file = tmp_path / "astro_lookup.py"
    source_file.write_text("def lookup_target(name):\n    return name.upper()\n", encoding="utf-8")

    content = file_tools.prepare_content("Inspect the attached file.", [str(source_file)])

    assert isinstance(content, str)
    assert content.startswith("Inspect the attached file.")
    assert "Attached file: astro_lookup.py" in content
    assert "Attachment metadata:" in content
    assert "Extracted lines: 2" in content
    assert "BEGIN ATTACHED FILE: astro_lookup.py" in content
    assert "~~~python" in content
    assert "def lookup_target(name):" in content
    assert "END ATTACHED FILE: astro_lookup.py" in content


def test_attachment_language_for_filename_defaults_to_text():
    assert file_tools.attachment_language_for_filename("module.py") == "python"
    assert file_tools.attachment_language_for_filename("notes.unknown") == "text"
