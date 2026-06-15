from fzastro_ai.memory_store import (
    build_persistent_memory_context,
    empty_persistent_memory,
    normalize_memory_entry,
    normalize_persistent_memory,
    search_persistent_memory_entries,
)


def test_normalize_memory_entry_accepts_text_and_defaults():
    entry = normalize_memory_entry("Use gain 100 for the ASI camera")

    assert entry is not None
    assert entry["category"] == "other"
    assert entry["source"] == "manual"
    assert "ASI camera" in entry["content"]
    assert entry["title"].startswith("Use gain 100")


def test_normalize_memory_entry_preserves_code_formatting():
    code = "```python\ndef f():\n    return 42\n```"
    entry = normalize_memory_entry({"content": code, "category": "procedure"})

    assert entry is not None
    assert "    return 42" in entry["content"]
    assert entry["category"] == "procedure"


def test_persistent_memory_search_and_context():
    memory = normalize_persistent_memory(
        {
            "entries": [
                {
                    "content": "Polar alignment checklist uses SharpCap",
                    "category": "procedure",
                    "tags": ["astro"],
                },
                {"content": "Unrelated cooking note", "category": "other"},
            ]
        }
    )

    results = search_persistent_memory_entries(memory, "polar alignment")
    assert results
    assert "SharpCap" in results[0]["content"]

    context = build_persistent_memory_context(memory, "polar alignment")
    assert "Polar alignment" in context
    assert "SharpCap" in context


def test_empty_memory_shape_is_stable():
    memory = empty_persistent_memory()
    assert memory["entries"] == []
    assert "version" in memory
