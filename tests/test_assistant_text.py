from fzastro_ai.assistant_text import normalize_assistant_link_markup


def test_normalize_assistant_link_markup_converts_html_anchor_to_markdown():
    text = 'Read <a href="https://example.com/story?id=1">the article</a> now.'

    assert (
        normalize_assistant_link_markup(text)
        == "Read [the article](https://example.com/story?id=1) now."
    )


def test_normalize_assistant_link_markup_converts_escaped_anchor():
    text = "Source: &lt;a href=&quot;https://example.com&quot;&gt;Example&lt;/a&gt;"

    assert (
        normalize_assistant_link_markup(text)
        == "Source: [Example](https://example.com)"
    )


def test_normalize_assistant_link_markup_preserves_fenced_html_code():
    text = (
        "Use this link: <a href='https://example.com'>Example</a>\n\n"
        '```html\n<a href="https://example.com">Example</a>\n```'
    )

    result = normalize_assistant_link_markup(text)

    assert "Use this link: [Example](https://example.com)" in result
    assert '```html\n<a href="https://example.com">Example</a>\n```' in result


def test_normalize_assistant_link_markup_turns_simple_html_layout_into_markdown_text():
    text = "<p><strong>Source</strong><br><a href='https://example.com'>Open</a></p>"

    assert (
        normalize_assistant_link_markup(text)
        == "**Source**\n[Open](https://example.com)"
    )


def test_normalize_assistant_link_markup_shortens_bare_urls():
    text = (
        "Source: https://api.open-meteo.com/v1/forecast?"
        "latitude=52.520000&longitude=13.405000&hourly=temperature_2m"
    )

    result = normalize_assistant_link_markup(text)

    assert result.startswith("Source: [Open-Meteo forecast](")
    assert "latitude=52.520000" in result
    assert "Source: https://api.open-meteo.com" not in result


def test_normalize_assistant_link_markup_polishes_source_url_lines():
    text = (
        "Source: Yahoo Finance https://finance.yahoo.com/quote/CRM\n"
        "SourceURL: https://example.test/story?id=1"
    )

    result = normalize_assistant_link_markup(text)

    assert "Source: [Yahoo Finance](https://finance.yahoo.com/quote/CRM)" in result
    assert "Source: [example.test/story](https://example.test/story?id=1)" in result
    assert "SourceURL:" not in result


def test_normalize_assistant_link_markup_polishes_open_meteo_url_lines():
    text = (
        "Open-Meteo URL: https://api.open-meteo.com/v1/forecast?"
        "latitude=52.520000&longitude=13.405000"
    )

    result = normalize_assistant_link_markup(text)

    assert result.startswith("Source: [Open-Meteo forecast](")
    assert "Open-Meteo URL:" not in result
    assert "latitude=52.520000" in result


def test_normalize_assistant_link_markup_preserves_existing_markdown_link():
    text = "Source: [Open-Meteo forecast](https://api.open-meteo.com/v1/forecast)"

    assert normalize_assistant_link_markup(text) == text
