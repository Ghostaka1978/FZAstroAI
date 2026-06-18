import json

from fzastro_ai.routing.tool_router import ToolPlan
from fzastro_ai.web_companion import server


def test_web_companion_direct_weather_uses_desktop_router(monkeypatch):
    from fzastro_ai import weather_tools

    monkeypatch.setattr(
        server,
        "detect_deterministic_tool_plan",
        lambda *args, **kwargs: ToolPlan(
            action="weather_today",
            tool_id="weather.today",
            query="Frankfurt",
        ),
    )
    monkeypatch.setattr(
        weather_tools,
        "perform_weather_today",
        lambda query: (
            "[WEATHER]\n"
            "# Weather Today - Frankfurt\n\n"
            "Open-Meteo URL: https://api.open-meteo.com/v1/forecast?"
            "latitude=50.1&longitude=8.6"
        ),
    )

    result = server._web_chat_direct_tool_response(
        server.ChatRequest(prompt="weather today in Frankfurt")
    )

    assert result is not None
    assert result["direct"] is True
    assert result["tool"] == "weather.today"
    assert "[WEATHER]" not in result["text"]
    assert "[Open-Meteo forecast]" in result["text"]
    assert "https://api.open-meteo.com/v1/forecast" in result["text"]


def test_web_companion_direct_market_pulse_returns_renderable_table(monkeypatch):
    from fzastro_ai import market_sources

    payload = {
        "title": "Global Market Pulse",
        "retrieved_at": "2026-06-19 10:00:00 UTC",
        "source_name": "Yahoo Finance structured chart endpoint",
        "source_url": "https://finance.yahoo.com/markets/",
        "summary": {"up": 1, "down": 0, "flat": 0, "unavailable": 0},
        "groups": [
            {
                "name": "US indices",
                "rows": [
                    {
                        "label": "S&P 500",
                        "ticker": "^GSPC",
                        "last": "7,500.64",
                        "change_text": "+80.54 / +1.09%",
                        "status": "After hours",
                    }
                ],
            }
        ],
        "unavailable": [],
        "disclaimer": "Market data can be delayed.",
    }

    monkeypatch.setattr(
        server,
        "detect_deterministic_tool_plan",
        lambda *args, **kwargs: ToolPlan(
            action="market_pulse",
            tool_id="market.pulse",
            query="global_market_pulse",
        ),
    )
    monkeypatch.setattr(
        market_sources,
        "perform_global_market_pulse",
        lambda: "[MARKET_PULSE]\n" + json.dumps(payload),
    )

    result = server._web_chat_direct_tool_response(
        server.ChatRequest(prompt="global market pulse")
    )

    assert result is not None
    assert result["direct"] is True
    assert result["tool"] == "market.pulse"
    assert "# Global Market Pulse" in result["text"]
    assert "| Indicator | Symbol | Last | Change / % | Status |" in result["text"]
    assert (
        "| S&P 500 | ^GSPC | 7,500.64 | +80.54 / +1.09% | After hours |"
        in result["text"]
    )


def test_web_companion_direct_screenshot_exposes_image_file(monkeypatch):
    from fzastro_ai import web_tools

    monkeypatch.setattr(
        server,
        "detect_deterministic_tool_plan",
        lambda *args, **kwargs: ToolPlan(
            action="web_screenshot_page",
            tool_id="web.screenshot_page",
            query="screenshot https://example.com",
        ),
    )
    monkeypatch.setattr(
        web_tools,
        "perform_website_screenshot",
        lambda query: (
            "[WEB SCREENSHOT]\n"
            "ImageFile: C:/Temp/fzastro_web_screenshots/example.png\n"
            "PageURL: https://example.com\n"
            "CaptureMode: Viewport\n"
            "Title: Example Domain\n"
            "Dimensions: 1440x1000"
        ),
    )

    result = server._web_chat_direct_tool_response(
        server.ChatRequest(prompt="screenshot https://example.com")
    )

    assert result is not None
    assert result["direct"] is True
    assert result["tool"] == "web.screenshot_page"
    assert result["images"] == ["C:/Temp/fzastro_web_screenshots/example.png"]
    assert "[Example Domain]" not in result["text"]
    assert "Source: [Open page](https://example.com)" in result["text"]
