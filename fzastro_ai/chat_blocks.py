"""Structured chat content blocks used by the chat renderer.

The app stores conversation history in the existing OpenAI-compatible message
shape, but the UI should not need to infer every content type from ad-hoc
strings.  These lightweight dataclasses are the compatibility layer between
legacy producers and the chat widget renderer.

Keep this module free of Qt imports so it can be tested and imported in
headless environments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Sequence, TypeAlias

MessageRole: TypeAlias = Literal["user", "assistant", "system", "tool", "news"]
TextFormat: TypeAlias = Literal["plain", "markdown"]
ToolStatus: TypeAlias = Literal["running", "success", "warning", "error"]


@dataclass(frozen=True)
class TextBlock:
    """Plain or Markdown text rendered with the standard chat text renderer."""

    text: str
    format: TextFormat = "markdown"


@dataclass(frozen=True)
class CodeBlock:
    """A fenced-code or source-code block with copy/run affordances."""

    code: str
    language: str = "code"
    source_path: str | None = None


@dataclass(frozen=True)
class ImageBlock:
    """A local image rendered as a chat preview."""

    path: str | Path
    caption: str | None = None
    alt_text: str | None = None


@dataclass(frozen=True)
class VideoBlock:
    """A video or video URL card.

    The first renderer can expose this as an openable card instead of embedding
    playback, which avoids codec and frozen-build risk.
    """

    path: str | Path | None = None
    url: str | None = None
    title: str | None = None
    thumbnail_path: str | Path | None = None


@dataclass(frozen=True)
class FileAttachmentBlock:
    """A non-image attachment line/card."""

    path: str | Path
    label: str | None = None


@dataclass(frozen=True)
class WebArticleBlock:
    """A web result/news article card payload."""

    article: dict[str, Any]


@dataclass(frozen=True)
class NewsBlock:
    """A normalized news card for future feed/daily-news rendering."""

    title: str
    source: str = ""
    summary: str = ""
    url: str | None = None
    published_at: datetime | None = None


@dataclass(frozen=True)
class TableBlock:
    """Tabular data rendered with a consistent table/card widget."""

    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    caption: str | None = None


@dataclass(frozen=True)
class ToolResultBlock:
    """A deterministic app/tool status, result, warning, or error card."""

    tool_name: str
    title: str
    body: str = ""
    status: ToolStatus = "success"
    details: str | None = None


@dataclass(frozen=True)
class CitationBlock:
    """A source/citation card for documents, web pages, and news."""

    label: str
    source: str
    page: int | None = None
    url: str | None = None


@dataclass(frozen=True)
class SourceHeaderBlock:
    """Existing source-chip header rendered as the first assistant block."""

    tags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class NewsHeaderBlock:
    """Existing daily-news header rendered before news text."""

    source_count: int = 0


@dataclass(frozen=True)
class DailyNewsBriefBlock:
    """Structured daily-news briefing payload with exact source metadata."""

    payload: dict[str, Any]


@dataclass(frozen=True)
class StockQuoteBlock:
    """Structured stock quote payload produced by market tools."""

    payload: dict[str, Any]


@dataclass(frozen=True)
class MarketPulseBlock:
    """Structured global market pulse payload produced by market tools."""

    payload: dict[str, Any]


ContentBlock: TypeAlias = (
    TextBlock
    | CodeBlock
    | ImageBlock
    | VideoBlock
    | FileAttachmentBlock
    | WebArticleBlock
    | NewsBlock
    | TableBlock
    | ToolResultBlock
    | CitationBlock
    | SourceHeaderBlock
    | NewsHeaderBlock
    | DailyNewsBriefBlock
    | StockQuoteBlock
    | MarketPulseBlock
)


@dataclass(frozen=True)
class ChatMessage:
    """Structured chat message for UI rendering and future history migration."""

    role: MessageRole
    blocks: tuple[ContentBlock, ...]
    message_id: str = ""
    source: str | None = None
    created_at: datetime | None = None


def coerce_blocks(blocks: Sequence[ContentBlock] | None) -> tuple[ContentBlock, ...]:
    """Return an immutable block tuple and fail fast on invalid producers."""

    if not blocks:
        return ()

    allowed_types = getattr(ContentBlock, "__args__", ())
    clean_blocks: list[ContentBlock] = []

    for block in blocks:
        if allowed_types and not isinstance(block, allowed_types):
            raise TypeError(f"Unsupported chat content block: {type(block)!r}")
        clean_blocks.append(block)

    return tuple(clean_blocks)


def blocks_to_plain_text(blocks: Sequence[ContentBlock] | None) -> str:
    """Best-effort plain text used by copy/export paths."""

    lines: list[str] = []

    for block in blocks or []:
        if isinstance(block, TextBlock):
            lines.append(block.text)
        elif isinstance(block, CodeBlock):
            header = f"```{block.language or 'code'}".rstrip()
            lines.append(f"{header}\n{block.code.rstrip()}\n```")
        elif isinstance(block, ImageBlock):
            caption = f" — {block.caption}" if block.caption else ""
            lines.append(f"[Image: {Path(block.path).name}{caption}]")
        elif isinstance(block, VideoBlock):
            target = block.url or block.path or "video"
            title = f"{block.title}: " if block.title else ""
            lines.append(f"[Video: {title}{target}]")
        elif isinstance(block, FileAttachmentBlock):
            label = block.label or Path(block.path).name
            lines.append(f"[Attached file: {label}]")
        elif isinstance(block, WebArticleBlock):
            article = block.article or {}
            title = str(article.get("title") or article.get("name") or "Web article")
            url = str(article.get("url") or article.get("href") or "")
            lines.append(f"{title}\n{url}".strip())
        elif isinstance(block, NewsBlock):
            source = f" [{block.source}]" if block.source else ""
            url = f"\n{block.url}" if block.url else ""
            lines.append(f"{block.title}{source}\n{block.summary}{url}".strip())
        elif isinstance(block, TableBlock):
            rows = [" | ".join(block.columns)]
            rows.extend(" | ".join(row) for row in block.rows)
            if block.caption:
                rows.insert(0, block.caption)
            lines.append("\n".join(rows))
        elif isinstance(block, ToolResultBlock):
            details = f"\n{block.details}" if block.details else ""
            lines.append(
                f"[{block.status.upper()}] {block.tool_name}: {block.title}\n{block.body}{details}".strip()
            )
        elif isinstance(block, CitationBlock):
            page = f", page {block.page}" if block.page is not None else ""
            url = f"\n{block.url}" if block.url else ""
            lines.append(f"[{block.label}] {block.source}{page}{url}".strip())
        elif isinstance(block, DailyNewsBriefBlock):
            payload = block.payload or {}
            sections = []
            for section in payload.get("sections") or []:
                stories = [
                    f"- {story.get('headline')} ({story.get('publisher') or 'Source'})"
                    for story in section.get("stories") or []
                ]
                if stories:
                    sections.append(
                        f"{section.get('name') or 'News'}\n" + "\n".join(stories)
                    )
            lines.append(
                "\n\n".join(
                    [
                        str(payload.get("title") or "Daily News Brief"),
                        *sections,
                    ]
                ).strip()
            )
        elif isinstance(block, StockQuoteBlock):
            payload = block.payload or {}
            ticker = str(payload.get("ticker") or "").strip()
            price = str(payload.get("price") or "").strip()
            change = str(payload.get("percentage_change") or "").strip()
            lines.append(f"[Market quote] {ticker}: {price} ({change}%)".strip())
        elif isinstance(block, MarketPulseBlock):
            payload = block.payload or {}
            sections = []
            for group in payload.get("groups") or []:
                rows = [
                    f"{row.get('label')}: {row.get('last')} ({row.get('change_text') or row.get('percent_change')})"
                    for row in group.get("rows") or []
                ]
                if rows:
                    sections.append(
                        f"{group.get('name') or 'Market group'}\n" + "\n".join(rows)
                    )
            lines.append(
                "\n\n".join(
                    [
                        str(payload.get("title") or "Global Market Pulse"),
                        *sections,
                    ]
                ).strip()
            )

    return "\n\n".join(line for line in lines if str(line).strip()).strip()
