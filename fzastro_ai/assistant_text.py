"""Assistant-response text normalization helpers."""

from __future__ import annotations

import html
import re
from urllib.parse import urlparse


FENCED_CODE_PATTERN = r"(```.*?```|~~~.*?~~~)"


def _strip_html_tags(value: str) -> str:
    return re.sub(r"(?is)<[^>]+>", "", str(value or ""))


def _normalize_html_segment(segment: str) -> str:
    text = str(segment or "")

    if "&lt;" in text and "&gt;" in text:
        text = html.unescape(text)

    def replace_anchor(match: re.Match[str]) -> str:
        attrs = match.group("attrs") or ""
        body = match.group("body") or ""
        href_match = re.search(
            r"""href\s*=\s*(?:"([^"]+)"|'([^']+)'|([^\s>]+))""",
            attrs,
            flags=re.IGNORECASE,
        )

        if not href_match:
            return html.unescape(_strip_html_tags(body)).strip()

        url = html.unescape(
            next(group for group in href_match.groups() if group is not None)
        ).strip()
        label = html.unescape(_strip_html_tags(body)).strip() or url
        label = label.replace("[", "\\[").replace("]", "\\]")
        url = url.replace(")", "%29")
        return f"[{label}]({url})"

    text = re.sub(
        r"(?is)<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a>",
        replace_anchor,
        text,
    )
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</p\s*>", "\n\n", text)
    text = re.sub(r"(?is)<p\b[^>]*>", "", text)
    text = re.sub(r"(?is)<li\b[^>]*>", "- ", text)
    text = re.sub(r"(?is)</li\s*>", "\n", text)
    text = re.sub(r"(?is)</?(?:ul|ol|div|span|section|article)\b[^>]*>", "", text)
    text = re.sub(
        r"(?is)<h([1-6])\b[^>]*>",
        lambda match: "\n" + "#" * int(match.group(1)) + " ",
        text,
    )
    text = re.sub(r"(?is)</h[1-6]\s*>", "\n\n", text)
    text = re.sub(r"(?is)</?(?:strong|b)\b[^>]*>", "**", text)
    text = re.sub(r"(?is)</?(?:em|i)\b[^>]*>", "*", text)

    # Any remaining simple HTML tag outside code is more likely accidental model
    # markup than useful content. Keep the text, drop the tag.
    text = re.sub(r"(?is)</?[A-Za-z][A-Za-z0-9:-]*\b[^>]*>", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _escape_markdown_label(label: str) -> str:
    return str(label or "").replace("[", "\\[").replace("]", "\\]").strip()


def _split_url_trailing_punctuation(url: str) -> tuple[str, str]:
    clean_url = str(url or "").strip()
    trailing = ""

    while clean_url and clean_url[-1] in ".,;:!?)]}":
        trailing = clean_url[-1] + trailing
        clean_url = clean_url[:-1]

    return clean_url, trailing


def _link_label_for_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    host = parsed.netloc or parsed.path.split("/", 1)[0] or "link"
    host = host.removeprefix("www.")

    if "open-meteo.com" in host:
        return "Open-Meteo forecast"

    path = parsed.path.strip("/")

    if path:
        compact_path = path
        if len(compact_path) > 34:
            compact_path = compact_path[:31].rstrip("/") + "..."
        return f"{host}/{compact_path}"

    return host


def _normalize_source_url_lines(segment: str) -> str:
    text = str(segment or "")

    def replace_line(match: re.Match[str]) -> str:
        indent = match.group("indent") or ""
        label = (match.group("label") or "").strip()
        descriptor = re.sub(r"\s+", " ", match.group("descriptor") or "").strip()
        raw_url = match.group("url") or ""

        if "](" in descriptor or descriptor.endswith("("):
            return match.group(0)

        url, trailing = _split_url_trailing_punctuation(raw_url)

        if not url:
            return match.group(0)

        safe_url = url.replace(")", "%29")
        label_key = label.casefold()

        if label_key == "source":
            link_label = descriptor.strip(":- ") or _link_label_for_url(url)
            output_label = "Source"
        elif "open-meteo" in label_key:
            link_label = "Open-Meteo forecast"
            output_label = "Source"
        elif label_key in {"sourceurl", "source url"}:
            link_label = _link_label_for_url(url)
            output_label = "Source"
        elif label_key in {"imageurl", "image url"}:
            link_label = descriptor.strip(":- ") or "Open image"
            output_label = "Image"
        else:
            link_label = descriptor.strip(":- ") or _link_label_for_url(url)
            output_label = "Link"

        return (
            f"{indent}{output_label}: "
            f"[{_escape_markdown_label(link_label)}]({safe_url}){trailing}"
        )

    return re.sub(
        r"(?im)^(?P<indent>[ \t]*)"
        r"(?P<label>SourceURL|Source URL|ImageURL|Image URL|Open-Meteo URL|URL|Link|Source)"
        r"\s*:\s*"
        r"(?P<descriptor>.*?)"
        r"(?P<url>https?://\S+)"
        r"[ \t]*$",
        replace_line,
        text,
    )


def _linkify_bare_urls(segment: str) -> str:
    text = str(segment or "")
    url_pattern = re.compile(r"https?://[^\s<>\]]+", flags=re.IGNORECASE)
    result: list[str] = []
    position = 0

    for match in url_pattern.finditer(text):
        start = match.start()
        raw_url = match.group(0)

        if start >= 2 and text[start - 2 : start] == "](":
            continue

        if start >= 1 and text[start - 1] == "(":
            continue

        raw_url, trailing = _split_url_trailing_punctuation(raw_url)

        result.append(text[position:start])
        label = _link_label_for_url(raw_url)
        safe_url = raw_url.replace(")", "%29")
        result.append(f"[{label}]({safe_url})")
        result.append(trailing)
        position = match.end()

    if not result:
        return text

    result.append(text[position:])
    return "".join(result)


def normalize_assistant_link_markup(text: str) -> str:
    """Convert accidental raw HTML and bare URLs into polished Markdown links.

    Fenced code blocks are preserved exactly so answers about HTML source code
    still render as code.
    """

    raw_text = str(text or "")

    parts = re.split(FENCED_CODE_PATTERN, raw_text, flags=re.DOTALL)
    normalized_parts: list[str] = []

    for part in parts:
        if not part:
            continue

        if part.startswith("```") or part.startswith("~~~"):
            normalized_parts.append(part)
        else:
            segment = part
            if re.search(r"(?is)&lt;/?[a-z]|</?[a-z][^>]*>", segment):
                segment = _normalize_html_segment(segment)
            segment = _normalize_source_url_lines(segment)
            segment = _linkify_bare_urls(segment)
            normalized_parts.append(segment)

    return "".join(normalized_parts).strip()


__all__ = ["normalize_assistant_link_markup"]
