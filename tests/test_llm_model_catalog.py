from fzastro_ai.llm import content, model_catalog


def test_content_token_estimates_and_image_reserve():
    assert content.estimate_token_count("") == 0
    assert content.estimate_token_count("abcd") == 1
    assert content.estimate_token_count("x" * 40) == 10

    parts = [
        {"type": "text", "text": "x" * 16},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
    ]

    assert content.estimate_model_content_tokens(parts) == 4 + 1024
    assert (
        content.estimate_messages_context_tokens(
            [{"role": "user", "content": "hello world"}]
        )
        == 7
    )
    assert content.format_token_budget_count(12_345) == "12.3k"


def test_content_normalization_preserves_or_strips_images_by_capability():
    parts = [
        {"type": "text", "text": "Inspect this."},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
    ]

    assert content.normalize_content_for_model(parts, allow_images=True) is parts

    stripped = content.normalize_content_for_model(parts, allow_images=False)
    assert "Inspect this." in stripped
    assert "selected model does not support vision" in stripped

    text_only = [
        {"type": "text", "text": "First"},
        {"type": "input_text", "text": "Second"},
    ]
    assert content.normalize_content_for_model(text_only) == "First\nSecond"


def test_parse_ollama_context_limit_prefers_runtime_num_ctx():
    payload = {
        "parameters": "PARAMETER temperature 0.3\nPARAMETER num_ctx 32768\n",
        "model_info": {
            "general.context_length": 8192,
            "other.context length": 16384,
        },
    }

    assert model_catalog.parse_ollama_context_limit(payload) == 32768
    assert (
        model_catalog.parse_ollama_context_limit(
            {"model_info": {"general.context_length": "65536"}}
        )
        == 65536
    )
    assert model_catalog.parse_ollama_context_limit({"model_info": {}}) is None


def test_qwen_text_only_filter_and_reliable_vision_hints():
    assert model_catalog.ollama_model_name_is_qwen_text_only("qwen3.6:35b")
    assert model_catalog.ollama_model_name_is_qwen_text_only("qwen2.5:32b")
    assert not model_catalog.ollama_model_name_is_qwen_text_only("qwen2.5-vl:7b")
    assert model_catalog.ollama_model_name_has_reliable_vision_hint("llava:latest")
    assert model_catalog.ollama_model_name_has_reliable_vision_hint("qwen2.5-vl:7b")
    assert not model_catalog.ollama_model_name_has_reliable_vision_hint("qwen3:32b")


def test_get_ollama_capabilities_filters_qwen_text_only_vision(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"capabilities": ["completion", "vision"]}

    calls = []

    def fake_post(url, json, timeout):
        calls.append((url, json, timeout))
        return FakeResponse()

    model_catalog._MODEL_CAPABILITY_CACHE.clear()
    model_catalog.configure_model_catalog_runtime("http://localhost:11434/v1", "key")
    monkeypatch.setattr(model_catalog.requests, "post", fake_post)

    assert model_catalog.get_ollama_model_capabilities("qwen3:32b") == {"completion"}
    assert calls[0][0] == "http://localhost:11434/api/show"
    assert calls[0][1] == {"model": "qwen3:32b"}


def test_find_installed_vision_model_prefers_stable_explicit_vision(monkeypatch):
    model_catalog._MODEL_CAPABILITY_CACHE.clear()
    monkeypatch.setattr(
        model_catalog,
        "get_available_models",
        lambda: [
            "qwen3:32b",
            "llava-uncensored:13b",
            "qwen2.5-vl:7b",
            "llava:latest",
        ],
    )

    capabilities = {
        "qwen3:32b": {"completion", "vision"},
        "llava-uncensored:13b": {"completion", "vision"},
        "qwen2.5-vl:7b": {"completion", "vision"},
        "llava:latest": {"completion", "vision"},
    }
    monkeypatch.setattr(
        model_catalog,
        "get_ollama_model_capabilities",
        lambda model_name: capabilities.get(model_name),
    )

    assert model_catalog.find_installed_vision_model() == "llava:latest"
    assert model_catalog.find_installed_vision_model(exclude_model="llava:latest") == (
        "qwen2.5-vl:7b"
    )
