import json

import pytest

from fzastro_ai import network_utils


class FakeResponse:
    def __init__(self, chunks, headers=None, status_code=200, encoding="utf-8"):
        self._chunks = list(chunks)
        self.headers = dict(headers or {})
        self.status_code = status_code
        self.encoding = encoding
        self.closed = False
        self.iterated = False

    def iter_content(self, chunk_size=65536):
        self.iterated = True
        yield from self._chunks

    def close(self):
        self.closed = True

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_read_limited_response_body_closes_response():
    response = FakeResponse([b"abc", b"def"], headers={"Content-Length": "6"})

    assert network_utils.read_limited_response_body(response, max_bytes=6) == b"abcdef"
    assert response.iterated is True
    assert response.closed is True


def test_read_limited_response_body_rejects_content_length_before_streaming():
    response = FakeResponse([b"not-read"], headers={"Content-Length": "7"})

    with pytest.raises(network_utils.DownloadTooLargeError):
        network_utils.read_limited_response_body(response, max_bytes=6)

    assert response.iterated is False
    assert response.closed is True


def test_get_limited_json_streams_and_parses(monkeypatch):
    response = FakeResponse([json.dumps({"ok": True}).encode("utf-8")])

    def fake_get(url, **kwargs):
        assert url == "https://example.test/data.json"
        assert kwargs["stream"] is True
        assert kwargs["timeout"] == 3
        return response

    monkeypatch.setattr(network_utils.requests, "get", fake_get)

    assert network_utils.get_limited_json(
        "https://example.test/data.json", max_bytes=100, timeout=3
    ) == {"ok": True}
    assert response.closed is True
