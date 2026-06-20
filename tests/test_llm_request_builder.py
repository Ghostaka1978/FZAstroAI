import pytest

from fzastro_ai.llm import build_chat_request_params


def test_build_chat_request_params_chat_ollama_profile():
    messages = [{"role": "user", "content": "hello"}]

    params = build_chat_request_params(
        model="qwen3:6.35b",
        messages=messages,
        profile="chat",
        base_url="http://localhost:11434/v1",
        stream=True,
    )

    assert params == {
        "model": "qwen3:6.35b",
        "messages": messages,
        "stream": True,
        "temperature": 0.3,
        "top_p": 0.95,
        "presence_penalty": 0.2,
        "extra_body": {
            "think": True,
            "top_k": 20,
            "options": {
                "num_predict": 4096,
                "repeat_penalty": 1.08,
                "repeat_last_n": 64,
            },
        },
    }
    assert "max_tokens" not in params


def test_build_chat_request_params_vision_ollama_profile():
    params = build_chat_request_params(
        model="qwen2.5vl:7b",
        messages=[{"role": "user", "content": "describe image"}],
        profile="vision",
        base_url="http://127.0.0.1:11434/v1",
    )

    assert params["temperature"] == 0.12
    assert params["top_p"] == 0.90
    assert params["presence_penalty"] == 0.0
    assert params["extra_body"] == {
        "think": False,
        "top_k": 20,
        "options": {
            "num_predict": 1200,
            "repeat_penalty": 1.16,
            "repeat_last_n": 256,
        },
    }


def test_build_chat_request_params_non_ollama_uses_max_tokens():
    params = build_chat_request_params(
        model="cloud-model",
        messages=[{"role": "user", "content": "hello"}],
        profile="chat",
        base_url="https://api.example.com/v1",
        num_predict=777,
    )

    assert params["max_tokens"] == 777
    assert "extra_body" not in params


def test_build_chat_request_params_router_response_format():
    response_format = {"type": "json_object"}

    params = build_chat_request_params(
        model="router-model",
        messages=[{"role": "user", "content": "decide"}],
        profile="router",
        base_url="http://localhost:11434/v1",
        stream=False,
        response_format=response_format,
    )

    assert params["stream"] is False
    assert params["temperature"] == 0.0
    assert params["response_format"] == response_format
    assert params["extra_body"] == {
        "think": False,
        "options": {"num_ctx": 4096},
    }


def test_build_chat_request_params_benchmark_includes_temperature_option():
    params = build_chat_request_params(
        model="bench-model",
        messages=[{"role": "user", "content": "bench"}],
        profile="benchmark",
        base_url="http://localhost:11434/v1",
        temperature=0.7,
        num_predict=999,
    )

    assert params["temperature"] == 0.7
    assert params["extra_body"] == {
        "think": False,
        "options": {
            "num_predict": 999,
            "repeat_penalty": 1.05,
            "temperature": 0.7,
        },
    }


def test_build_chat_request_params_rejects_unknown_profile():
    with pytest.raises(ValueError, match="Unknown generation profile"):
        build_chat_request_params(
            model="model",
            messages=[],
            profile="unknown",
            base_url="http://localhost:11434/v1",
        )


def test_build_chat_request_params_adds_ollama_keep_alive():
    params = build_chat_request_params(
        model="qwen3:6.35b",
        messages=[{"role": "user", "content": "hello"}],
        profile="chat",
        base_url="http://localhost:11434/v1",
        keep_alive="60m",
    )

    assert params["extra_body"]["keep_alive"] == "60m"


def test_build_chat_request_params_does_not_send_keep_alive_to_remote_provider():
    params = build_chat_request_params(
        model="cloud-model",
        messages=[{"role": "user", "content": "hello"}],
        profile="chat",
        base_url="https://api.example.com/v1",
        keep_alive="60m",
    )

    assert "extra_body" not in params
