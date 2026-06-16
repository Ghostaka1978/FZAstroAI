"""File extraction and attachment-content helpers for FZAstro AI.

Extracted from app.py without behavior changes. These helpers prepare attached
files for model requests and keep image attachments in OpenAI-compatible content
arrays.
"""

import base64
import os
import zipfile
import xml.etree.ElementTree as ET
from io import BytesIO

from .config import CHAT_ATTACHMENT_MAX_BYTES, CHAT_IMAGE_ATTACHMENT_MAX_BYTES
from .logging_utils import log_debug, log_exception, log_warning


IMAGE_FILE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


class AttachmentReadError(ValueError):
    """Raised when a chat attachment cannot be safely read into memory."""


class AttachmentTooLargeError(AttachmentReadError):
    """Raised when a chat attachment exceeds the configured size limit."""


def _format_size(byte_count):
    try:
        byte_count = int(byte_count)
    except (TypeError, ValueError):
        byte_count = 0

    units = ("bytes", "KB", "MB", "GB")
    size = float(max(0, byte_count))

    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "bytes":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024

    return f"{byte_count} bytes"


def _validate_attachment_file(file_path, max_bytes, attachment_kind):
    if not os.path.isfile(file_path):
        raise AttachmentReadError("The selected path is not a readable file.")

    try:
        file_size = os.path.getsize(file_path)
    except OSError as exc:
        raise AttachmentReadError(f"Could not check file size: {exc}") from exc

    if file_size > int(max_bytes):
        raise AttachmentTooLargeError(
            f"This {attachment_kind} is too large to attach directly "
            f"({_format_size(file_size)}; limit {_format_size(max_bytes)}). "
            "Import it into the knowledge library instead."
        )

    return file_size


def _read_attachment_bytes(file_path, max_bytes, attachment_kind):
    _validate_attachment_file(file_path, max_bytes, attachment_kind)

    with open(file_path, "rb") as file:
        return file.read()


def extract_pdf_text(file_bytes):
    from PyPDF2 import PdfReader

    reader = PdfReader(BytesIO(file_bytes))
    pages = []

    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text)

    return "\n".join(pages)


def extract_docx_text(file_bytes):
    text_parts = []

    with zipfile.ZipFile(BytesIO(file_bytes)) as docx:
        with docx.open("word/document.xml") as document:
            tree = ET.parse(document)
            root = tree.getroot()

            for element in root.iter():
                if element.tag.endswith("}t") and element.text:
                    text_parts.append(element.text)

    return "\n".join(text_parts)


def extract_xlsx_text(file_bytes):
    import openpyxl

    workbook = openpyxl.load_workbook(BytesIO(file_bytes), data_only=True)
    rows = []

    for sheet in workbook.worksheets:
        rows.append(f"Sheet: {sheet.title}")

        for row in sheet.iter_rows(values_only=True):
            values = [str(value) for value in row if value is not None]
            if values:
                rows.append(" | ".join(values))

    return "\n".join(rows)


def extract_pptx_text(file_bytes):
    text_parts = []

    with zipfile.ZipFile(BytesIO(file_bytes)) as pptx:
        slide_files = sorted(
            name
            for name in pptx.namelist()
            if name.startswith("ppt/slides/slide") and name.endswith(".xml")
        )

        for slide_file in slide_files:
            with pptx.open(slide_file) as slide:
                tree = ET.parse(slide)
                root = tree.getroot()

                for element in root.iter():
                    if element.tag.endswith("}t") and element.text:
                        text_parts.append(element.text)

    return "\n".join(text_parts)


def file_to_data_url(file_path):
    file_bytes = _read_attachment_bytes(
        file_path, CHAT_IMAGE_ATTACHMENT_MAX_BYTES, "image file"
    )

    ext = os.path.splitext(file_path.lower())[1]

    mime_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }

    mime = mime_map.get(ext, "image/png")
    encoded = base64.b64encode(file_bytes).decode("utf-8")

    return f"data:{mime};base64,{encoded}"


def extract_file_text(file_path):
    file_name = os.path.basename(file_path)
    file_lower = file_name.lower()
    file_bytes = _read_attachment_bytes(file_path, CHAT_ATTACHMENT_MAX_BYTES, "file")

    if file_lower.endswith(".pdf"):
        return extract_pdf_text(file_bytes)

    if file_lower.endswith(".docx"):
        return extract_docx_text(file_bytes)

    if file_lower.endswith(".xlsx"):
        return extract_xlsx_text(file_bytes)

    if file_lower.endswith(".pptx"):
        return extract_pptx_text(file_bytes)

    return file_bytes.decode("utf-8", errors="replace")


def has_image_attachments(files):
    return any(
        str(file_path).lower().endswith(IMAGE_FILE_EXTENSIONS) for file_path in files
    )


def prepare_content(text, files):
    message_text = text.strip() or "Analyze the attached file."
    file_text_blocks = []
    image_parts = []

    for file_path in files:
        file_name = os.path.basename(file_path)
        file_lower = file_name.lower()

        if file_lower.endswith(IMAGE_FILE_EXTENSIONS):
            try:
                image_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": file_to_data_url(file_path)},
                    }
                )
            except AttachmentTooLargeError as error:
                log_warning("prepare_content image attachment too large", error)
                file_text_blocks.append(
                    f"Attached file: {file_name}\n\nCould not attach this image: {error}"
                )
            except Exception as error:
                log_exception("prepare_content image attachment", error)
                file_text_blocks.append(
                    f"Attached file: {file_name}\n\nCould not attach this image: {error}"
                )
        else:
            try:
                extracted_text = extract_file_text(file_path)

                log_debug("EXTRACTED FILE SIZE", len(extracted_text))
                log_debug("SENT TO MODEL", len(extracted_text))

                file_text_blocks.append(
                    f"Attached file: {file_name}\n\n{extracted_text}"
                )
            except AttachmentTooLargeError as error:
                log_warning("prepare_content file attachment too large", error)
                file_text_blocks.append(
                    f"Attached file: {file_name}\n\nCould not read this file: {error}"
                )
            except Exception as error:
                log_exception("prepare_content file attachment", error)
                file_text_blocks.append(
                    f"Attached file: {file_name}\n\nCould not read this file: {error}"
                )

    if file_text_blocks:
        message_text += "\n\n" + "\n\n---\n\n".join(file_text_blocks)

    # Text documents must be sent as a plain string. Sending a one-item content
    # array makes Ollama classify the request as multimodal, even with no image.
    if not image_parts:
        return message_text

    return [{"type": "text", "text": message_text}, *image_parts]
