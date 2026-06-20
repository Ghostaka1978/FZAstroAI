from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_chat_block_model_is_qt_free_and_supports_core_media_types():
    import fzastro_ai.chat_blocks as chat_blocks

    blocks = [
        chat_blocks.TextBlock("hello"),
        chat_blocks.CodeBlock("print('ok')", language="python"),
        chat_blocks.ImageBlock("screen.png", caption="Screenshot"),
        chat_blocks.VideoBlock(url="https://example.invalid/video.mp4", title="Clip"),
        chat_blocks.ToolResultBlock("Web", "Browser unavailable", status="warning"),
        chat_blocks.NewsBlock("Title", source="Source", summary="Summary"),
        chat_blocks.DailyNewsBriefBlock(
            {
                "title": "Daily News Brief",
                "sections": [
                    {
                        "name": "World",
                        "stories": [
                            {
                                "headline": "Story one",
                                "publisher": "Example News",
                            }
                        ],
                    }
                ],
            }
        ),
        chat_blocks.TableBlock(("A", "B"), (("1", "2"),)),
        chat_blocks.CitationBlock("Source 1", "document.pdf", page=4),
        chat_blocks.MarketPulseBlock(
            {
                "title": "Global Market Pulse",
                "groups": [
                    {
                        "name": "US",
                        "rows": [
                            {
                                "label": "S&P 500",
                                "ticker": "^GSPC",
                                "last": "7,500.64",
                                "change_text": "+80.54 / +1.09%",
                            }
                        ],
                    }
                ],
            }
        ),
    ]

    message = chat_blocks.ChatMessage(role="assistant", blocks=tuple(blocks))
    assert len(message.blocks) == len(blocks)
    assert "hello" in chat_blocks.blocks_to_plain_text(blocks)
    assert "print('ok')" in chat_blocks.blocks_to_plain_text(blocks)


def test_message_widget_uses_structured_content_block_registry():
    widget_text = (PROJECT_ROOT / "fzastro_ai" / "ui" / "message_widgets.py").read_text(
        encoding="utf-8-sig"
    )
    app_text = (PROJECT_ROOT / "fzastro_ai" / "app.py").read_text(encoding="utf-8-sig")

    assert "CHAT_BLOCK_RENDERERS" in widget_text
    assert 'TextBlock: "_render_text_content_block"' in widget_text
    assert 'ImageBlock: "_render_image_content_block"' in widget_text
    assert 'VideoBlock: "_render_video_content_block"' in widget_text
    assert 'ToolResultBlock: "_render_tool_result_block"' in widget_text
    assert 'DailyNewsBriefBlock: "_render_daily_news_brief_block"' in widget_text
    assert 'MarketPulseBlock: "_render_market_pulse_block"' in widget_text
    assert "build_daily_news_brief_payload(answer, self.news_sources)" in widget_text
    assert "class DailyNewsBriefCard" in widget_text
    assert "parse_market_pulse_payload(answer)" in widget_text
    assert "class MarketPulseCard" in widget_text
    assert "def _render_content_blocks" in widget_text
    assert "self._build_answer_content_blocks(answer)" in widget_text
    assert "content_blocks=None" in app_text
    assert "content_blocks=content_blocks" in app_text
