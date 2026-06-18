from pathlib import Path

from fzastro_ai.news_tools import (
    build_deterministic_daily_news_brief,
    format_daily_news_context_from_sections,
    parse_news_sources,
)
from fzastro_ai.ui.message_widgets import build_daily_news_brief_payload


def test_daily_news_context_preserves_published_time_and_image_url():
    context = format_daily_news_context_from_sections(
        [
            {
                "section": "World",
                "items": [
                    {
                        "title": "Example global headline today - Example News",
                        "source_name": "Example News",
                        "source_url": "https://example.test/story",
                        "summary": "A concise RSS summary for the main article.",
                        "published_at": "Thu, 18 Jun 2026 18:15:00 GMT",
                        "image_url": "https://example.test/story.jpg",
                    }
                ],
            }
        ]
    )

    assert "Published: Thu, 18 Jun 2026 18:15:00 GMT" in context
    assert "ImageURL: https://example.test/story.jpg" in context

    sources = parse_news_sources(context)
    assert sources["NEWS_0001"]["published_at"] == "Thu, 18 Jun 2026 18:15:00 GMT"
    assert sources["NEWS_0001"]["image_url"] == "https://example.test/story.jpg"


def test_daily_news_payload_replaces_raw_source_ids_with_story_metadata():
    context = format_daily_news_context_from_sections(
        [
            {
                "section": "World",
                "items": [
                    {
                        "title": "Example global headline today - Example News",
                        "source_name": "Example News",
                        "source_url": "https://example.test/story",
                        "summary": "A longer summary that can be expanded in the lead story card.",
                        "published_at": "Thu, 18 Jun 2026 18:15:00 GMT",
                        "image_url": "https://example.test/story.jpg",
                    }
                ],
            }
        ]
    )
    brief = build_deterministic_daily_news_brief(context)
    payload = build_daily_news_brief_payload(brief, parse_news_sources(context))

    assert payload["title"] == "Daily News Brief"
    assert payload["story_count"] == 1
    assert payload["image_count"] == 1
    assert payload["lead_story"]["headline"] == "Example global headline today."
    assert payload["lead_story"]["publisher"] == "Example News"
    assert payload["lead_story"]["url"] == "https://example.test/story"
    assert payload["sections"][0]["stories"][0]["primary_source_id"] == "NEWS_0001"


def test_daily_news_card_exposes_per_story_details_controls():
    widget_text = (
        Path(__file__).resolve().parents[1] / "fzastro_ai" / "ui" / "message_widgets.py"
    ).read_text(encoding="utf-8-sig")

    assert 'details_button = QPushButton("More")' in widget_text
    assert 'details_button.setObjectName("dailyNewsMoreButton")' in widget_text
    assert 'details_label.setObjectName("dailyNewsSummary")' in widget_text
    assert (
        'preview_text = details_text[:preview_limit].rstrip() + " ..."' in widget_text
    )
    assert "details_label.setVisible(True)" in widget_text
    assert "def sync_parent_chat_layout" in widget_text
    assert 'getattr(self.window(), "sync_chat_container_height", None)' in widget_text
    assert "layout.setAlignment(Qt.AlignTop)" in widget_text
    assert "layout.addWidget(title, 0, Qt.AlignTop)" in widget_text
