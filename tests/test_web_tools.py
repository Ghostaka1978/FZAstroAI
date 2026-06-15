import pytest

from fzastro_ai import web_tools


class FakeResponse:
    def __init__(self, chunks, headers=None, status_code=200):
        self._chunks = list(chunks)
        self.headers = dict(headers or {})
        self.status_code = status_code
        self.closed = False
        self.iterated = False

    def iter_content(self, chunk_size=65536):
        self.iterated = True
        yield from self._chunks

    def close(self):
        self.closed = True


def test_web_tools_imports_without_ui_or_provider_dependencies():
    assert web_tools.WEB_IMAGE_DOWNLOAD_MAX_BYTES > 0
    assert web_tools.RENDERED_PAGE_IMAGE_PREVIEW_MAX_BYTES > 0


def test_limited_response_body_streams_and_closes_response():
    response = FakeResponse([b"abc", b"", b"def"], headers={"Content-Length": "6"})

    assert web_tools._read_limited_response_body(response, max_bytes=6) == b"abcdef"
    assert response.iterated is True
    assert response.closed is True


def test_limited_response_body_rejects_content_length_before_streaming():
    response = FakeResponse([b"not-read"], headers={"Content-Length": "7"})

    with pytest.raises(web_tools.WebDownloadTooLargeError):
        web_tools._read_limited_response_body(response, max_bytes=6)

    assert response.iterated is False
    assert response.closed is True


def test_limited_response_body_rejects_when_stream_exceeds_limit():
    response = FakeResponse([b"abc", b"defg"], headers={})

    with pytest.raises(web_tools.WebDownloadTooLargeError):
        web_tools._read_limited_response_body(response, max_bytes=6)

    assert response.iterated is True
    assert response.closed is True


def test_playwright_launcher_falls_back_to_installed_edge(monkeypatch):
    class FakeChromium:
        def __init__(self):
            self.calls = []

        def launch(self, **kwargs):
            self.calls.append(kwargs)
            if kwargs.get("channel") == "msedge":
                return "edge-browser"
            raise RuntimeError("Executable doesn't exist at bundled chromium")

    class FakePlaywright:
        def __init__(self):
            self.chromium = FakeChromium()

    logged = []
    monkeypatch.setattr(
        web_tools,
        "log_debug",
        lambda message, exc=None: logged.append(message),
    )

    playwright = FakePlaywright()

    assert web_tools._launch_playwright_chromium(playwright) == "edge-browser"
    assert playwright.chromium.calls == [
        {"headless": True},
        {"headless": True, "channel": "msedge"},
    ]
    assert logged


def test_playwright_launcher_reports_all_browser_candidates(monkeypatch):
    class FakeChromium:
        def launch(self, **kwargs):
            raise RuntimeError("Executable doesn't exist ╔ large playwright box")

    class FakePlaywright:
        chromium = FakeChromium()

    monkeypatch.setattr(web_tools, "log_debug", lambda message, exc=None: None)

    with pytest.raises(RuntimeError) as error:
        web_tools._launch_playwright_chromium(FakePlaywright())

    message = str(error.value)
    assert "bundled Playwright Chromium" in message
    assert "installed Microsoft Edge" in message
    assert "installed Google Chrome" in message
    assert "python -m playwright install chromium" in message
    assert "large playwright box" not in message
