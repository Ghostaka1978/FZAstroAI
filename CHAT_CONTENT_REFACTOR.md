# Chat Content Rendering Refactor

This RC introduces the first compatibility layer for standardising how the chat window displays mixed content.

## Goal

All chat output should move toward this pipeline:

```text
Producer/action/worker
  -> structured ContentBlock objects
  -> MessageWidget renderer registry
  -> block-specific Qt widgets/cards
```

The chat UI should render known block types rather than guessing from ad-hoc strings produced by each feature.

## Added model

`fzastro_ai/chat_blocks.py` defines Qt-free dataclasses for the main content types:

- `TextBlock`
- `CodeBlock`
- `ImageBlock`
- `VideoBlock`
- `FileAttachmentBlock`
- `WebArticleBlock`
- `NewsBlock`
- `TableBlock`
- `ToolResultBlock`
- `CitationBlock`
- `SourceHeaderBlock`
- `NewsHeaderBlock`
- `StockQuoteBlock`
- `ChatMessage`

The module intentionally has no Qt imports so it remains safe for headless tests and non-GUI tooling.

## Added renderer registry

`fzastro_ai/ui/message_widgets.py` now contains a single renderer registry:

```python
CHAT_BLOCK_RENDERERS = {
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
    SourceHeaderBlock: "_render_source_header_block",
    NewsHeaderBlock: "_render_news_header_block",
    StockQuoteBlock: "_render_stock_quote_block",
}
```

Existing legacy message inputs are converted to blocks internally before static rendering.

## Compatibility guarantees in this RC patch

This patch is deliberately conservative:

- Existing `add_message_widget(...)` callers still work.
- Existing history format is unchanged.
- Existing streaming behaviour is unchanged for performance.
- Existing text, code, image, file, web article, news header, source header and stock quote UI components are reused.
- A new optional `content_blocks=` parameter is available for future producers that already have structured data.

## What this patch does not do yet

This is the foundation, not the full migration.

Still to migrate in later phases:

- Save/load structured block history.
- Convert web/news/Python/document/astro producers to emit blocks directly.
- Replace deterministic tool failures with `ToolResultBlock` cards at the producer boundary.
- Add richer dedicated widgets for `VideoBlock`, `TableBlock`, `NewsBlock`, and `CitationBlock` instead of Markdown-backed fallback rendering.
- Add export/copy support for all block types after history migration.

## Recommended next phase

Migrate deterministic producers first, because they create the most visible inconsistency:

1. Screenshot success/failure -> `ImageBlock` / `ToolResultBlock`
2. Rendered page extraction failure -> `ToolResultBlock`
3. Web search results -> `WebArticleBlock` / `CitationBlock`
4. Daily news stories -> `NewsBlock`
5. Document visual page retrieval -> `ImageBlock` + `CitationBlock`
6. Python execution result -> `ToolResultBlock` + `CodeBlock` / `FileAttachmentBlock`

Keep model-streamed assistant text on the existing streaming path until finalization. Streaming can be migrated after deterministic tool outputs are stable.
