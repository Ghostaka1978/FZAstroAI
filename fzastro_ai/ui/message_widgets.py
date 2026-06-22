import html
import os
import re
import threading
import tempfile
import uuid
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import Request, urlopen

import markdown
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.util import ClassNotFound
from PySide6.QtCore import QPoint, QPropertyAnimation, Qt, QTimer, Signal, QUrl
from PySide6.QtGui import (
    QAction,
    QColor,
    QDesktopServices,
    QKeyEvent,
    QKeySequence,
    QPainter,
    QPixmap,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..assistant_text import normalize_assistant_link_markup
from ..composer_tools import empty_fenced_code_block, fenced_code_block
from ..chat_blocks import (
    ChatMessage,
    CitationBlock,
    CodeBlock,
    ContentBlock,
    DailyNewsBriefBlock,
    FileAttachmentBlock,
    ImageBlock,
    NewsBlock,
    NewsHeaderBlock,
    MarketPulseBlock,
    SourceHeaderBlock,
    StockQuoteBlock,
    TableBlock,
    TextBlock,
    ToolResultBlock,
    VideoBlock,
    WebArticleBlock,
    blocks_to_plain_text,
    coerce_blocks,
)
from ..logging_utils import log_exception
from ..market_sources import (
    _stock_number,
    market_pulse_plain_text,
    parse_market_pulse_payload,
    parse_stock_quote_payload,
    stock_quote_plain_text,
)
from ..routing.source_tags import (
    infer_response_source_tags,
    normalize_response_source_tags,
)
from .source_chips import add_source_header_widget

CHAT_BLOCK_RENDERERS = {
    SourceHeaderBlock: "_render_source_header_block",
    NewsHeaderBlock: "_render_news_header_block",
    TextBlock: "_render_text_content_block",
    CodeBlock: "_render_code_content_block",
    ImageBlock: "_render_image_content_block",
    VideoBlock: "_render_video_content_block",
    FileAttachmentBlock: "_render_file_attachment_block",
    WebArticleBlock: "_render_web_article_block",
    NewsBlock: "_render_news_content_block",
    TableBlock: "_render_table_content_block",
    ToolResultBlock: "_render_tool_result_block",
    CitationBlock: "_render_citation_block",
    DailyNewsBriefBlock: "_render_daily_news_brief_block",
    StockQuoteBlock: "_render_stock_quote_block",
    MarketPulseBlock: "_render_market_pulse_block",
}


def escape_text(text):
    return html.escape(text)


LATEX_SYMBOL_REPLACEMENTS = {
    "\\alpha": "α",
    "\\beta": "β",
    "\\gamma": "γ",
    "\\Gamma": "Γ",
    "\\delta": "δ",
    "\\Delta": "Δ",
    "\\epsilon": "ε",
    "\\varepsilon": "ε",
    "\\zeta": "ζ",
    "\\eta": "η",
    "\\theta": "θ",
    "\\Theta": "Θ",
    "\\kappa": "κ",
    "\\lambda": "λ",
    "\\Lambda": "Λ",
    "\\mu": "μ",
    "\\nu": "ν",
    "\\xi": "ξ",
    "\\pi": "π",
    "\\Pi": "Π",
    "\\rho": "ρ",
    "\\sigma": "σ",
    "\\Sigma": "Σ",
    "\\tau": "τ",
    "\\phi": "φ",
    "\\varphi": "φ",
    "\\Phi": "Φ",
    "\\chi": "χ",
    "\\psi": "ψ",
    "\\Psi": "Ψ",
    "\\omega": "ω",
    "\\Omega": "Ω",
    "\\times": "×",
    "\\cdot": "·",
    "\\pm": "±",
    "\\mp": "∓",
    "\\approx": "≈",
    "\\simeq": "≃",
    "\\sim": "∼",
    "\\propto": "∝",
    "\\leq": "≤",
    "\\le": "≤",
    "\\geq": "≥",
    "\\ge": "≥",
    "\\neq": "≠",
    "\\ne": "≠",
    "\\infty": "∞",
    "\\rightarrow": "→",
    "\\Rightarrow": "⇒",
    "\\leftarrow": "←",
    "\\Leftarrow": "⇐",
    "\\to": "→",
    "\\ldots": "…",
    "\\dots": "…",
    "\\ln": "ln",
    "\\log": "log",
    "\\sin": "sin",
    "\\cos": "cos",
    "\\tan": "tan",
    "\\exp": "exp",
}

SUPERSCRIPT_CHARS = str.maketrans("0123456789+-=()nix", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿᶦˣ")

SUBSCRIPT_CHARS = str.maketrans(
    "0123456789+-=()aeiouhklmnpstx", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑᵢₒᵤₕₖₗₘₙₚₛₜₓ"
)


def _strip_latex_wrappers(text):
    text = re.sub(r"\\(?:left|right)\s*", "", str(text or ""))
    text = re.sub(
        r"\\(?:text|mathrm|mathbf|mathit|operatorname)\{([^{}]*)\}",
        lambda match: match.group(1),
        text,
    )
    text = text.replace("\\dot{m}", "ṁ")
    text = re.sub(
        r"\\frac\{([^{}]+)\}\{([^{}]+)\}",
        lambda match: f"{match.group(1).strip()} / {match.group(2).strip()}",
        text,
    )
    return text


def _replace_latex_symbols(text):
    for command, symbol in sorted(
        LATEX_SYMBOL_REPLACEMENTS.items(), key=lambda item: len(item[0]), reverse=True
    ):
        text = text.replace(command, symbol)
    return text


def _clean_latex_script_content(content):
    clean = _replace_latex_symbols(_strip_latex_wrappers(content))
    clean = clean.replace("{", "").replace("}", "").strip()
    return clean


def _replace_latex_scripts_html(text):
    script_pattern = r"(?:\{([^{}]+)\}|([A-Za-z0-9Α-Ωα-ω,+\-=().]+))"

    def replace_superscript(match):
        base = match.group(1)
        script = _clean_latex_script_content(match.group(2) or match.group(3) or "")
        return f"{base}<sup>{html.escape(script)}</sup>"

    def replace_subscript(match):
        base = match.group(1)
        script = _clean_latex_script_content(match.group(2) or match.group(3) or "")
        return f"{base}<sub>{html.escape(script)}</sub>"

    text = re.sub(
        r"(?<![A-Za-z0-9_])([A-Za-z0-9Α-Ωα-ω]+)\^" + script_pattern,
        replace_superscript,
        text,
    )
    text = re.sub(
        r"(?<![A-Za-z0-9_])([A-Za-zΑ-Ωα-ω])_" + script_pattern,
        replace_subscript,
        text,
    )
    return text


def _unicode_script(script, table):
    clean = _clean_latex_script_content(script)
    converted = clean.translate(table)
    if converted == clean:
        return None
    return converted


def _replace_latex_scripts_plain(text):
    script_pattern = r"(?:\{([^{}]+)\}|([A-Za-z0-9Α-Ωα-ω,+\-=().]+))"

    def replace_superscript(match):
        base = match.group(1)
        script = match.group(2) or match.group(3) or ""
        converted = _unicode_script(script, SUPERSCRIPT_CHARS)
        if converted is None:
            return f"{base}^{_clean_latex_script_content(script)}"
        return f"{base}{converted}"

    def replace_subscript(match):
        base = match.group(1)
        script = match.group(2) or match.group(3) or ""
        converted = _unicode_script(script, SUBSCRIPT_CHARS)
        if converted is None:
            return f"{base}_{_clean_latex_script_content(script)}"
        return f"{base}{converted}"

    text = re.sub(
        r"(?<![A-Za-z0-9_])([A-Za-z0-9Α-Ωα-ω]+)\^" + script_pattern,
        replace_superscript,
        text,
    )
    text = re.sub(
        r"(?<![A-Za-z0-9_])([A-Za-zΑ-Ωα-ω])_" + script_pattern,
        replace_subscript,
        text,
    )
    return text


def clean_latex_math(text):
    """Convert lightweight LaTeX into Qt-rich-text friendly HTML.

    Markdown rendering is not a full MathJax engine, so common model output like
    T_0, \\Omega_\\gamma,0, \\text{ K}, and 10^{-5} needs to be normalized
    before it reaches QTextBrowser.
    """
    text = _strip_latex_wrappers(text)
    text = _replace_latex_symbols(text)
    text = _replace_latex_scripts_html(text)
    text = re.sub(r"\\([A-Za-z]+)", r"\1", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_latex_plain_text(text):
    """Convert lightweight LaTeX for the fast plain-text streaming QLabel."""
    text = str(text or "")
    text = re.sub(
        r"\\\[(.*?)\\\]",
        lambda match: clean_latex_plain_text(match.group(1)),
        text,
        flags=re.DOTALL,
    )
    text = re.sub(
        r"\\\((.*?)\\\)",
        lambda match: clean_latex_plain_text(match.group(1)),
        text,
        flags=re.DOTALL,
    )
    text = re.sub(
        r"\$\$(.*?)\$\$",
        lambda match: clean_latex_plain_text(match.group(1)),
        text,
        flags=re.DOTALL,
    )
    text = re.sub(
        r"\$(.*?)\$",
        lambda match: clean_latex_plain_text(match.group(1)),
        text,
    )
    text = _strip_latex_wrappers(text)
    text = _replace_latex_symbols(text)
    text = _replace_latex_scripts_plain(text)
    text = re.sub(r"\\([A-Za-z]+)", r"\1", text)
    return text


def normalize_loose_latex_markup(text):
    """Clean loose LaTeX fragments without flattening normal Markdown.

    The previous implementation sent the whole assistant message through
    clean_latex_math(). That function is useful for a single formula, but it
    collapses all whitespace. Source-code answers often contain identifiers
    such as cache_key, ttl_days, HIPS_ENDPOINT, and imagefetch.py; the broad
    underscore detector mistook those for LaTeX and turned a structured answer
    into one huge paragraph.
    """
    text = str(text or "")

    latex_fragment_pattern = (
        r"\\[A-Za-z]+"
        r"|(?<![A-Za-z0-9_])[A-Za-zΑ-Ωα-ω0-9]\^\{?"
        r"|(?<![A-Za-z0-9_])[A-Za-zΑ-Ωα-ω]_[A-Za-z0-9Α-Ωα-ω{]"
    )

    if not re.search(latex_fragment_pattern, text):
        return text

    parts = re.split(r"(```.*?```|~~~.*?~~~)", text, flags=re.DOTALL)
    cleaned_parts = []

    for part in parts:
        if part.startswith("```") or part.startswith("~~~"):
            cleaned_parts.append(part)
            continue

        lines = part.split("\n")
        cleaned_lines = []

        for line in lines:
            # URLs, Markdown links, and inline code frequently contain
            # underscores. They are not LaTeX and must keep their exact text.
            if (
                "`" in line
                or "http://" in line
                or "https://" in line
                or re.search(r"\b[A-Za-z][A-Za-z0-9]+_[A-Za-z0-9_]+\b", line)
            ):
                cleaned_lines.append(line)
            elif re.search(latex_fragment_pattern, line):
                cleaned_lines.append(clean_latex_math(line))
            else:
                cleaned_lines.append(line)

        cleaned_parts.append("\n".join(cleaned_lines))

    return "".join(cleaned_parts)


def sanitize_markdown_images(text, has_local_image=False):
    """Prevent QTextBrowser from showing broken remote-image placeholders.

    Downloaded web images are rendered by ImagePreview. If no local image is
    attached, preserve access to a model-produced image URL as a normal link
    instead of asking QTextBrowser to fetch and decode it as an inline image.
    """
    clean_text = str(text or "")

    def replace_markdown_image(match):
        alt_text = re.sub(r"\s+", " ", match.group(1) or "").strip()
        image_url = (match.group(2) or "").strip()

        if has_local_image:
            return ""

        label = f"Open image: {alt_text}" if alt_text else "Open image"
        return f"[{label}]({image_url})"

    clean_text = re.sub(
        r"!\[([^\]]*)\]\((\S+?)(?:\s+[\"'][^\"']*[\"'])?\)",
        replace_markdown_image,
        clean_text,
        flags=re.IGNORECASE,
    )

    def replace_html_image(match):
        tag = match.group(0)
        source_match = re.search(
            r"src\s*=\s*[\"']([^\"']+)[\"']", tag, flags=re.IGNORECASE
        )
        alt_match = re.search(
            r"alt\s*=\s*[\"']([^\"']*)[\"']", tag, flags=re.IGNORECASE
        )

        if has_local_image:
            return ""

        if not source_match:
            return ""

        image_url = source_match.group(1).strip()
        alt_text = alt_match.group(1).strip() if alt_match else ""
        label = f"Open image: {alt_text}" if alt_text else "Open image"
        return f"[{label}]({image_url})"

    clean_text = re.sub(
        r"<img\b[^>]*>", replace_html_image, clean_text, flags=re.IGNORECASE
    )
    clean_text = re.sub(r"\n{3,}", "\n\n", clean_text)
    return clean_text.strip()


NEWS_BRIEF_SECTION_NAMES = (
    "World",
    "Europe",
    "United States",
    "Technology",
    "Artificial Intelligence",
    "Cybersecurity",
    "Business",
    "Markets",
    "Energy",
    "Science",
    "Space",
    "Health",
    "Climate",
    "Defense",
)


def is_document_inventory_response(text):
    """Detect direct Document Knowledge Library inventory output.

    The file names contain underscores and hyphen-separated titles, which the
    loose-LaTeX cleaner and compact-Markdown fixer can mistake for math/scripts
    or nested bullets.  Direct inventory output is deterministic, so it should
    bypass both cleanup passes.
    """
    clean_text = str(text or "")
    if "document-inventory" in clean_text:
        return True

    return "document-inventory-table" in clean_text or (
        (
            "Document Knowledge Library" in clean_text
            or "Imported documents" in clean_text
        )
        and re.search(r"(?im)^\s*(?:\|\s*#\s*\||\d+\.\s+\*\*)", clean_text) is not None
    )


def is_direct_browser_tool_response(text):
    """Detect deterministic browser-tool output that must keep line breaks.

    URLs often contain underscores and query strings.  The loose LaTeX cleaner
    treats underscores as math subscripts and collapses whitespace, which turns
    clean extraction output into one huge paragraph.  Browser-tool output is not
    LaTeX, so it bypasses that cleaner.
    """
    clean_text = str(text or "").lstrip()
    return clean_text.startswith(
        (
            "**Rendered page extracted.**",
            "Rendered page extracted.",
            "**Website screenshot captured.**",
            "Website screenshot captured.",
            "[RENDERED PAGE]",
            "[WEB SCREENSHOT]",
        )
    )


def _normalize_compacted_markdown_segment(segment):
    """Repair model Markdown that was streamed as one physical paragraph.

    Some local models emit valid Markdown tokens, but without the line breaks
    Markdown needs.  Example: "text ### Heading * Focus: ...".  QTextBrowser
    then renders heading markers and bullets as plain text.  This normalizer only
    touches obvious Markdown structure outside fenced code blocks.
    """
    clean_text = str(segment or "")

    if not clean_text.strip():
        return clean_text

    # Put inline Markdown headings on their own line:
    # "cover: ### 1. Title" -> "cover:\n\n### 1. Title".
    clean_text = re.sub(
        r"(?<!^)(?<!\n)[ \t]+(?=#{1,6}[ \t]+\S)",
        "\n\n",
        clean_text,
    )

    # Some models also continue the body on the same physical line as a
    # heading, e.g. "### Core Functionality The primary purpose...".
    # Markdown only recognizes a heading up to the end of the line, so split
    # common analysis headings before the body text.
    inline_heading_titles = (
        "Overview",
        "Summary",
        "Core Functionality",
        "Key Features",
        "Technical Summary",
        "Technical Summary of Logic Flow",
        "Logic Flow",
        "Dependencies",
        "Issues",
        "Potential Issues",
        "Recommendations",
        "Suggested Fix",
        "What I changed",
        "How it works",
        "Result",
    )
    inline_heading_pattern = "|".join(
        re.escape(value)
        for value in sorted(inline_heading_titles, key=len, reverse=True)
    )
    clean_text = re.sub(
        rf"(?m)^(#{{1,6}}[ \t]+(?:{inline_heading_pattern}))[ \t]+(?=\S)",
        r"\1\n\n",
        clean_text,
    )

    # If a heading is followed immediately by a compact bullet marker, keep
    # the marker as the first item under the heading.
    clean_text = re.sub(
        r"(?m)^(#{1,6}[ \t]+[^\n]{3,100}?)[ \t]+[-–—][ \t]+(?=\S)",
        r"\1\n\n- ",
        clean_text,
    )

    # If a model places body text after a PDF/book heading, split after the
    # filename so the heading does not absorb the whole paragraph.
    clean_text = re.sub(
        r"(?m)^(#{1,6}[ \t]+[^\n]*?\.pdf(?:\*\*)?)[ \t]+(?=[A-Z])",
        r"\1\n\n",
        clean_text,
    )

    # Also support headings wrapped in bold where the body starts immediately
    # after the closing ** marker.
    clean_text = re.sub(
        r"(?m)^(#{1,6}[ \t]+[^\n]{3,220}?\*\*)[ \t]+(?=[A-Z][a-z])",
        r"\1\n\n",
        clean_text,
    )

    # Restore compact inline bullets used by the model for labelled points:
    # "... * Focus: ... * Scope: ..." -> separate Markdown bullets.
    clean_text = re.sub(
        r"(?<!^)(?<!\n)[ \t]+[*•][ \t]+(?=(?:\*\*)?[A-Z][A-Za-z0-9 /&()\-]{1,48}(?:\*\*)?:)",
        "\n- ",
        clean_text,
    )

    # Restore obvious inline numbered-list items.
    clean_text = re.sub(
        r"(?<!^)(?<![#\n])[ \t]+(?=\d{1,2}[.)][ \t]+\S)",
        "\n",
        clean_text,
    )

    # Restore compact sub-bullets inside numbered items:
    # "1. **Cache:** - Checks file" -> nested bullet on the next line.
    clean_text = re.sub(
        r"(?<!^)(?<!\n)[ \t]+[-–—][ \t]+(?=[A-Z`])",
        "\n  - ",
        clean_text,
    )

    # Normalize bullet markers created above without changing ordinary emphasis.
    clean_text = re.sub(r"(?m)^\s*[*•]\s+", "- ", clean_text)
    clean_text = re.sub(r"\n{3,}", "\n\n", clean_text)
    return clean_text.strip("\n")


def normalize_compacted_markdown(text):
    """Repair missing Markdown line breaks while preserving fenced code.

    Fenced code blocks must remain on their own physical lines. The compacted
    Markdown fixer trims non-code segments, so joining those trimmed segments
    directly against a preserved fence can accidentally create invalid Markdown
    such as ``**Output:**```text``. Preserve the boundary newlines around each
    non-code segment before joining the parts back together.
    """
    clean_text = re.sub(r"\r\n?", "\n", str(text or ""))

    if not re.search(
        r"#{1,6}\s+|[*•]\s+(?:\*\*)?[A-Z][A-Za-z0-9 /&()\-]{1,48}(?:\*\*)?:|\d{1,2}[.)]\s+",
        clean_text,
    ):
        return clean_text

    parts = re.split(r"(```.*?```|~~~.*?~~~)", clean_text, flags=re.DOTALL)
    normalized_parts = []

    for part in parts:
        if not part:
            continue

        if part.startswith("```") or part.startswith("~~~"):
            # Ensure a fence is never glued to surrounding inline Markdown.
            if normalized_parts and not normalized_parts[-1].endswith("\n"):
                normalized_parts[-1] += "\n"

            normalized_parts.append(part)
            continue

        leading_match = re.match(r"^\n*", part)
        trailing_match = re.search(r"\n*$", part)
        leading_newlines = leading_match.group(0) if leading_match else ""
        trailing_newlines = trailing_match.group(0) if trailing_match else ""
        core_start = len(leading_newlines)
        core_end = len(part) - len(trailing_newlines)
        core = part[core_start:core_end] if core_end >= core_start else ""

        if core:
            normalized_core = _normalize_compacted_markdown_segment(core)
            normalized_parts.append(
                leading_newlines + normalized_core + trailing_newlines
            )
        else:
            normalized_parts.append(part)

    result = "".join(normalized_parts)

    # If a following paragraph starts immediately after a closing fence, restore
    # a paragraph break so blockquotes/lists/headings render normally.
    result = re.sub(r"(?m)^(```|~~~)\s*\n(?=\S)", r"\1\n\n", result)
    return result.strip()


def normalize_news_brief_markdown(text):
    """Repair compacted daily-news Markdown before Qt rich-text rendering.

    Some local models compress the whole news answer into one physical line, for
    example: "# Daily News Brief ## World * Story... * Story...".  Markdown then
    treats the entire line as one H1, making the whole brief huge.  This keeps the
    news card layout deterministic even when the model misses newlines.
    """
    clean_text = re.sub(r"\r\n?", "\n", str(text or "")).strip()

    if not clean_text:
        return clean_text

    section_pattern = "|".join(
        re.escape(section_name) for section_name in NEWS_BRIEF_SECTION_NAMES
    )

    # Restore missing line breaks before Markdown headings.
    # Do not split after a bullet marker: "- #New40k ..." must stay a bullet,
    # not become a blank bullet followed by a giant heading.
    clean_text = re.sub(
        r"(?<!^)(?<!\n)(?<![-*•])\s+(?=#{1,6}\s+)",
        "\n\n",
        clean_text,
    )
    clean_text = re.sub(
        rf"(?<!^)(?<!\n)\s+(?=##\s*(?:{section_pattern})\b)",
        "\n\n",
        clean_text,
        flags=re.IGNORECASE,
    )

    # Handle a compact title without the leading #.
    clean_text = re.sub(
        rf"^\s*Daily\s+News\s+Brief\s+(?=##\s*(?:{section_pattern})\b)",
        "Daily News Brief\n\n",
        clean_text,
        count=1,
        flags=re.IGNORECASE,
    )

    # Keep each H2 section header on its own paragraph.
    clean_text = re.sub(
        rf"^(##\s*(?:{section_pattern})\b[^\n]*?)\s+(?=(?:[-*•]|\d+[.)])\s+)",
        r"\1\n\n",
        clean_text,
        flags=re.IGNORECASE | re.MULTILINE,
    )

    # Keep each bullet on its own line if the model streamed them inline.
    clean_text = re.sub(
        r"(?<!^)(?<!\n)\s+(?=(?:[-*•]|\d+[.)])\s+\S)",
        "\n",
        clean_text,
    )

    # The card already displays a fixed DAILY NEWS BRIEF header, so remove the
    # duplicate model-generated title from the message body.
    clean_text = re.sub(
        r"^\s*#?\s*Daily\s+News\s+Brief\s*(?:\n+|$)",
        "",
        clean_text,
        count=1,
        flags=re.IGNORECASE,
    )

    # Prefer a single bullet marker style inside news cards.
    clean_text = re.sub(r"(?m)^\s*[*•]\s+", "- ", clean_text)

    # Defensive pass for article titles that arrived with a Markdown heading
    # marker after the bullet, e.g. "- #New40k ..." or "- # New40k ...".
    # Without this, Markdown renders that one bullet as a giant H1 while the
    # rest of the news items remain normal list items.
    clean_text = re.sub(
        r"(?m)^(\s*(?:[-*•]|\d{1,3}[.)])\s+)#{1,6}\s*(?=\S)",
        r"\1",
        clean_text,
    )

    clean_text = re.sub(r"\n{3,}", "\n\n", clean_text)
    return clean_text.strip()


NEWS_CITATION_GROUP_RE = re.compile(
    r"[\[(]\s*((?:NEWS_\d{4,}\s*,?\s*)+)\s*[\])]", re.IGNORECASE
)


def _plain_label_text(value, fallback=""):
    clean = html.unescape(str(value or "")).strip()
    clean = re.sub(r"\s+", " ", clean)
    return clean or fallback


def _clean_news_story_headline(text, source_name=""):
    clean = _plain_label_text(text)
    publisher = _plain_label_text(source_name)
    clean = re.sub(r"^\s*(?:[-*â€¢]|\d{1,3}[.)])\s+", "", clean)
    clean = NEWS_CITATION_GROUP_RE.sub("", clean)
    clean = re.sub(r"\s+", " ", clean).strip(" \t\r\n-:;")

    if publisher and clean.casefold().endswith((" - " + publisher).casefold()):
        clean = clean[: -len(" - " + publisher)].rstrip(" \t\r\n-:;")
    elif " - " in clean:
        possible_headline, possible_publisher = clean.rsplit(" - ", 1)
        if possible_publisher and len(possible_publisher.strip()) <= 80:
            clean = possible_headline.strip(" \t\r\n-:;")

    return clean


def _news_source_record(source_id, source_value):
    clean_id = _plain_label_text(source_id)

    if isinstance(source_value, dict):
        return {
            "id": clean_id,
            "publisher": _plain_label_text(source_value.get("name"), "Source"),
            "url": _plain_label_text(source_value.get("url")),
            "source_title": _plain_label_text(source_value.get("title")),
            "summary": _plain_label_text(source_value.get("summary")),
            "published_at": _plain_label_text(source_value.get("published_at")),
            "image_url": _plain_label_text(source_value.get("image_url")),
        }

    return {
        "id": clean_id,
        "publisher": clean_id or "Source",
        "url": _plain_label_text(source_value),
        "source_title": "",
        "summary": "",
        "published_at": "",
        "image_url": "",
    }


def build_daily_news_brief_payload(text, news_sources):
    """Parse the deterministic Daily News markdown into UI-ready sections."""
    normalized_text = normalize_news_brief_markdown(text)
    source_lookup = {
        str(source_id or "")
        .strip()
        .upper(): _news_source_record(source_id, source_value)
        for source_id, source_value in (news_sources or {}).items()
        if str(source_id or "").strip()
    }
    sections = []
    current_section = None

    def ensure_section(name):
        nonlocal current_section
        clean_name = _plain_label_text(name, "Top Stories")
        current_section = {"name": clean_name, "stories": []}
        sections.append(current_section)
        return current_section

    for raw_line in normalized_text.splitlines():
        line = raw_line.strip()

        if not line:
            continue

        if line.startswith("#"):
            heading = re.sub(r"^#+\s*", "", line).strip()

            if heading and heading.casefold() != "daily news brief":
                ensure_section(heading)
            continue

        bullet_match = re.match(r"^(?:[-*â€¢]|\d{1,3}[.)])\s+(.+)$", line)

        if not bullet_match:
            continue

        bullet_text = bullet_match.group(1).strip()
        source_ids = [
            match.upper()
            for group in NEWS_CITATION_GROUP_RE.findall(bullet_text)
            for match in re.findall(r"NEWS_\d{4,}", group, flags=re.IGNORECASE)
        ]
        headline = _clean_news_story_headline(bullet_text)

        if not current_section:
            ensure_section("Top Stories")

        primary_source = None

        for source_id in source_ids:
            primary_source = source_lookup.get(source_id)

            if primary_source:
                break

        if primary_source is None and source_ids:
            primary_source = {"id": source_ids[0], "publisher": source_ids[0]}
        elif primary_source is None:
            primary_source = {}

        source_title = _clean_news_story_headline(
            primary_source.get("source_title"), primary_source.get("publisher")
        )
        display_headline = headline or source_title

        if not display_headline:
            continue

        story = {
            "headline": display_headline,
            "section": current_section["name"],
            "source_ids": source_ids,
            "primary_source_id": primary_source.get("id") or "",
            "publisher": primary_source.get("publisher") or "Source",
            "url": primary_source.get("url") or "",
            "source_title": source_title,
            "summary": primary_source.get("summary") or "",
            "published_at": primary_source.get("published_at") or "",
            "image_url": primary_source.get("image_url") or "",
        }
        current_section["stories"].append(story)

    sections = [section for section in sections if section.get("stories")]

    if not sections and source_lookup:
        fallback_stories = []

        for source in list(source_lookup.values())[:12]:
            headline = _clean_news_story_headline(
                source.get("source_title"), source.get("publisher")
            )

            if not headline:
                continue

            fallback_stories.append(
                {
                    "headline": headline,
                    "section": "Sources",
                    "source_ids": [source.get("id")],
                    "primary_source_id": source.get("id") or "",
                    "publisher": source.get("publisher") or "Source",
                    "url": source.get("url") or "",
                    "source_title": headline,
                    "summary": source.get("summary") or "",
                    "published_at": source.get("published_at") or "",
                    "image_url": source.get("image_url") or "",
                }
            )

        if fallback_stories:
            sections = [{"name": "Sources", "stories": fallback_stories}]

    if not sections:
        return {}

    lead_story = None

    for section in sections:
        for story in section.get("stories") or []:
            if story.get("summary") or story.get("image_url"):
                lead_story = story
                break

        if lead_story:
            break

    if lead_story is None:
        lead_story = sections[0]["stories"][0]

    stories = [story for section in sections for story in section.get("stories") or []]
    image_count = sum(1 for story in stories if story.get("image_url"))

    return {
        "title": "Daily News Brief",
        "sections": sections,
        "lead_story": lead_story,
        "story_count": len(stories),
        "source_count": len(news_sources or {}),
        "image_count": image_count,
    }


def render_text_block(text, news_mode=False, user_mode=False, plain_mode=False):
    text = str(text or "")
    inventory_mode = is_document_inventory_response(text)
    browser_tool_mode = is_direct_browser_tool_response(text)

    if plain_mode:
        escaped_lines = html.escape(text).splitlines() or [""]
        html_content = "<br>\n".join(escaped_lines)
    elif news_mode:
        text = normalize_news_brief_markdown(text)
    elif not user_mode and not inventory_mode and not browser_tool_mode:
        text = normalize_assistant_link_markup(text)
        text = normalize_compacted_markdown(text)

    if not plain_mode:
        text = re.sub(
            r"\\\[(.*?)\\\]",
            lambda m: f"$${m.group(1)}$$",
            text,
            flags=re.DOTALL,
        )
        text = re.sub(
            r"\\\((.*?)\\\)",
            lambda m: f"${m.group(1)}$",
            text,
            flags=re.DOTALL,
        )

        text = re.sub(
            r"\$\$(.*?)\$\$",
            lambda m: f'<div class="math-block">{clean_latex_math(m.group(1))}</div>',
            text,
            flags=re.DOTALL,
        )

        text = re.sub(
            r"\$(.*?)\$",
            lambda m: f'<span class="math-inline">{clean_latex_math(m.group(1))}</span>',
            text,
        )

        # Models often emit raw LaTeX without dollar delimiters. Normalize those
        # fragments before Markdown so the final message does not show markup such
        # as \text{ K}, \Omega_\gamma,0, or 10^{-5}.
        # Do not run this on Daily News: source IDs such as NEWS_0001 look like
        # LaTeX subscripts to the lightweight cleaner, and clean_latex_math()
        # collapses newlines. That turns valid news Markdown into one huge heading.
        inventory_mode = inventory_mode or is_document_inventory_response(text)
        browser_tool_mode = browser_tool_mode or is_direct_browser_tool_response(text)

        if not news_mode and not inventory_mode and not browser_tool_mode:
            text = normalize_loose_latex_markup(text)

        # One final pass after lightweight LaTeX cleanup protects responses that
        # contain both formulas and compact Markdown headings/lists. Deterministic
        # app-generated tables and browser output already have intentional layout.
        if (
            not news_mode
            and not user_mode
            and not inventory_mode
            and not browser_tool_mode
        ):
            text = normalize_compacted_markdown(text)

        html_content = markdown.markdown(
            text, extensions=["fenced_code", "tables", "sane_lists", "nl2br"]
        )

        if news_mode:
            # Last-resort HTML cleanup.  QTextBrowser supports only part of CSS, so
            # relying on CSS to shrink <h1> tags inside <li> is not enough.  Convert
            # accidental list-item headings back into normal list-item text.
            html_content = re.sub(
                r"(?is)<li>\s*<h[1-6][^>]*>(.*?)</h[1-6]>\s*</li>",
                r"<li>\1</li>",
                html_content,
            )
            html_content = re.sub(
                r"(?is)<li>\s*<h[1-6][^>]*>(.*?)</h[1-6]>",
                r"<li>\1",
                html_content,
            )

    mode_class = (
        "news-copy" if news_mode else "user-copy" if user_mode else "assistant-copy"
    )

    return f"""
<style>
body {{
    margin: 0;
    padding: 0;
    background: transparent;
}}

.chat-copy {{
    color: #e8e8e8;
    font-family: "Segoe UI Variable", "Segoe UI", sans-serif;
    font-size: 15px;
    line-height: 1.58;
    background: transparent;
    white-space: normal;
    word-wrap: break-word;
    overflow-wrap: anywhere;
}}

.chat-copy p {{
    margin: 0 0 11px 0;
}}

.chat-copy p:last-child {{
    margin-bottom: 0;
}}

.chat-copy h1 {{
    color: #ffffff;
    font-size: 23px;
    line-height: 1.25;
    font-weight: 750;
    margin: 18px 0 11px 0;
}}

.chat-copy h1:first-child,
.chat-copy h2:first-child,
.chat-copy h3:first-child {{
    margin-top: 0;
}}

.chat-copy h2 {{
    color: #f4f4f4;
    font-size: 19px;
    line-height: 1.3;
    font-weight: 700;
    margin: 16px 0 9px 0;
}}

.chat-copy h3 {{
    color: #eeeeee;
    font-size: 16px;
    line-height: 1.35;
    font-weight: 700;
    margin: 13px 0 7px 0;
}}

.chat-copy ul,
.chat-copy ol {{
    margin: 7px 0 12px 24px;
    padding: 0;
}}

.chat-copy li {{
    margin: 0 0 7px 0;
    padding-left: 2px;
}}

.chat-copy li p {{
    margin: 0 0 6px 0;
}}

.chat-copy a {{
    color: #8dbfff;
    text-decoration: none;
}}

.chat-copy strong {{
    color: #ffffff;
    font-weight: 700;
}}

.chat-copy em {{
    color: #d3d3d3;
}}

.chat-copy sub,
.chat-copy sup {{
    color: #7dd3fc;
    font-size: 0.78em;
    line-height: 0;
}}

.chat-copy blockquote {{
    color: #d0d6de;
    background: #15191e;
    border-left: 4px solid #536a84;
    margin: 10px 0;
    padding: 9px 12px;
}}

.chat-copy hr {{
    border: none;
    border-top: 1px solid #303030;
    margin: 16px 0;
}}

.chat-copy code {{
    color: #c5e4ff;
    background: #1b222a;
    border: 1px solid #2d3945;
    padding: 1px 5px;
    font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
    font-size: 13px;
}}

.chat-copy pre {{
    white-space: pre-wrap;
    word-wrap: break-word;
    background: #0d1117;
    border: 1px solid #28313a;
    border-radius: 9px;
    padding: 10px 12px;
    margin: 10px 0 12px 0;
}}

.chat-copy pre code {{
    background: transparent;
    border: none;
    padding: 0;
}}

.chat-copy table {{
    border-collapse: collapse;
    margin: 10px 0 14px 0;
    max-width: 100%;
}}

.chat-copy th {{
    color: #ffffff;
    background: #20242a;
    border: 1px solid #3a3f46;
    padding: 7px 10px;
    font-weight: 700;
}}

.chat-copy td {{
    color: #dedede;
    background: #15171a;
    border: 1px solid #32363b;
    padding: 7px 10px;
}}

.user-copy {{
    color: #f0e2e2;
}}

.user-copy a {{
    color: #ff9c9c;
}}

.news-copy {{
    color: #e5e9ee;
    font-size: 15px;
    line-height: 1.55;
}}

.news-copy h1 {{
    color: #ffffff;
    background: #17212c;
    border-left: 4px solid #67a7ef;
    font-size: 20px;
    line-height: 1.25;
    margin: 18px 0 11px 0;
    padding: 9px 12px;
}}

.news-copy h2 {{
    color: #dcecff;
    background: #141b23;
    border-left: 3px solid #4d83bd;
    font-size: 17px;
    line-height: 1.3;
    margin: 16px 0 9px 0;
    padding: 7px 10px;
}}

.news-copy ul,
.news-copy ol {{
    margin: 7px 0 13px 22px;
}}

.news-copy li {{
    margin: 0 0 9px 0;
    padding-left: 3px;
}}

.news-copy a {{
    color: #91c6ff;
    font-weight: 650;
}}

.news-copy li h1,
.news-copy li h2,
.news-copy li h3,
.news-copy li h4,
.news-copy li h5,
.news-copy li h6 {{
    color: #e5e9ee;
    background: transparent;
    border-left: none;
    display: inline;
    font-size: 15px;
    line-height: 1.55;
    margin: 0;
    padding: 0;
    font-weight: 650;
}}

.document-inventory-list {{
    margin-top: 8px;
}}

.document-inventory-card {{
    display: block;
    margin: 0 0 10px 0;
    padding: 10px 12px;
    border: 1px solid #263244;
    border-radius: 9px;
    background-color: #0b111a;
}}

.document-inventory-title {{
    margin: 0 0 5px 0;
    font-size: 15px;
    line-height: 1.45;
}}

.document-inventory-index {{
    color: #94a3b8;
}}

.document-inventory-stats,
.document-inventory-actions,
.document-inventory-help {{
    margin: 3px 0;
    line-height: 1.45;
}}

.document-inventory-stats {{
    color: #d7e3f3;
}}

.document-inventory-actions a {{
    white-space: nowrap;
}}

.document-selected-badge {{
    color: #c4b5fd;
    font-weight: 700;
}}

.math-inline {{
    color: #7dd3fc;
    font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
    font-weight: 600;
}}

.math-block {{
    margin: 11px 0;
    padding: 11px;
    border-radius: 8px;
    background: #111827;
    border: 1px solid #374151;
    text-align: center;
    color: #7dd3fc;
    font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
}}
</style>

<div class="chat-copy {mode_class}">
    {html_content}
</div>
"""


def render_code_block(language, code):
    safe_language = escape_text((language or "code").capitalize())
    safe_code = escape_text(code.rstrip())

    return f"""
    <div style="
        background:#0d1117;
        border:1px solid #30363d;
        border-radius:12px;
        margin-top:10px;
        margin-bottom:10px;
        overflow:hidden;
    ">
        <div style="
            background:#161b22;
            color:#c9d1d9;
            padding:8px 12px;
            font-family:'Cascadia Code','JetBrains Mono',Consolas,monospace;
            font-size:12px;
            border-bottom:1px solid #30363d;
        ">
            {safe_language}
        </div>
        <pre style="
            color:#e6edf3;
            background:#0d1117;
            font-family:'Cascadia Code','JetBrains Mono',Consolas,monospace;
            font-size:13px;
            line-height:1.35;
            white-space:pre;
            overflow-x:auto;
            margin:0;
            padding:16px;
        ">{safe_code}</pre>
    </div>
    """


def parse_markdown_blocks(text):
    blocks = []
    lines = text.splitlines(keepends=True)
    text_buffer = []
    code_buffer = []
    in_code = False
    fence = ""
    language = "code"

    for line in lines:
        stripped = line.lstrip()

        if not in_code:
            match = re.match(r"(`{3,}|~{3,})([A-Za-z0-9_+\-.#]*)\s*$", stripped)

            if match:
                if text_buffer:
                    blocks.append(("text", "", "".join(text_buffer)))
                    text_buffer = []

                fence = match.group(1)
                language = match.group(2) or "code"
                code_buffer = []
                in_code = True
            else:
                text_buffer.append(line)
        else:
            closing_pattern = rf"^{re.escape(fence)}\s*$"

            if re.match(closing_pattern, stripped):
                blocks.append(("code", language, "".join(code_buffer)))
                code_buffer = []
                in_code = False
                fence = ""
                language = "code"
            else:
                code_buffer.append(line)

    if in_code:
        blocks.append(("code", language, "".join(code_buffer)))

    if text_buffer:
        blocks.append(("text", "", "".join(text_buffer)))

    return blocks


def highlight_code(language, code):
    try:
        lexer = get_lexer_by_name(language.lower())
    except ClassNotFound:
        try:
            lexer = guess_lexer(code)
        except ClassNotFound:
            lexer = get_lexer_by_name("text")

    formatter = HtmlFormatter(noclasses=True, style="github-dark", nowrap=True)

    return highlight(code.rstrip(), lexer, formatter)


class EnterSendTextEdit(QTextEdit):
    def __init__(self, send_callback, paste_files_callback):
        super().__init__()
        self.send_callback = send_callback
        self.paste_files_callback = paste_files_callback

    def wrap_selection_as_code(self, language=""):
        cursor = self.textCursor()
        selected_text = cursor.selectedText().replace("\u2029", "\n")

        if selected_text:
            cursor.insertText(fenced_code_block(selected_text, language))
            self.setTextCursor(cursor)
            return True

        current_text = self.toPlainText()

        if current_text:
            self.setPlainText(fenced_code_block(current_text, language))
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.setTextCursor(cursor)
            return True

        block_text, cursor_offset = empty_fenced_code_block(language)
        start_position = cursor.position()
        cursor.insertText(block_text)
        cursor.setPosition(start_position + cursor_offset)
        self.setTextCursor(cursor)
        return True

    def paste_clipboard_text_as_code(self, language=""):
        clipboard_text = QApplication.clipboard().text()

        if not clipboard_text:
            return False

        cursor = self.textCursor()
        cursor.insertText(fenced_code_block(clipboard_text, language))
        self.setTextCursor(cursor)
        return True

    def keyPressEvent(self, event: QKeyEvent):
        if (
            event.key() in (Qt.Key_Return, Qt.Key_Enter)
            and not event.modifiers() & Qt.ShiftModifier
        ):
            self.send_callback()
            return

        if event.matches(QKeySequence.StandardKey.Paste):
            clipboard = QApplication.clipboard()
            mime_data = clipboard.mimeData()

            if mime_data.hasImage():
                image = clipboard.image()

                if not image.isNull():
                    temp_dir = Path(tempfile.gettempdir()) / "fzastro_clipboard"
                    temp_dir.mkdir(parents=True, exist_ok=True)

                    file_path = temp_dir / f"clipboard_{uuid.uuid4().hex}.png"
                    image.save(str(file_path), "PNG")

                    self.paste_files_callback([str(file_path)])
                    return

            if mime_data.hasUrls():
                paths = []

                for url in mime_data.urls():
                    local_path = url.toLocalFile()

                    if local_path:
                        paths.append(local_path)

                if paths:
                    self.paste_files_callback(paths)
                    return

        super().keyPressEvent(event)


class SystemPromptTextEdit(QTextEdit):
    save_requested = Signal()

    def keyPressEvent(self, event: QKeyEvent):
        blocked_modifiers = (
            Qt.KeyboardModifier.ShiftModifier
            | Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.AltModifier
            | Qt.KeyboardModifier.MetaModifier
        )

        if (
            event.key() in (Qt.Key_Return, Qt.Key_Enter)
            and not event.modifiers() & blocked_modifiers
        ):
            self.save_requested.emit()
            event.accept()
            return

        super().keyPressEvent(event)


class AttachmentChip(QWidget):
    remove_requested = Signal(str)

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path
        self.setObjectName("attachmentChip")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 6, 4)
        layout.setSpacing(8)

        label = QLabel(Path(file_path).name)
        label.setObjectName("attachmentChipLabel")

        remove_button = QPushButton("×")
        remove_button.setFixedSize(22, 22)
        remove_button.setObjectName("removeAttachmentButton")
        remove_button.clicked.connect(
            lambda: self.remove_requested.emit(self.file_path)
        )

        layout.addWidget(label)
        layout.addWidget(remove_button)


class ImagePreview(QLabel):
    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path
        self.setObjectName("imagePreview")
        self.setAlignment(Qt.AlignLeft)

        pixmap = QPixmap()

        try:
            with open(file_path, "rb") as image_file:
                image_bytes = image_file.read()

            pixmap.loadFromData(image_bytes)
        except Exception as exc:
            log_exception("ImagePreview.__init__ line 6523", exc)
            pixmap = QPixmap()

        if not pixmap.isNull():
            normalized_path = str(file_path).replace("\\", "/").casefold()
            is_knowledge_page = "document_knowledge_assets" in normalized_path
            is_astro_image = any(
                marker in normalized_path
                for marker in (
                    "astro_tools/fzastro/web/cache/images/",
                    "astro_tools/images/",
                    "astro_tools/outputs/",
                    "fzastro_ai/astro_tools/",
                )
            )

            if is_knowledge_page:
                maximum_width = 760
                maximum_height = 920
            elif is_astro_image:
                screen = QApplication.primaryScreen()
                if screen is not None:
                    available = screen.availableGeometry()
                    maximum_width = min(1280, max(900, int(available.width() * 0.78)))
                    maximum_height = min(860, max(620, int(available.height() * 0.72)))
                else:
                    maximum_width = 1120
                    maximum_height = 760
            else:
                maximum_width = 420
                maximum_height = 280

            scaled = pixmap.scaled(
                maximum_width,
                maximum_height,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self.setPixmap(scaled)
            self.setFixedSize(scaled.size())
            self.setToolTip(
                "Retrieved PDF page from Document Knowledge Library"
                if is_knowledge_page
                else (
                    "Migrated FZASTRO image preview"
                    if is_astro_image
                    else Path(file_path).name
                )
            )
        else:
            self.setText(Path(file_path).name)


def clean_article_preview(text):
    lines = []

    blocked_lines = {
        "Home",
        "News",
        "Press Releases",
        "For Scientists",
        "Newsworthy Results",
        "Announcements",
        "Images",
        "Videos",
        "About",
        "Contact",
    }

    for line in text.splitlines():
        clean = line.strip()

        if not clean:
            continue

        if clean in blocked_lines:
            continue

        if len(clean) < 25:
            continue

        lines.append(clean)

    return " ".join(lines).strip()


class StockQuoteCard(QFrame):
    THEMES = {
        "CRM": {"accent": "#1b96ff", "soft": "#10283b", "button": "SALESFORCE"},
        "DBX": {"accent": "#6f8cff", "soft": "#171d3a", "button": "DROPBOX"},
        "CL=F": {"accent": "#e59a3a", "soft": "#332411", "button": "WTI CRUDE"},
        "GC=F": {"accent": "#f3c552", "soft": "#332a11", "button": "GOLD"},
    }

    def __init__(self, payload):
        super().__init__()
        self.payload = dict(payload or {})
        self.setObjectName("stockQuoteCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.setMaximumWidth(820)

        ticker = str(self.payload.get("ticker") or "").strip().upper()
        theme = self.THEMES.get(
            ticker,
            {"accent": "#79a8ff", "soft": "#172236", "button": ticker or "MARKET"},
        )

        accent = theme["accent"]
        soft = theme["soft"]

        self.setStyleSheet(
            f"""
            QFrame#stockQuoteCard {{
                background: #151515;
                border: 1px solid {accent};
                border-radius: 14px;
            }}
            QLabel {{
                background: transparent;
                border: none;
                color: #e9e9e9;
                font-family: "Segoe UI Variable", "Segoe UI";
            }}
            QLabel#stockAssetBadge {{
                background: {soft};
                color: {accent};
                border: 1px solid {accent};
                border-radius: 7px;
                padding: 4px 8px;
                font-size: 10px;
                font-weight: 800;
            }}
            QLabel#stockTitle {{
                color: #f4f4f4;
                font-size: 20px;
                font-weight: 700;
            }}
            QLabel#stockPrice {{
                color: {accent};
                font-size: 28px;
                font-weight: 800;
            }}
            QLabel#stockFieldLabel {{
                color: #9ca3af;
                font-size: 12px;
                font-weight: 650;
            }}
            QLabel#stockFieldValue {{
                color: #f2f2f2;
                font-size: 13px;
                font-weight: 600;
            }}
            QLabel#stockSourceLink {{
                color: {accent};
                font-size: 12px;
                font-weight: 650;
            }}
            QLabel#stockRetrieved {{
                color: #8f8f8f;
                font-size: 11px;
                font-style: italic;
            }}
        """
        )

        outer_layout = QHBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        accent_bar = QFrame()
        accent_bar.setFixedWidth(6)
        accent_bar.setStyleSheet(
            f"background: {accent}; border: none; "
            "border-top-left-radius: 13px; border-bottom-left-radius: 13px;"
        )
        outer_layout.addWidget(accent_bar)

        content = QWidget()
        content.setStyleSheet("background: transparent; border: none;")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 16, 20, 16)
        content_layout.setSpacing(10)
        outer_layout.addWidget(content, 1)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)

        asset_badge = QLabel(theme["button"])
        asset_badge.setObjectName("stockAssetBadge")
        asset_badge.setAlignment(Qt.AlignCenter)
        asset_badge.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        company_name = str(
            self.payload.get("company_name") or ticker or "Market quote"
        ).strip()

        title_label = QLabel(f"{company_name}  ({ticker})")
        title_label.setObjectName("stockTitle")
        title_label.setWordWrap(True)

        status_text = str(self.payload.get("market_status") or "Unavailable").strip()
        status_label = QLabel(status_text.upper())
        status_label.setAlignment(Qt.AlignCenter)
        status_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        if status_text.lower() == "open":
            status_background = "#123322"
            status_color = "#62d99b"
            status_border = "#2f7d56"
        elif status_text.lower() in {"pre-market", "after hours"}:
            status_background = soft
            status_color = accent
            status_border = accent
        else:
            status_background = "#232323"
            status_color = "#b9b9b9"
            status_border = "#444444"

        status_label.setStyleSheet(
            f"""
            background: {status_background};
            color: {status_color};
            border: 1px solid {status_border};
            border-radius: 7px;
            padding: 4px 8px;
            font-size: 10px;
            font-weight: 800;
        """
        )

        header_layout.addWidget(asset_badge, 0, Qt.AlignTop)
        header_layout.addWidget(title_label, 1)
        header_layout.addWidget(status_label, 0, Qt.AlignTop)
        content_layout.addLayout(header_layout)

        currency = str(self.payload.get("currency") or "USD").strip().upper()
        price = _stock_number(self.payload.get("price"))
        change = _stock_number(self.payload.get("change"))
        percentage_change = _stock_number(self.payload.get("percentage_change"))

        if price is None:
            price_text = "Unavailable"
        elif currency == "USD":
            price_text = f"${price:,.2f} USD"
        else:
            price_text = f"{price:,.2f} {currency}"

        price_row = QHBoxLayout()
        price_row.setContentsMargins(0, 0, 0, 0)
        price_row.setSpacing(12)

        price_label = QLabel(price_text)
        price_label.setObjectName("stockPrice")
        price_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        price_row.addWidget(price_label)

        if change is not None and percentage_change is not None:
            positive = change > 0
            negative = change < 0

            if positive:
                change_color = "#62d99b"
                change_background = "#123322"
                change_border = "#2f7d56"
                arrow = "▲"
            elif negative:
                change_color = "#ff7b7b"
                change_background = "#35191b"
                change_border = "#76363b"
                arrow = "▼"
            else:
                change_color = "#c8c8c8"
                change_background = "#252525"
                change_border = "#444444"
                arrow = "•"

            change_chip = QLabel(f"{arrow} {change:+,.2f}  ({percentage_change:+.2f}%)")
            change_chip.setAlignment(Qt.AlignCenter)
            change_chip.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            change_chip.setTextInteractionFlags(Qt.TextSelectableByMouse)
            change_chip.setStyleSheet(
                f"""
                background: {change_background};
                color: {change_color};
                border: 1px solid {change_border};
                border-radius: 8px;
                padding: 5px 9px;
                font-size: 12px;
                font-weight: 800;
            """
            )
            price_row.addWidget(change_chip)

        price_row.addStretch()
        content_layout.addLayout(price_row)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setFixedHeight(1)
        divider.setStyleSheet("background: #303030; border: none;")
        content_layout.addWidget(divider)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(8)
        grid.setColumnMinimumWidth(0, 150)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)

        change_text = "Unavailable" if change is None else f"{change:+,.2f} {currency}"
        percentage_text = (
            "Unavailable" if percentage_change is None else f"{percentage_change:+.2f}%"
        )

        details = (
            ("Daily change", change_text),
            ("Percentage change", percentage_text),
            ("Market status", status_text),
            (
                "Quote timestamp",
                str(self.payload.get("quote_timestamp") or "Unavailable"),
            ),
            ("Exchange", str(self.payload.get("exchange") or "Unavailable")),
        )

        for row_index, (field_name, value) in enumerate(details):
            field_label = QLabel(field_name)
            field_label.setObjectName("stockFieldLabel")
            field_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

            value_label = QLabel(value)
            value_label.setObjectName("stockFieldValue")
            value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            value_label.setWordWrap(True)

            grid.addWidget(field_label, row_index, 0)
            grid.addWidget(value_label, row_index, 1)

        content_layout.addLayout(grid)

        source_name = str(self.payload.get("source_name") or "Source").strip()
        source_url = str(self.payload.get("source_url") or "").strip()

        if source_url:
            safe_url = html.escape(source_url, quote=True)
            safe_name = html.escape(source_name)
            source_label = QLabel(
                f'<a href="{safe_url}" style="color:{accent}; '
                f'text-decoration:none;">Open source: {safe_name}</a>'
            )
            source_label.setObjectName("stockSourceLink")
            source_label.setOpenExternalLinks(True)
            source_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
            content_layout.addWidget(source_label)

        retrieved_at = str(self.payload.get("retrieved_at") or "Unavailable").strip()
        retrieved_label = QLabel(
            f"Retrieved {retrieved_at} · Direct market data · No LLM estimation"
        )
        retrieved_label.setObjectName("stockRetrieved")
        retrieved_label.setWordWrap(True)
        retrieved_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        content_layout.addWidget(retrieved_label)


class MarketPulseCard(QFrame):
    COLORS = {
        "up": ("#2ea043", "#0f2a1a", "#52c878", "UP"),
        "down": ("#f85149", "#351416", "#ff7b72", "DOWN"),
        "flat": ("#8b949e", "#161b22", "#30363d", "FLAT"),
        "unavailable": ("#8b949e", "#161b22", "#30363d", "N/A"),
    }

    def __init__(self, payload):
        super().__init__()
        self.payload = dict(payload or {})
        self.setObjectName("marketPulseCard")
        self.setStyleSheet(
            """
            QFrame#marketPulseCard {
                background: #0d1117;
                border: 1px solid #30363d;
                border-radius: 12px;
            }
            QLabel {
                background: transparent;
                border: none;
                color: #e6edf3;
                font-family: "Segoe UI Variable", "Segoe UI";
            }
            QLabel#marketPulseBadge {
                background: #332600;
                color: #f2cc60;
                border: 1px solid #806000;
                border-radius: 7px;
                padding: 4px 8px;
                font-size: 10px;
                font-weight: 850;
            }
            QLabel#marketPulseTitle {
                color: #f0f6fc;
                font-size: 22px;
                font-weight: 800;
            }
            QLabel#marketPulseMeta,
            QLabel#marketPulseFootnote {
                color: #8b949e;
                font-size: 11px;
            }
            QFrame#marketPulseGroup {
                background: #11161d;
                border: 1px solid #30363d;
                border-radius: 10px;
            }
            QLabel#marketPulseGroupTitle {
                color: #f2cc60;
                font-size: 12px;
                font-weight: 850;
                letter-spacing: 0.5px;
            }
            QLabel#marketPulseHeader {
                color: #8b949e;
                font-size: 10px;
                font-weight: 800;
            }
            QLabel#marketPulseName {
                color: #f0f6fc;
                font-size: 12px;
                font-weight: 700;
            }
            QLabel#marketPulseTicker {
                color: #79c0ff;
                font-size: 10px;
                font-family: "Cascadia Code", Consolas, monospace;
            }
            QLabel#marketPulseValue {
                color: #f0f6fc;
                font-size: 12px;
                font-weight: 750;
            }
            QLabel#marketPulseStatus {
                color: #c9d1d9;
                font-size: 11px;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)

        badge = QLabel("MARKET")
        badge.setObjectName("marketPulseBadge")
        badge.setAlignment(Qt.AlignCenter)
        badge.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(2)

        title = QLabel(str(self.payload.get("title") or "Global Market Pulse"))
        title.setObjectName("marketPulseTitle")

        retrieved = str(self.payload.get("retrieved_at") or "Unavailable").strip()
        source_name = str(self.payload.get("source_name") or "Market data").strip()
        meta = QLabel(f"Retrieved {retrieved} - {source_name}")
        meta.setObjectName("marketPulseMeta")
        meta.setTextInteractionFlags(Qt.TextSelectableByMouse)

        title_box.addWidget(title)
        title_box.addWidget(meta)

        header.addWidget(badge, 0, Qt.AlignTop)
        header.addLayout(title_box, 1)
        layout.addLayout(header)

        summary_row = QHBoxLayout()
        summary_row.setContentsMargins(0, 0, 0, 0)
        summary_row.setSpacing(7)
        summary = self.payload.get("summary") or {}
        for key, label in (
            ("up", "Up"),
            ("down", "Down"),
            ("flat", "Flat"),
            ("unavailable", "N/A"),
        ):
            value = int(summary.get(key) or 0)
            summary_row.addWidget(self._chip(f"{label} {value}", key))
        summary_row.addStretch(1)
        layout.addLayout(summary_row)

        groups = [group for group in (self.payload.get("groups") or []) if group]
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        for index, group in enumerate(groups):
            grid.addWidget(self._group_card(group), index // 2, index % 2)
        if groups:
            layout.addLayout(grid)

        unavailable = self.payload.get("unavailable") or []
        if unavailable:
            unavailable_label = QLabel(
                "Unavailable: " + "; ".join(str(item) for item in unavailable[:4])
            )
            unavailable_label.setObjectName("marketPulseFootnote")
            unavailable_label.setWordWrap(True)
            unavailable_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(unavailable_label)

        disclaimer = str(self.payload.get("disclaimer") or "").strip()
        if disclaimer:
            footnote = QLabel(disclaimer)
            footnote.setObjectName("marketPulseFootnote")
            footnote.setWordWrap(True)
            footnote.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(footnote)

    def _chip(self, text, direction):
        color, background, border, _label = self.COLORS.get(
            str(direction or "flat"), self.COLORS["flat"]
        )
        chip = QLabel(str(text or ""))
        chip.setAlignment(Qt.AlignCenter)
        chip.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        chip.setStyleSheet(
            f"""
            background: {background};
            color: {color};
            border: 1px solid {border};
            border-radius: 7px;
            padding: 4px 8px;
            font-size: 10px;
            font-weight: 850;
            """
        )
        return chip

    def _group_card(self, group):
        card = QFrame()
        card.setObjectName("marketPulseGroup")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(11, 10, 11, 10)
        layout.setSpacing(8)

        title = QLabel(str(group.get("name") or "Market group").upper())
        title.setObjectName("marketPulseGroupTitle")
        layout.addWidget(title)

        table = QGridLayout()
        table.setContentsMargins(0, 0, 0, 0)
        table.setHorizontalSpacing(12)
        table.setVerticalSpacing(6)
        headers = ("Indicator", "Last", "Move", "Status")
        for col, header in enumerate(headers):
            label = QLabel(header)
            label.setObjectName("marketPulseHeader")
            table.addWidget(label, 0, col)

        for row_index, row in enumerate(group.get("rows") or [], start=1):
            name_box = QVBoxLayout()
            name_box.setContentsMargins(0, 0, 0, 0)
            name_box.setSpacing(1)

            name = QLabel(str(row.get("label") or "Indicator"))
            name.setObjectName("marketPulseName")
            name.setTextInteractionFlags(Qt.TextSelectableByMouse)

            ticker = QLabel(str(row.get("ticker") or ""))
            ticker.setObjectName("marketPulseTicker")
            ticker.setTextInteractionFlags(Qt.TextSelectableByMouse)

            name_box.addWidget(name)
            name_box.addWidget(ticker)
            table.addLayout(name_box, row_index, 0)

            last = QLabel(str(row.get("last") or "n/a"))
            last.setObjectName("marketPulseValue")
            last.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            last.setTextInteractionFlags(Qt.TextSelectableByMouse)
            table.addWidget(last, row_index, 1)

            direction = str(row.get("direction") or "flat").strip().lower()
            move_text = str(row.get("change_text") or "n/a")
            table.addWidget(self._chip(move_text, direction), row_index, 2)

            status = QLabel(str(row.get("status") or "Unavailable"))
            status.setObjectName("marketPulseStatus")
            status.setWordWrap(True)
            status.setTextInteractionFlags(Qt.TextSelectableByMouse)
            table.addWidget(status, row_index, 3)

        table.setColumnStretch(0, 2)
        table.setColumnStretch(1, 1)
        table.setColumnStretch(2, 1)
        table.setColumnStretch(3, 1)
        layout.addLayout(table)
        return card


class RemoteNewsImage(QLabel):
    image_loaded = Signal(bytes)
    image_failed = Signal()

    def __init__(self, image_url):
        super().__init__()
        self.image_url = str(image_url or "").strip()
        self.setObjectName("dailyNewsImage")
        self.setAlignment(Qt.AlignCenter)
        self.setFixedSize(152, 92)
        self.setWordWrap(True)
        self.setText("IMAGE")
        self.setToolTip("Open image")
        self.setCursor(Qt.PointingHandCursor)
        self.image_loaded.connect(self._apply_image)
        self.image_failed.connect(self._show_image_link)
        QTimer.singleShot(120, self._start_loading)

    def _start_loading(self):
        if not self.image_url.lower().startswith(("http://", "https://")):
            self._show_image_link()
            return

        worker = threading.Thread(target=self._download_image, daemon=True)
        worker.start()

    def _download_image(self):
        try:
            request = Request(
                self.image_url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/149.0.0.0 Safari/537.36"
                    )
                },
            )

            with urlopen(request, timeout=3.0) as response:
                content_type = str(response.headers.get("Content-Type") or "").lower()
                data = response.read(900_000)

            if data and (
                "image/" in content_type
                or data.startswith((b"\x89PNG", b"\xff\xd8\xff", b"GIF8"))
            ):
                self.image_loaded.emit(data)
                return
        except Exception:
            pass

        self.image_failed.emit()

    def _apply_image(self, data):
        pixmap = QPixmap()

        if not pixmap.loadFromData(data):
            self._show_image_link()
            return

        scaled = pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.setPixmap(scaled)

    def _show_image_link(self):
        self.setText("IMAGE\nLINK")

    def mousePressEvent(self, event):
        if self.image_url.lower().startswith(("http://", "https://")):
            QDesktopServices.openUrl(QUrl(self.image_url))
        super().mousePressEvent(event)


class DailyNewsBriefCard(QFrame):
    def __init__(self, payload):
        super().__init__()
        self.payload = dict(payload or {})
        self.expanded = False
        self.lead_summary_label = None
        self.more_button = None
        self.setObjectName("dailyNewsBriefCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.setStyleSheet(
            """
            QFrame#dailyNewsBriefCard {
                background: #0d1117;
                border: 1px solid #30363d;
                border-radius: 12px;
            }
            QLabel {
                background: transparent;
                border: none;
                color: #e6edf3;
                font-family: "Segoe UI Variable", "Segoe UI";
            }
            QLabel#dailyNewsBadge {
                background: #0b2a44;
                color: #79c0ff;
                border: 1px solid #1f6feb;
                border-radius: 7px;
                padding: 4px 8px;
                font-size: 10px;
                font-weight: 850;
            }
            QLabel#dailyNewsTitle {
                color: #f0f6fc;
                font-size: 22px;
                font-weight: 850;
            }
            QLabel#dailyNewsMeta,
            QLabel#dailyNewsStoryMeta,
            QLabel#dailyNewsSummary {
                color: #8b949e;
                font-size: 11px;
            }
            QFrame#dailyNewsLead {
                background: #11161d;
                border: 1px solid #30363d;
                border-radius: 10px;
            }
            QLabel#dailyNewsLeadKicker {
                color: #f2cc60;
                font-size: 10px;
                font-weight: 850;
                letter-spacing: 0.6px;
            }
            QLabel#dailyNewsLeadTitle {
                color: #f0f6fc;
                font-size: 16px;
                font-weight: 850;
            }
            QLabel#dailyNewsImage {
                background: #161b22;
                color: #79c0ff;
                border: 1px solid #30363d;
                border-radius: 8px;
                font-size: 10px;
                font-weight: 850;
            }
            QLabel#dailyNewsSectionTitle {
                color: #f2cc60;
                font-size: 12px;
                font-weight: 850;
                letter-spacing: 0.5px;
            }
            QFrame#dailyNewsSection {
                background: #11161d;
                border: 1px solid #30363d;
                border-radius: 10px;
            }
            QFrame#dailyNewsStoryRow {
                background: transparent;
                border-bottom: 1px solid #21262d;
                border-radius: 0px;
            }
            QLabel#dailyNewsStoryHeadline {
                color: #f0f6fc;
                font-size: 12px;
                font-weight: 700;
            }
            QLabel#dailyNewsLink {
                color: #79c0ff;
                font-size: 11px;
                font-weight: 750;
            }
            QPushButton#dailyNewsMoreButton {
                background: #161b22;
                color: #c9d1d9;
                border: 1px solid #30363d;
                border-radius: 7px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 750;
            }
            QPushButton#dailyNewsMoreButton:hover {
                background: #21262d;
                color: #f0f6fc;
                border-color: #58a6ff;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)

        badge = QLabel("NEWS")
        badge.setObjectName("dailyNewsBadge")
        badge.setAlignment(Qt.AlignCenter)
        badge.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(2)

        title = QLabel(str(self.payload.get("title") or "Daily News Brief"))
        title.setObjectName("dailyNewsTitle")

        story_count = int(self.payload.get("story_count") or 0)
        source_count = int(self.payload.get("source_count") or 0)
        image_count = int(self.payload.get("image_count") or 0)
        meta_bits = [f"{story_count} stories", f"{source_count} source records"]
        if image_count:
            meta_bits.append(f"{image_count} image links")
        meta = QLabel(" - ".join(meta_bits))
        meta.setObjectName("dailyNewsMeta")
        meta.setTextInteractionFlags(Qt.TextSelectableByMouse)

        title_box.addWidget(title)
        title_box.addWidget(meta)
        header.addWidget(badge, 0, Qt.AlignTop)
        header.addLayout(title_box, 1)
        layout.addLayout(header)

        lead_story = self.payload.get("lead_story") or {}
        if lead_story:
            layout.addWidget(self._lead_story_card(lead_story))

        sections = [
            section for section in self.payload.get("sections") or [] if section
        ]
        if sections:
            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(10)

            for index, section in enumerate(sections):
                grid.addWidget(self._section_card(section), index // 2, index % 2)

            layout.addLayout(grid)

    def _lead_story_card(self, story):
        card = QFrame()
        card.setObjectName("dailyNewsLead")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        image_url = str(story.get("image_url") or "").strip()
        if image_url:
            layout.addWidget(RemoteNewsImage(image_url), 0, Qt.AlignTop)

        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(7)

        kicker = QLabel(str(story.get("section") or "Top Story").upper())
        kicker.setObjectName("dailyNewsLeadKicker")

        headline = QLabel(str(story.get("headline") or "News story"))
        headline.setObjectName("dailyNewsLeadTitle")
        headline.setWordWrap(True)
        headline.setTextInteractionFlags(Qt.TextSelectableByMouse)

        meta_text = self._story_meta_text(story)
        meta = QLabel(meta_text)
        meta.setObjectName("dailyNewsStoryMeta")
        meta.setWordWrap(True)
        meta.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.lead_summary_label = QLabel()
        self.lead_summary_label.setObjectName("dailyNewsSummary")
        self.lead_summary_label.setWordWrap(True)
        self.lead_summary_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        text_box.addWidget(kicker)
        text_box.addWidget(headline)
        text_box.addWidget(meta)

        summary_text = str(story.get("summary") or story.get("source_title") or "")
        if summary_text:
            text_box.addWidget(self.lead_summary_label)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(10)

        article_link = self._link_label("Open article", story.get("url"))
        if article_link:
            action_row.addWidget(article_link)

        image_link = self._link_label("Open image", image_url)
        if image_link:
            action_row.addWidget(image_link)

        if summary_text and len(summary_text) > 260:
            self.more_button = QPushButton("More")
            self.more_button.setObjectName("dailyNewsMoreButton")
            self.more_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            self.more_button.clicked.connect(self.toggle_lead_summary)
            action_row.addWidget(self.more_button)

        action_row.addStretch(1)
        text_box.addLayout(action_row)
        layout.addLayout(text_box, 1)
        self.render_lead_summary(story)
        return card

    def render_lead_summary(self, story):
        if self.lead_summary_label is None:
            return

        summary = _plain_label_text(story.get("summary") or story.get("source_title"))
        if not summary:
            self.lead_summary_label.hide()
            return

        self.lead_summary_label.show()
        if self.expanded or len(summary) <= 260:
            self.lead_summary_label.setText(summary)
            if self.more_button is not None:
                self.more_button.setText("Less")
        else:
            self.lead_summary_label.setText(summary[:260].rstrip() + " ...")
            if self.more_button is not None:
                self.more_button.setText("More")

    def sync_parent_chat_layout(self):
        sync_callback = getattr(self.window(), "sync_chat_container_height", None)

        if callable(sync_callback):
            QTimer.singleShot(0, sync_callback)

    def toggle_lead_summary(self):
        self.expanded = not self.expanded
        self.render_lead_summary(self.payload.get("lead_story") or {})
        self.adjustSize()
        self.updateGeometry()
        self.sync_parent_chat_layout()

    def _section_card(self, section):
        card = QFrame()
        card.setObjectName("dailyNewsSection")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(11, 10, 11, 8)
        layout.setSpacing(7)
        layout.setAlignment(Qt.AlignTop)

        title = QLabel(str(section.get("name") or "News").upper())
        title.setObjectName("dailyNewsSectionTitle")
        layout.addWidget(title, 0, Qt.AlignTop)

        for story in section.get("stories") or []:
            layout.addWidget(self._story_row(story), 0, Qt.AlignTop)

        return card

    def _story_row(self, story):
        row = QFrame()
        row.setObjectName("dailyNewsStoryRow")
        layout = QGridLayout(row)
        layout.setContentsMargins(0, 0, 0, 7)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(3)

        headline = QLabel(str(story.get("headline") or "News story"))
        headline.setObjectName("dailyNewsStoryHeadline")
        headline.setWordWrap(True)
        headline.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(headline, 0, 0)

        action_widget = QWidget()
        action_widget.setStyleSheet("background: transparent; border: none;")
        action_layout = QHBoxLayout(action_widget)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(6)

        details_text = _plain_label_text(story.get("summary"))
        details_label = None
        details_button = None

        if details_text:
            preview_limit = 190
            preview_text = details_text

            if len(details_text) > preview_limit:
                preview_text = details_text[:preview_limit].rstrip() + " ..."

            details_label = QLabel()
            details_label.setObjectName("dailyNewsSummary")
            details_label.setWordWrap(True)
            details_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(details_label, 2, 0, 1, 2)

            details_state = {"expanded": False}

            def render_details():
                expanded = bool(details_state["expanded"])
                details_label.setVisible(True)
                details_label.setText(details_text if expanded else preview_text)

                if details_button is not None:
                    details_button.setText("Less" if expanded else "More")

            def toggle_details():
                details_state["expanded"] = not bool(details_state["expanded"])
                render_details()
                row.adjustSize()
                row.updateGeometry()
                self.adjustSize()
                self.updateGeometry()
                self.sync_parent_chat_layout()

            if preview_text != details_text:
                details_button = QPushButton("More")
                details_button.setObjectName("dailyNewsMoreButton")
                details_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
                details_button.clicked.connect(toggle_details)
                action_layout.addWidget(details_button)

            render_details()

        link = self._link_label("Open", story.get("url"))
        if link:
            action_layout.addWidget(link)

        if action_layout.count():
            layout.addWidget(action_widget, 0, 1, Qt.AlignTop | Qt.AlignRight)

        meta = QLabel(self._story_meta_text(story))
        meta.setObjectName("dailyNewsStoryMeta")
        meta.setWordWrap(True)
        meta.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(meta, 1, 0, 1, 2)

        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 0)
        return row

    def _story_meta_text(self, story):
        bits = [
            str(story.get("publisher") or "").strip(),
            str(story.get("published_at") or "").strip(),
        ]
        return " - ".join(bit for bit in bits if bit) or "Source"

    def _link_label(self, label_text, url):
        clean_url = str(url or "").strip()
        if not clean_url.lower().startswith(("http://", "https://")):
            return None

        safe_url = html.escape(clean_url, quote=True)
        safe_label = html.escape(str(label_text or "Open").strip() or "Open")
        label = QLabel(
            f'<a href="{safe_url}" style="color:#79c0ff; text-decoration:none;">'
            f"{safe_label}</a>"
        )
        label.setObjectName("dailyNewsLink")
        label.setOpenExternalLinks(True)
        label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        return label


class WebArticleCard(QWidget):
    def __init__(self, article):
        super().__init__()
        self.setObjectName("webArticleCard")
        self.article = article
        self.expanded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        title = QLabel(article.get("title", "Untitled"))
        title.setObjectName("webArticleTitle")
        title.setWordWrap(True)
        layout.addWidget(title)

        image_file = article.get("image_file", "")

        if image_file and os.path.exists(image_file):
            layout.addWidget(ImagePreview(image_file))

        self.content = clean_article_preview(article.get("content", ""))
        self.body = QLabel()
        self.body.setObjectName("webArticleBody")
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.body)

        self.more_button = QPushButton("More")
        self.more_button.setObjectName("codeCopyButton")
        self.more_button.setFixedWidth(80)
        self.more_button.clicked.connect(self.toggle_article)

        if len(self.content) > 350:
            layout.addWidget(self.more_button)

        url = article.get("url", "")

        if url:
            source = QLabel(f'<a href="{url}">Source</a>')
            source.setObjectName("webArticleSource")
            source.setOpenExternalLinks(True)
            layout.addWidget(source)

        self.render_article_text()

    def render_article_text(self):
        if not self.content:
            self.body.hide()
            return

        self.body.show()

        if self.expanded:
            self.body.setText(self.content)
            self.more_button.setText("Less")
        else:
            preview = self.content[:350].strip()

            if len(self.content) > 350:
                preview += " ..."

            self.body.setText(preview)
            self.more_button.setText("More")

    def toggle_article(self):
        self.expanded = not self.expanded
        self.render_article_text()
        self.adjustSize()
        self.updateGeometry()


class CodeBlockWidget(QWidget):
    run_requested = Signal(str)

    def __init__(self, language, code):
        super().__init__()
        self.language = str(language or "code").strip().lower()
        self.code = code.rstrip()
        self.is_python_block = self.language in {"python", "py", "python3", "pyw"}
        self.setObjectName("codeBlockWidget")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 16)
        layout.setSpacing(0)

        header = QWidget()
        header.setObjectName("codeBlockHeader")

        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 7, 10, 7)
        header_layout.setSpacing(8)

        language_label = QLabel((language or "code").capitalize())
        language_label.setObjectName("codeLanguageLabel")

        self.run_button = QPushButton("Run")
        self.run_button.setObjectName("codeRunButton")
        self.run_button.setFixedWidth(54)
        self.run_button.setToolTip("Run this Python code block")
        self.run_button.clicked.connect(self.run_code)
        self.run_button.setVisible(self.is_python_block)

        self.copy_button = QPushButton("Copy code")
        self.copy_button.setObjectName("codeCopyButton")
        self.copy_button.setFixedWidth(92)
        self.copy_button.clicked.connect(self.copy_code)

        header_layout.addWidget(language_label)
        header_layout.addStretch()
        header_layout.addWidget(self.run_button)
        header_layout.addWidget(self.copy_button)
        footer = QWidget()
        footer.setObjectName("codeBlockHeader")

        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(14, 7, 10, 7)
        footer_layout.setSpacing(8)

        footer_language_label = QLabel((language or "code").capitalize())
        footer_language_label.setObjectName("codeLanguageLabel")
        line_count = len(self.code.splitlines())

        footer_line_count = QLabel(f"{line_count} lines")
        footer_line_count.setObjectName("codeLanguageLabel")
        footer_run_button = QPushButton("Run")
        footer_run_button.setObjectName("codeRunButton")
        footer_run_button.setFixedWidth(54)
        footer_run_button.setToolTip("Run this Python code block")
        footer_run_button.clicked.connect(self.run_code)
        footer_run_button.setVisible(self.is_python_block)

        footer_copy_button = QPushButton("Copy code")
        footer_copy_button.setObjectName("codeCopyButton")
        footer_copy_button.setFixedWidth(92)
        footer_copy_button.clicked.connect(self.copy_code)

        self.setAttribute(Qt.WA_Hover, True)
        self._action_buttons = [
            self.run_button,
            self.copy_button,
            footer_run_button,
            footer_copy_button,
        ]
        self._action_button_animations = []

        for action_button in self._action_buttons:
            action_effect = QGraphicsOpacityEffect(action_button)
            action_effect.setOpacity(0.46)
            action_button.setGraphicsEffect(action_effect)

        footer_layout.addWidget(footer_language_label)
        footer_layout.addSpacing(12)
        footer_layout.addWidget(footer_line_count)
        footer_layout.addStretch()
        footer_layout.addWidget(footer_run_button)
        footer_layout.addWidget(footer_copy_button)
        code_view = QTextBrowser()
        code_view.setObjectName("codeView")
        code_view.setReadOnly(True)
        code_view.setOpenExternalLinks(False)
        code_view.setFrameShape(QFrame.NoFrame)
        code_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        code_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        highlighted_html = highlight_code(language or "text", self.code)

        code_view.setHtml(
            f"""
        <html>
            <head>
                <style>
                    body {{
                        background-color: #0d1117;
                        color: #e6edf3;
                        font-family: "Cascadia Code", "JetBrains Mono", Consolas, monospace;
                        font-size: 13px;
                        line-height: 1.35;
                        margin: 0;
                        padding: 0;
                    }}

                    pre {{
                        margin: 0;
                        white-space: pre-wrap;
                    }}
                </style>
            </head>
            <body>
                <pre>{highlighted_html}</pre>
            </body>
        </html>
        """
        )

        # Do not rely on QTextDocument's early layout height here. For terminal-style
        # ASTRO outputs, Qt can overestimate the document height before the widget has
        # its final width, producing a large blank area under SEEING/TARGETS results.
        line_count = max(1, len(self.code.splitlines()))
        estimated_height = int(line_count * 18 + 30)
        height = max(82, min(estimated_height, 900))

        if estimated_height > height:
            code_view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        else:
            code_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        code_view.setMinimumHeight(height)
        code_view.setMaximumHeight(height)

        layout.addWidget(header)
        layout.addWidget(code_view)
        layout.addWidget(footer)

    def _animate_action_buttons(self, target_opacity, duration=150):
        self._action_button_animations = []

        for action_button in getattr(self, "_action_buttons", []):
            try:
                effect = action_button.graphicsEffect()

                if not isinstance(effect, QGraphicsOpacityEffect):
                    effect = QGraphicsOpacityEffect(action_button)
                    action_button.setGraphicsEffect(effect)

                animation = QPropertyAnimation(effect, b"opacity", self)
                animation.setDuration(duration)
                animation.setStartValue(effect.opacity())
                animation.setEndValue(float(target_opacity))
                animation.start()
                self._action_button_animations.append(animation)
            except RuntimeError:
                continue

    def enterEvent(self, event):
        self._animate_action_buttons(1.0, duration=120)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate_action_buttons(0.46, duration=180)
        super().leaveEvent(event)

    def run_code(self):
        if self.is_python_block and self.code.strip():
            self.run_requested.emit(self.code)

    def copy_code(self):
        QApplication.clipboard().setText(self.code)

        button = self.sender()

        if isinstance(button, QPushButton):
            button.setText("Copied")

            QTimer.singleShot(
                2000, lambda current_button=button: current_button.setText("Copy code")
            )


class AutoHeightRichText(QTextBrowser):
    link_activated = Signal(str)

    """Rich-text view that follows its QTextDocument without stale blank space.

    History restoration creates many rich-text widgets before the outer
    QScrollArea has its final width.  Measuring at that temporary narrow width
    can lock in an oversized height (or occasionally a near-zero height), which
    then appears as a large blank gap while scrolling.  Height measurement is
    therefore deferred until a useful width exists and repeated after the Qt
    layout has settled.
    """

    def __init__(self):
        super().__init__()
        self._height_update_pending = False
        self._updating_height = False
        self._last_measured_width = -1
        self._qt_destroyed = False

        self.destroyed.connect(self._mark_qt_destroyed)

        self.setObjectName("messageText")
        self.setReadOnly(True)
        self.setOpenExternalLinks(False)
        self.setOpenLinks(False)
        self.anchorClicked.connect(self._emit_link_activated)
        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(24)
        self.setContentsMargins(0, 0, 0, 0)
        self.setViewportMargins(0, 0, 0, 0)
        self.document().setDocumentMargin(0)
        self.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse
        )

        self.document().documentLayout().documentSizeChanged.connect(
            self._schedule_height_update
        )

    def _emit_link_activated(self, url):
        try:
            self.link_activated.emit(url.toString())
        except Exception as exc:
            log_exception("AutoHeightRichText._emit_link_activated", exc)

    def _mark_qt_destroyed(self, *_):
        self._qt_destroyed = True
        self._height_update_pending = False
        self._updating_height = False

    def _is_qt_alive(self):
        if getattr(self, "_qt_destroyed", False):
            return False

        try:
            self.objectName()
            return True
        except RuntimeError:
            self._qt_destroyed = True
            self._height_update_pending = False
            self._updating_height = False
            return False

    def _safe_single_shot(self, delay_ms, callback):
        def guarded_callback():
            if self._is_qt_alive():
                callback()

        QTimer.singleShot(delay_ms, guarded_callback)

    def setHtml(self, html_text):
        if not self._is_qt_alive():
            return

        try:
            super().setHtml(html_text)
        except RuntimeError:
            self._mark_qt_destroyed()
            return

        self._schedule_height_update()

        # The first pass can happen before QScrollArea assigns the final width.
        self._safe_single_shot(40, self._schedule_height_update)
        self._safe_single_shot(140, self._schedule_height_update)

    def resizeEvent(self, event):
        if not self._is_qt_alive():
            return

        old_width = event.oldSize().width()
        new_width = event.size().width()
        super().resizeEvent(event)

        if old_width != new_width:
            self._schedule_height_update()
            self._safe_single_shot(30, self._schedule_height_update)

    def wheelEvent(self, event):
        # Let the outer chat scroll area handle wheel scrolling.
        event.ignore()

    def _schedule_height_update(self, *_):
        if not self._is_qt_alive():
            return

        if self._height_update_pending:
            return

        self._height_update_pending = True
        self._safe_single_shot(0, self._update_document_height)

    def _update_document_height(self):
        if not self._is_qt_alive():
            return

        self._height_update_pending = False

        if self._updating_height:
            self._safe_single_shot(0, self._schedule_height_update)
            return

        self._updating_height = True

        try:
            viewport = self.viewport()
            if viewport is None:
                return

            available_width = int(viewport.width())

            # Do not calculate against the tiny provisional width used while a
            # restored message is still being inserted into the chat layout.
            if available_width < 120:
                self._safe_single_shot(35, self._schedule_height_update)
                return

            document = self.document()

            if abs(document.textWidth() - available_width) > 1:
                document.setTextWidth(available_width)

            rendered_height = int(
                document.documentLayout().documentSize().height() + 0.999
            )

            frame_extra = self.frameWidth() * 2
            exact_height = max(24, rendered_height + frame_extra + 2)

            if self.height() != exact_height:
                self.setFixedHeight(exact_height)
                self.updateGeometry()

                parent = self.parentWidget()
                if parent is not None:
                    parent.updateGeometry()

            self._last_measured_width = available_width

        except RuntimeError:
            self._mark_qt_destroyed()
            return
        finally:
            self._updating_height = False

        # A scrollbar appearing can change the available width by a few pixels
        # during the same event cycle.  Re-measure once more when that happens.
        if not self._is_qt_alive():
            return

        try:
            if int(self.viewport().width()) != self._last_measured_width:
                self._safe_single_shot(0, self._schedule_height_update)
        except RuntimeError:
            self._mark_qt_destroyed()


class TypingIndicatorWidget(QWidget):
    """Compact animated three-dot bubble shown before answer text arrives."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._phase = 0
        self.setObjectName("typingIndicator")
        self.setFixedSize(66, 38)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAccessibleName("AI is thinking")

        self._timer = QTimer(self)
        self._timer.setInterval(260)
        self._timer.timeout.connect(self._advance_phase)
        self._timer.start()

    def _advance_phase(self):
        self._phase = (self._phase + 1) % 3
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        bubble_rect = self.rect().adjusted(0, 0, -1, -1)
        painter.setPen(QColor("#34383d"))
        painter.setBrush(QColor("#1d1f22"))
        painter.drawRoundedRect(bubble_rect, 19, 19)

        dot_colors = (
            QColor(199, 202, 206, 105),
            QColor(199, 202, 206, 150),
            QColor(218, 220, 223, 230),
        )

        dot_radius = 3
        gap = 5
        total_width = dot_radius * 2 * 3 + gap * 2
        start_x = (self.width() - total_width) // 2
        center_y = self.height() // 2

        painter.setPen(Qt.NoPen)

        for index in range(3):
            distance = (index - self._phase) % 3
            color = dot_colors[2 if distance == 0 else 1 if distance == 1 else 0]
            painter.setBrush(color)
            x = start_x + index * (dot_radius * 2 + gap)
            painter.drawEllipse(
                x, center_y - dot_radius, dot_radius * 2, dot_radius * 2
            )

        painter.end()


class MessageWidget(QWidget):
    delete_requested = Signal(str, object)
    run_python_requested = Signal(str)
    astro_lookup_requested = Signal(str)
    document_action_requested = Signal(str, str)

    def __init__(
        self,
        role,
        text="",
        files=None,
        streaming=False,
        web_articles=None,
        news_sources=None,
        message_id="",
        response_time=None,
        source_tags=None,
        content_blocks=None,
    ):
        super().__init__()
        self.role = role
        self.text = text
        self.files = files or []
        self.web_articles = web_articles or []
        self.news_sources = news_sources or {}
        self.source_tags = normalize_response_source_tags(source_tags)
        self.explicit_content_blocks = coerce_blocks(content_blocks)
        self.content_blocks: tuple[ContentBlock, ...] = ()
        self.structured_message = ChatMessage(
            role=(
                "user"
                if role in ["You", ":ME:"]
                else "news" if news_sources else "assistant"
            ),
            blocks=self.explicit_content_blocks,
            message_id=str(message_id or ""),
        )
        if not self.source_tags and self.role not in ["You", ":ME:"]:
            self.source_tags = infer_response_source_tags(
                text=self.text,
                files=self.files,
                web_articles=self.web_articles,
                news_sources=self.news_sources,
            )
        self.streaming = streaming
        self.message_id = str(message_id or "")

        try:
            self.response_time = (
                float(response_time) if response_time is not None else None
            )
        except (TypeError, ValueError):
            self.response_time = None

        self.reply_timer_state = (
            "complete" if self.response_time is not None else "idle"
        )
        self.reply_timer_footer = None
        self.reply_timer_label = None
        self.news_brief_meta_label = None
        self.is_user_message = self.role in ["You", ":ME:"]

        # A source dictionary alone does not make a response a news briefing.
        # Image search results also include source metadata.  Current news
        # records use NEWS_xxxx identifiers; the title check preserves the
        # appearance of older saved daily briefs that used publisher keys.
        has_news_source_ids = any(
            re.fullmatch(r"NEWS_\d+", str(source_id or "").strip().upper())
            for source_id in self.news_sources
        )
        has_legacy_news_title = bool(
            re.search(r"(?im)^\s*#\s*Daily News Brief\s*$", str(self.text or ""))
        )
        self.is_news_message = not self.is_user_message and (
            has_news_source_ids or has_legacy_news_title
        )
        self._message_menu_open = False
        self.setObjectName("messageWidget")
        self.setAttribute(Qt.WA_Hover, True)

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(4)

        self.role_label = None

        self.message_row = QHBoxLayout()
        self.message_row.setContentsMargins(0, 2, 0, 2)
        self.message_row.setSpacing(10)

        # Compact identity badges replace the developer-style ">" and "#"
        # markers while keeping user and assistant messages easy to scan.
        self.message_badge = QLabel(
            "YOU" if self.is_user_message else "NEWS" if self.is_news_message else "AI"
        )
        self.message_badge.setObjectName("messageRoleBadge")
        self.message_badge.setProperty(
            "roleType",
            (
                "user"
                if self.is_user_message
                else "news" if self.is_news_message else "assistant"
            ),
        )
        self.message_badge.setAlignment(Qt.AlignCenter)
        self.message_badge.setFixedSize(
            44 if self.is_news_message else 36 if self.is_user_message else 28, 20
        )
        self.message_badge.setToolTip(
            "Your message"
            if self.is_user_message
            else "Daily news briefing" if self.is_news_message else "AI response"
        )

        self.content_container = QWidget()
        self.content_container.setObjectName("messageContentContainer")
        self.content_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._apply_content_width("")

        self.response_layout = QVBoxLayout(self.content_container)
        self.response_layout.setContentsMargins(12, 10, 12, 10)
        self.response_layout.setSpacing(7)

        initial_kind = (
            "news"
            if self.is_news_message
            else "user" if self.is_user_message else "assistant"
        )
        self._base_content_kind = initial_kind
        self._typing_mode = False
        self.typing_indicator = None
        self._set_content_kind(initial_kind)

        # Keep a permanent narrow slot at the right so revealing the hover menu
        # never shifts or reflows the message content.
        self.options_slot = QWidget()
        self.options_slot.setObjectName("messageOptionsSlot")
        self.options_slot.setFixedSize(30, 26)

        options_layout = QHBoxLayout(self.options_slot)
        options_layout.setContentsMargins(0, 0, 0, 0)
        options_layout.setSpacing(0)

        self.options_button = QPushButton("⋮")
        self.options_button.setObjectName("messageOptionsButton")
        self.options_button.setFixedSize(28, 26)
        self.options_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.options_button.setFocusPolicy(Qt.NoFocus)
        self.options_button.setAutoDefault(False)
        self.options_button.setDefault(False)
        self.options_button.setToolTip("Message options")
        self.options_button.setAccessibleName("Message options")
        self.options_button.clicked.connect(self.show_message_menu)
        self.options_button.hide()
        options_layout.addWidget(self.options_button)

        self.message_row.addWidget(self.message_badge, 0, Qt.AlignTop)
        self.message_row.addWidget(self.content_container, 1)
        self.message_row.addWidget(self.options_slot, 0, Qt.AlignTop)
        self.layout.addLayout(self.message_row)

        self.stream_view = None
        self.set_text(text)

    def enterEvent(self, event):
        self.options_button.show()
        self.options_button.raise_()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._message_menu_open:
            self.options_button.hide()

        super().leaveEvent(event)

    def copy_message_text(self):
        raw_text = str(self.text or "")

        if self.is_user_message:
            copy_text = raw_text
        else:
            _thoughts, answer = self.split_thoughts(raw_text)
            quote_payload = parse_stock_quote_payload(answer)
            pulse_payload = parse_market_pulse_payload(answer)

            if pulse_payload:
                copy_text = market_pulse_plain_text(pulse_payload)
            elif quote_payload:
                copy_text = stock_quote_plain_text(quote_payload)
            else:
                copy_text = answer or raw_text

        QApplication.clipboard().setText(copy_text.strip())

    def show_message_menu(self):
        menu = QMenu(self)
        menu.setObjectName("messageOptionsMenu")
        menu.setStyleSheet(
            """
            QMenu {
                background-color: #181818;
                color: #e8e8e8;
                border: 1px solid #343434;
                border-radius: 8px;
                padding: 5px;
            }
            QMenu::item {
                padding: 7px 28px 7px 10px;
                border-radius: 5px;
            }
            QMenu::item:selected {
                background-color: #2a2a2a;
                color: #ffffff;
            }
            QMenu::separator {
                height: 1px;
                background: #343434;
                margin: 4px 6px;
            }
        """
        )

        copy_action = QAction("Copy message", menu)
        delete_action = QAction("Delete message", menu)

        menu.addAction(copy_action)
        menu.addSeparator()
        menu.addAction(delete_action)

        popup_position = self.options_button.mapToGlobal(
            self.options_button.rect().bottomRight()
        )
        popup_position.setX(popup_position.x() - menu.sizeHint().width())

        self._message_menu_open = True

        try:
            selected_action = menu.exec(popup_position)
        finally:
            self._message_menu_open = False

            if not self.underMouse():
                self.options_button.hide()

        if selected_action == copy_action:
            self.copy_message_text()
        elif selected_action == delete_action:
            self.delete_requested.emit(self.message_id, self)

    def _set_content_kind(self, kind):
        clean_kind = str(kind or "assistant")
        self.content_container.setProperty("messageKind", clean_kind)

        if clean_kind in {"stock", "typing"}:
            self.response_layout.setContentsMargins(0, 0, 0, 0)
        else:
            self.response_layout.setContentsMargins(12, 10, 12, 10)

        style = self.content_container.style()
        style.unpolish(self.content_container)
        style.polish(self.content_container)
        self.content_container.update()

    def _content_is_wide(self, text="", blocks=None):
        if self.is_news_message or self.web_articles or self.files:
            return True

        block_items = list(blocks or []) + list(self.explicit_content_blocks or [])
        if any(
            isinstance(
                block,
                (
                    CodeBlock,
                    ImageBlock,
                    VideoBlock,
                    WebArticleBlock,
                    TableBlock,
                    ToolResultBlock,
                    DailyNewsBriefBlock,
                    StockQuoteBlock,
                    MarketPulseBlock,
                ),
            )
            for block in block_items
        ):
            return True

        plain_text = str(text or "")
        return "```" in plain_text or "\n|" in plain_text

    def _preferred_content_width(self, text="", blocks=None):
        if self._content_is_wide(text, blocks):
            return 1160 if not self.is_user_message else 980

        plain_text = re.sub(r"<[^>]+>", " ", str(text or ""))
        plain_text = re.sub(r"\s+", " ", plain_text).strip()
        longest_line = max(
            [len(line.strip()) for line in str(text or "").splitlines()] or [0]
        )
        visible_chars = max(len(plain_text), longest_line)

        minimum = 300 if self.is_user_message else 420
        maximum = 760 if self.is_user_message else 900
        estimated = int(min(maximum, max(minimum, longest_line * 8 + 112)))

        if visible_chars > 260:
            estimated = max(estimated, 620 if self.is_user_message else 700)
        if visible_chars > 700:
            estimated = max(estimated, maximum)

        return estimated

    def _apply_content_width(self, text="", blocks=None):
        width = self._preferred_content_width(text, blocks)
        self.content_container.setMinimumWidth(min(width, 280))
        self.content_container.setMaximumWidth(width)

    def _fade_in_child_widget(self, target_widget, duration=160, start_opacity=0.0):
        try:
            effect = QGraphicsOpacityEffect(target_widget)
            effect.setOpacity(float(start_opacity))
            target_widget.setGraphicsEffect(effect)

            animation = QPropertyAnimation(effect, b"opacity", target_widget)
            animation.setDuration(int(duration))
            animation.setStartValue(float(start_opacity))
            animation.setEndValue(1.0)

            def finish_fade(current_widget=target_widget):
                try:
                    current_widget.setGraphicsEffect(None)
                except RuntimeError:
                    pass

            animation.finished.connect(finish_fade)
            animation.start()
            target_widget._fade_in_animation = animation
        except RuntimeError:
            pass

    def _add_source_header(self):
        add_source_header_widget(self)

    def _add_news_header(self):
        if not self.is_news_message:
            return

        header = QWidget()
        header.setObjectName("newsBriefHeader")

        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 8)
        header_layout.setSpacing(8)

        title = QLabel("DAILY NEWS BRIEF")
        title.setObjectName("newsBriefTitle")

        source_count = len(self.news_sources)
        source_text = (
            f"{source_count} source records" if source_count != 1 else "1 source record"
        )
        meta = QLabel(source_text)
        meta.setObjectName("newsBriefMeta")

        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(meta)
        self.news_brief_meta_label = meta
        self.response_layout.addWidget(header)

    def refresh_news_source_meta(self):
        if not self.is_news_message or self.news_brief_meta_label is None:
            return

        source_count = len(self.news_sources or {})
        source_text = (
            f"{source_count} source records" if source_count != 1 else "1 source record"
        )
        self.news_brief_meta_label.setText(source_text)

    def _reply_timer_text(self):
        if self.response_time is None:
            return ""

        elapsed = max(0.0, float(self.response_time))

        if self.reply_timer_state == "stopped":
            return f"⏱ Stopped after {elapsed:.2f}s"

        if self.reply_timer_state == "failed":
            return f"⏱ Failed after {elapsed:.2f}s"

        if self.reply_timer_state == "complete":
            return f"⏱ Reply assembled in {elapsed:.2f}s"

        return f"⏱ Assembling reply • {elapsed:.2f}s"

    def _ensure_reply_timer_footer(self):
        if self.is_user_message or self.response_time is None:
            return

        footer = self.reply_timer_footer

        if footer is None:
            footer = QWidget()
            footer.setObjectName("replyTimerFooter")

            footer_layout = QHBoxLayout(footer)
            footer_layout.setContentsMargins(0, 3, 0, 0)
            footer_layout.setSpacing(0)

            timer_label = QLabel()
            timer_label.setObjectName("replyTimerLabel")
            timer_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            timer_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            timer_label.setMinimumWidth(0)
            timer_label.setFixedHeight(20)

            footer_layout.addStretch()
            footer_layout.addWidget(timer_label)

            self.reply_timer_footer = footer
            self.reply_timer_label = timer_label
            self.response_layout.addWidget(footer)
        else:
            footer_index = self.response_layout.indexOf(footer)
            last_index = self.response_layout.count() - 1

            if footer_index >= 0 and footer_index != last_index:
                self.response_layout.removeWidget(footer)
                self.response_layout.addWidget(footer)

        if self.reply_timer_label is not None:
            self.reply_timer_label.setText(self._reply_timer_text())

    def set_reply_elapsed(self, elapsed, finished=False, stopped=False, failed=False):
        if self.is_user_message:
            return

        try:
            self.response_time = max(0.0, float(elapsed))
        except (TypeError, ValueError):
            return

        if failed:
            self.reply_timer_state = "failed"
        elif stopped:
            self.reply_timer_state = "stopped"
        elif finished:
            self.reply_timer_state = "complete"
        else:
            self.reply_timer_state = "running"

        # Keep the initial three-dot bubble compact. The elapsed footer appears
        # as soon as answer text starts streaming or the request finishes.
        if self._typing_mode and not (finished or stopped or failed):
            return

        self._ensure_reply_timer_footer()

    def set_message_id(self, message_id):
        self.message_id = str(message_id or "")

    def split_thoughts(self, text):
        m = re.search(
            r"<\|channel\|>thought\s*(.*?)\s*<\|channel\|>", text, flags=re.DOTALL
        )

        if m:
            thoughts = m.group(1).strip()
            answer = text.replace(m.group(0), "").strip()
            return thoughts, answer

        m = re.search(r"<think>(.*?)</think>", text, flags=re.DOTALL)

        if m:
            thoughts = m.group(1).strip()
            answer = text.replace(m.group(0), "").strip()
            return thoughts, answer

        m = re.search(r"<analysis>(.*?)</analysis>", text, flags=re.DOTALL)

        if m:
            thoughts = m.group(1).strip()
            answer = text.replace(m.group(0), "").strip()
            return thoughts, answer

        m = re.search(r"<think>(.*)", text, flags=re.DOTALL)

        if m:
            thoughts = m.group(1).strip()
            answer = text[: m.start()].strip()
            return thoughts, answer

        m = re.search(r"<analysis>(.*)", text, flags=re.DOTALL)

        if m:
            thoughts = m.group(1).strip()
            answer = text[: m.start()].strip()
            return thoughts, answer

        return "", text

    def set_stream_text(self, text):
        self.text = text
        thoughts, answer = self.split_thoughts(text)

        # Models can stream hidden reasoning for several seconds before the
        # first visible answer token. Keep the ChatGPT-style bubble visible
        # throughout that phase instead of rendering an empty message card.
        if not answer.strip():
            if not self.is_user_message and not self._typing_mode:
                self._enter_typing_mode()
            return

        if self._typing_mode:
            self._leave_typing_mode()

        if self.stream_view is None or isinstance(self.stream_view, QTextBrowser):
            if self.stream_view is not None:
                self.response_layout.removeWidget(self.stream_view)
                self.stream_view.deleteLater()

            self.stream_view = QLabel()
            self.stream_view.setObjectName("messageText")
            self.stream_view.setProperty(
                "messageMode",
                (
                    "news"
                    if self.is_news_message
                    else "user" if self.is_user_message else "assistant"
                ),
            )
            self.stream_view.setWordWrap(True)
            self.stream_view.setTextFormat(Qt.PlainText)
            self.stream_view.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.stream_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
            self.response_layout.addWidget(self.stream_view)

        if self.response_time is not None:
            self._ensure_reply_timer_footer()

        if answer == getattr(self, "last_stream_answer", ""):
            return

        self.last_stream_answer = answer

        has_local_image = any(
            str(file_path).lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
            and os.path.exists(file_path)
            for file_path in self.files
        )
        display_answer = sanitize_markdown_images(
            answer, has_local_image=has_local_image
        )

        if self.is_news_message:
            display_answer = normalize_news_brief_markdown(display_answer)
        elif not self.is_user_message:
            display_answer = normalize_assistant_link_markup(display_answer)
            display_answer = normalize_compacted_markdown(display_answer)

        # Streaming uses a fast QLabel in plain-text mode for performance, so
        # clean common LaTeX markup here too instead of waiting for final rich
        # Markdown rendering. Do not run this on Daily News because NEWS_0001
        # citation IDs resemble LaTeX subscripts and must remain exact.
        if not self.is_news_message:
            display_answer = clean_latex_plain_text(display_answer)

        self._apply_content_width(display_answer)
        self.stream_view.setText(display_answer)

        width = self.stream_view.width()

        if width < 100:
            width = self.content_container.width()

        if width < 100:
            width = self.width()

        if width < 100:
            width = 800

        height = self.stream_view.heightForWidth(width)

        if height < 40:
            height = 40

        self.stream_view.setMinimumHeight(height)
        self.stream_view.setMaximumHeight(height)

        self.stream_view.updateGeometry()
        self.content_container.updateGeometry()
        self.updateGeometry()

    def inject_news_links(self, rendered_html):
        """Render news citation IDs as links to their exact RSS articles.

        Current messages store ``{SourceID: {name, url}}``.  Older history may
        still contain ``{publisher: url}``, which is supported as a fallback.
        Both square-bracket and parenthesized citation groups are recognized.
        """
        citation_records = {}
        legacy_records = {}
        publisher_occurrences = {}

        for source_key, source_value in (self.news_sources or {}).items():
            key = html.unescape(str(source_key or "").strip())

            if isinstance(source_value, dict):
                source_name = html.unescape(
                    str(source_value.get("name", "") or "").strip()
                )
                source_url = html.unescape(
                    str(source_value.get("url", "") or "").strip()
                )

                if key and source_name and source_url:
                    citation_records[key] = {"name": source_name, "url": source_url}
                    publisher_occurrences.setdefault(source_name, []).append(source_url)

            else:
                source_url = html.unescape(str(source_value or "").strip())

                if key and source_url:
                    legacy_records[key] = source_url
                    publisher_occurrences.setdefault(key, []).append(source_url)

        # Publisher-name fallback is safe only when that publisher occurs once.
        # With repeated publishers, only SourceID can identify the exact story.
        unique_publishers = {
            publisher: urls[0]
            for publisher, urls in publisher_occurrences.items()
            if len(set(urls)) == 1
        }

        def link_for_token(token):
            clean_token = html.unescape(str(token or "").strip())
            record = citation_records.get(clean_token)

            if record:
                safe_name = html.escape(record["name"])
                safe_url = html.escape(record["url"], quote=True)
                return f'<a href="{safe_url}">{safe_name}</a>'

            legacy_url = legacy_records.get(clean_token)

            if legacy_url:
                safe_name = html.escape(clean_token)
                safe_url = html.escape(legacy_url, quote=True)
                return f'<a href="{safe_url}">{safe_name}</a>'

            unique_url = unique_publishers.get(clean_token)

            if unique_url:
                safe_name = html.escape(clean_token)
                safe_url = html.escape(unique_url, quote=True)
                return f'<a href="{safe_url}">{safe_name}</a>'

            return None

        def replace_citation_group(match):
            opening = match.group("opening")
            closing = match.group("closing")

            if (opening, closing) not in (("[", "]"), ("(", ")")):
                return match.group(0)

            group_text = match.group("body")
            parts = [part.strip() for part in group_text.split(",")]

            if not parts:
                return match.group(0)

            linked_parts = []
            matched_any = False

            for part in parts:
                linked = link_for_token(part)

                if linked:
                    linked_parts.append(linked)
                    matched_any = True
                else:
                    # The text has already been escaped by markdown rendering.
                    linked_parts.append(part)

            if not matched_any:
                return match.group(0)

            return opening + ", ".join(linked_parts) + closing

        rendered_html = re.sub(
            r"(?P<opening>[\[(])(?P<body>[^()\[\]]+)(?P<closing>[\])])",
            replace_citation_group,
            rendered_html,
        )

        # Also support a bare SourceID if the model forgets the brackets.
        for source_id, record in sorted(
            citation_records.items(), key=lambda item: len(item[0]), reverse=True
        ):
            safe_name = html.escape(record["name"])
            safe_url = html.escape(record["url"], quote=True)
            link_html = f'<a href="{safe_url}">{safe_name}</a>'

            rendered_html = re.sub(
                rf"(?<![A-Za-z0-9_]){re.escape(html.escape(source_id))}(?![A-Za-z0-9_])",
                link_html,
                rendered_html,
            )

        # Backward-compatible handling for old messages that cited a single
        # publisher after punctuation instead of using brackets.
        for source_name, source_url in sorted(
            unique_publishers.items(), key=lambda item: len(item[0]), reverse=True
        ):
            safe_name = html.escape(source_name)
            safe_url = html.escape(source_url, quote=True)
            link_html = f'<a href="{safe_url}">{safe_name}</a>'

            rendered_html = rendered_html.replace(f" - {safe_name}", f" - {link_html}")
            rendered_html = rendered_html.replace(f". {safe_name}", f". {link_html}")

        return rendered_html

    def _handle_text_link_activated(self, url_text):
        url_text = str(url_text or "").strip()
        if not url_text:
            return

        parsed = urlparse(url_text)
        scheme = parsed.scheme.lower()

        if scheme == "fzastro" and parsed.netloc.lower() == "lookup":
            values = parse_qs(parsed.query)
            target = unquote((values.get("object") or [""])[0]).strip()
            if target:
                self.astro_lookup_requested.emit(target)
            return

        if scheme == "fzastro" and parsed.netloc.lower() == "document":
            values = parse_qs(parsed.query)
            action = unquote((values.get("action") or [""])[0]).strip().lower()
            document_id = unquote((values.get("id") or [""])[0]).strip()
            if action and document_id:
                self.document_action_requested.emit(action, document_id)
            return

        if scheme not in {"http", "https", "mailto"}:
            return

        QDesktopServices.openUrl(QUrl(url_text))

    def _clear_response_layout(self):
        while self.response_layout.count():
            item = self.response_layout.takeAt(0)
            widget = item.widget()

            if widget:
                widget.deleteLater()

        self.stream_view = None
        self.reply_timer_footer = None
        self.reply_timer_label = None
        self.news_brief_meta_label = None

    def _add_code_block_widget(self, language, content):
        code_widget = CodeBlockWidget(language, content)
        code_widget.run_requested.connect(self.run_python_requested.emit)
        self.response_layout.addWidget(code_widget)
        return code_widget

    def _build_static_content_blocks(self):
        blocks: list[ContentBlock] = []

        if self.source_tags:
            blocks.append(SourceHeaderBlock(tuple(self.source_tags)))

        if self.is_news_message:
            blocks.append(NewsHeaderBlock(len(self.news_sources or {})))

        for file_path in self.files:
            file_text = str(file_path or "")
            lower_path = file_text.lower()

            if lower_path.endswith((".jpg", ".jpeg", ".png", ".webp")):
                blocks.append(ImageBlock(file_text))
            elif lower_path.endswith(".py"):
                try:
                    with open(file_text, "r", encoding="utf-8", errors="replace") as f:
                        blocks.append(
                            CodeBlock(
                                f.read(), language="python", source_path=file_text
                            )
                        )
                except Exception as e:
                    log_exception("MessageWidget._build_static_content_blocks", e)
                    blocks.append(
                        FileAttachmentBlock(
                            file_text,
                            label=f"{Path(file_text).name} — could not read: {e}",
                        )
                    )
            else:
                blocks.append(FileAttachmentBlock(file_text))

        for article in self.web_articles:
            blocks.append(WebArticleBlock(article))

        return blocks

    def _build_answer_content_blocks(self, answer):
        blocks: list[ContentBlock] = []

        for block_type, language, content in parse_markdown_blocks(answer):
            if block_type == "text" and content.strip():
                blocks.append(TextBlock(content, format="markdown"))
            elif block_type == "code":
                blocks.append(CodeBlock(content, language=language or "code"))

        return blocks

    def _render_content_blocks(self, blocks):
        self.content_blocks = coerce_blocks(blocks)
        self.structured_message = ChatMessage(
            role=(
                "user"
                if self.is_user_message
                else "news" if self.is_news_message else "assistant"
            ),
            blocks=self.content_blocks,
            message_id=self.message_id,
        )

        for block in self.content_blocks:
            self._render_content_block(block)

    def _render_content_block(self, block):
        renderer_name = CHAT_BLOCK_RENDERERS.get(type(block))

        if not renderer_name:
            fallback = TextBlock(f"Unsupported chat block: {type(block).__name__}")
            return self._render_text_content_block(fallback)

        renderer = getattr(self, renderer_name)
        return renderer(block)

    def _render_source_header_block(self, block):
        self._add_source_header()

    def _render_news_header_block(self, block):
        self._add_news_header()

    def _render_text_content_block(self, block):
        text_view = AutoHeightRichText()
        text_view.setProperty(
            "messageMode",
            (
                "news"
                if self.is_news_message
                else "user" if self.is_user_message else "assistant"
            ),
        )
        rendered_html = self.inject_news_links(
            render_text_block(
                block.text,
                news_mode=self.is_news_message,
                user_mode=self.is_user_message,
                plain_mode=block.format == "plain",
            )
        )
        text_view.setHtml(rendered_html)
        text_view.link_activated.connect(self._handle_text_link_activated)
        self.response_layout.addWidget(text_view)
        return text_view

    def _render_code_content_block(self, block):
        return self._add_code_block_widget(block.language, block.code)

    def _render_image_content_block(self, block):
        image = ImagePreview(str(block.path))

        if block.caption:
            image.setToolTip(str(block.caption))

        self.response_layout.addWidget(image)
        return image

    def _render_video_content_block(self, block):
        target = block.url or block.path or "video"
        title = block.title or Path(str(target)).name
        label = QLabel(f"Video: {title} — {target}")
        label.setObjectName("fileLine")
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.response_layout.addWidget(label)
        return label

    def _render_file_attachment_block(self, block):
        label_text = block.label or f"Attached: {Path(str(block.path)).name}"
        label = QLabel(label_text)
        label.setObjectName("fileLine")
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.response_layout.addWidget(label)
        return label

    def _render_web_article_block(self, block):
        card = WebArticleCard(block.article)
        self.response_layout.addWidget(card)
        return card

    def _render_news_content_block(self, block):
        parts = [f"### {block.title}"]

        if block.source:
            parts.append(f"**Source:** {block.source}")
        if block.summary:
            parts.append(block.summary)
        if block.url:
            parts.append(f"[Open source]({block.url})")

        return self._render_text_content_block(TextBlock("\n\n".join(parts)))

    def _render_daily_news_brief_block(self, block):
        card = DailyNewsBriefCard(block.payload)
        self.response_layout.addWidget(card)
        return card

    def _render_table_content_block(self, block):
        lines = []

        if block.caption:
            lines.append(str(block.caption))
            lines.append("")

        columns = [str(column) for column in block.columns]
        lines.append("| " + " | ".join(columns) + " |")
        lines.append("| " + " | ".join("---" for _ in columns) + " |")

        for row in block.rows:
            lines.append("| " + " | ".join(str(value) for value in row) + " |")

        return self._render_text_content_block(TextBlock("\n".join(lines)))

    def _render_tool_result_block(self, block):
        status_label = block.status.upper()
        parts = [f"**{status_label}: {block.tool_name} — {block.title}**"]

        if block.body:
            parts.append(block.body)
        if block.details:
            parts.append(f"```text\n{block.details}\n```")

        return self._render_text_content_block(TextBlock("\n\n".join(parts)))

    def _render_citation_block(self, block):
        page_text = f", page {block.page}" if block.page is not None else ""
        citation = f"**{block.label}:** {block.source}{page_text}"

        if block.url:
            citation += f"\n\n[Open source]({block.url})"

        return self._render_text_content_block(TextBlock(citation))

    def _render_stock_quote_block(self, block):
        card = StockQuoteCard(block.payload)
        self.response_layout.addWidget(card)
        return card

    def _render_market_pulse_block(self, block):
        card = MarketPulseCard(block.payload)
        self.response_layout.addWidget(card)
        return card

    def _populate_static_response_content(self):
        self._render_content_blocks(self._build_static_content_blocks())

    def _enter_typing_mode(self):
        if self.is_user_message or self._typing_mode:
            return

        self._typing_mode = True
        self._clear_response_layout()

        self.message_badge.hide()
        self.options_slot.hide()

        self.content_container.setMinimumWidth(66)
        self.content_container.setMaximumWidth(66)
        self.content_container.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Minimum)
        self._set_content_kind("typing")

        self.typing_indicator = TypingIndicatorWidget(self.content_container)
        self.response_layout.addWidget(
            self.typing_indicator, 0, Qt.AlignLeft | Qt.AlignVCenter
        )

        self.adjustSize()
        self.updateGeometry()

    def _leave_typing_mode(self):
        if not self._typing_mode:
            return

        self._typing_mode = False
        self._clear_response_layout()
        self.typing_indicator = None

        self.message_badge.show()
        self.options_slot.show()
        self.options_button.hide()

        self.content_container.setMinimumWidth(0)
        self._apply_content_width(self.text)
        self.content_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._set_content_kind(self._base_content_kind)
        self._populate_static_response_content()

        self.adjustSize()
        self.updateGeometry()

    def set_text(self, text):
        self.text = text
        self.last_stream_answer = ""
        thoughts, answer = self.split_thoughts(text)

        if self.streaming and not self.is_user_message and not answer.strip():
            self._enter_typing_mode()
            return

        if self._typing_mode:
            self._leave_typing_mode()

        self._clear_response_layout()
        self._set_content_kind(self._base_content_kind)

        if self.explicit_content_blocks:
            self._apply_content_width(answer or self.text, self.explicit_content_blocks)
            self._render_content_blocks(self.explicit_content_blocks)

            if self.response_time is not None:
                self._ensure_reply_timer_footer()

            self.adjustSize()
            self.updateGeometry()
            return

        content_blocks = self._build_static_content_blocks()
        pulse_payload = parse_market_pulse_payload(answer)

        if pulse_payload:
            self._set_content_kind("market")
            content_blocks.append(MarketPulseBlock(pulse_payload))
            self._apply_content_width(answer, content_blocks)
            self._render_content_blocks(content_blocks)

            if self.response_time is not None:
                self._ensure_reply_timer_footer()

            self.adjustSize()
            self.updateGeometry()
            return

        quote_payload = parse_stock_quote_payload(answer)

        if quote_payload:
            self._set_content_kind("stock")
            content_blocks.append(StockQuoteBlock(quote_payload))
            self._apply_content_width(answer, content_blocks)
            self._render_content_blocks(content_blocks)

            if self.response_time is not None:
                self._ensure_reply_timer_footer()

            self.adjustSize()
            self.updateGeometry()
            return

        if self.is_news_message:
            news_payload = build_daily_news_brief_payload(answer, self.news_sources)

            if news_payload:
                content_blocks.append(DailyNewsBriefBlock(news_payload))
                self._apply_content_width(answer, content_blocks)
                self._render_content_blocks(content_blocks)

                if self.response_time is not None:
                    self._ensure_reply_timer_footer()

                self.adjustSize()
                self.updateGeometry()
                return

        has_local_image = any(
            str(file_path).lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
            and os.path.exists(file_path)
            for file_path in self.files
        )
        answer = sanitize_markdown_images(answer, has_local_image=has_local_image)

        if self.is_news_message:
            answer = normalize_news_brief_markdown(answer)
        elif not self.is_user_message:
            answer = normalize_assistant_link_markup(answer)
            answer = normalize_compacted_markdown(answer)

        content_blocks.extend(self._build_answer_content_blocks(answer))
        self._apply_content_width(
            answer if not self.is_user_message else self.text, content_blocks
        )
        self._render_content_blocks(content_blocks)

        if self.response_time is not None:
            self._ensure_reply_timer_footer()

        self.adjustSize()
        self.updateGeometry()


class DropScrollArea(QScrollArea):
    files_dropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.viewport().setFocusPolicy(Qt.StrongFocus)

    def wheelEvent(self, event):
        self.verticalScrollBar().setValue(
            self.verticalScrollBar().value() - event.angleDelta().y()
        )
        event.accept()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = []

        for url in event.mimeData().urls():
            local_path = url.toLocalFile()

            if local_path:
                paths.append(local_path)

        if paths:
            self.files_dropped.emit(paths)
