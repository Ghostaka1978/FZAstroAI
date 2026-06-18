from types import SimpleNamespace

from fzastro_ai.llm import (
    extract_delta_reasoning,
    extract_delta_text,
    is_expected_stream_close_error,
    looks_like_repetition_loop,
)


class DumpObject:
    def __init__(self, **data):
        self._data = data

    def model_dump(self):
        return dict(self._data)


def _chunk(delta=None, *, choice_extra=None, chunk_extra=None):
    choice = SimpleNamespace(delta=delta, model_extra=choice_extra)
    return SimpleNamespace(choices=[choice], model_extra=chunk_extra)


def test_extract_delta_text_from_attribute():
    chunk = _chunk(SimpleNamespace(content="hello"))

    assert extract_delta_text(chunk) == "hello"


def test_extract_delta_text_from_model_dump():
    chunk = _chunk(DumpObject(content="from dump"))

    assert extract_delta_text(chunk) == "from dump"


def test_extract_delta_text_handles_empty_choices():
    assert extract_delta_text(SimpleNamespace(choices=[])) == ""
    assert extract_delta_text(SimpleNamespace()) == ""


def test_extract_delta_reasoning_from_attribute():
    chunk = _chunk(SimpleNamespace(content=None, thinking="think"))

    assert extract_delta_reasoning(chunk) == "think"


def test_extract_delta_reasoning_from_model_dump():
    chunk = _chunk(DumpObject(reasoning_content="reason"))

    assert extract_delta_reasoning(chunk) == "reason"


def test_extract_delta_reasoning_from_model_extra_fallbacks():
    assert (
        extract_delta_reasoning(
            _chunk(SimpleNamespace(content=None, model_extra={"reasoning": "delta"}))
        )
        == "delta"
    )
    assert (
        extract_delta_reasoning(
            _chunk(SimpleNamespace(content=None), choice_extra={"thinking": "choice"})
        )
        == "choice"
    )
    assert (
        extract_delta_reasoning(
            _chunk(
                SimpleNamespace(content=None),
                chunk_extra={"reasoning_content": "chunk"},
            )
        )
        == "chunk"
    )


def test_is_expected_stream_close_error_markers():
    assert is_expected_stream_close_error(RuntimeError("ResponseClosed"))
    assert is_expected_stream_close_error(OSError("[WinError 10038] not a socket"))
    assert not is_expected_stream_close_error(RuntimeError("provider refused auth"))


def test_looks_like_repetition_loop_detects_common_patterns():
    assert not looks_like_repetition_loop("short short short")

    repeated_word = " ".join(["alpha"] * 80)
    assert looks_like_repetition_loop(repeated_word)

    repeated_phrase = " ".join(["red green blue"] * 45)
    assert looks_like_repetition_loop(repeated_phrase)
