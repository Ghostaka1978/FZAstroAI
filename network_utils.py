"""Small bounded-download helpers for HTTP providers.

These helpers keep provider responses from entering memory unbounded. They are
for desktop-worker use, not a replacement for provider-specific validation.
"""

import json

import requests


class DownloadTooLargeError(ValueError):
    """Raised when a streamed provider response exceeds the configured limit."""


def response_header_int(response, header_name):
    try:
        return int(str(response.headers.get(header_name, "")).strip())
    except (TypeError, ValueError):
        return None


def read_limited_response_body(response, max_bytes, chunk_size=64 * 1024):
    """Read a streamed response body with a hard byte cap and close it."""
    max_bytes = int(max_bytes)
    content_length = response_header_int(response, "Content-Length")

    if content_length is not None and content_length > max_bytes:
        close = getattr(response, "close", None)
        if callable(close):
            close()
        raise DownloadTooLargeError(
            f"download is too large ({content_length} bytes; limit {max_bytes} bytes)"
        )

    body = bytearray()

    try:
        for chunk in response.iter_content(chunk_size=chunk_size):
            if not chunk:
                continue

            body.extend(chunk)

            if len(body) > max_bytes:
                raise DownloadTooLargeError(
                    f"download exceeded {max_bytes} bytes while streaming"
                )
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()

    return bytes(body)


def decode_response_bytes(response, data):
    encoding = str(getattr(response, "encoding", "") or "").strip() or "utf-8"

    try:
        return bytes(data or b"").decode(encoding, errors="replace")
    except LookupError:
        return bytes(data or b"").decode("utf-8", errors="replace")


def get_limited_response(url, *, max_bytes, **kwargs):
    """GET a URL with stream=True and return (response, body_bytes).

    The returned response has already been closed by read_limited_response_body().
    """
    kwargs = dict(kwargs)
    kwargs["stream"] = True
    response = requests.get(url, **kwargs)

    try:
        response.raise_for_status()
        body = read_limited_response_body(response, max_bytes=max_bytes)
        return response, body
    except Exception:
        close = getattr(response, "close", None)
        if callable(close):
            close()
        raise


def get_limited_text(url, *, max_bytes, **kwargs):
    response, body = get_limited_response(url, max_bytes=max_bytes, **kwargs)
    return decode_response_bytes(response, body)


def get_limited_json(url, *, max_bytes, **kwargs):
    response, body = get_limited_response(url, max_bytes=max_bytes, **kwargs)
    text = decode_response_bytes(response, body)
    return json.loads(text)
