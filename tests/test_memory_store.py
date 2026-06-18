import json

import fzastro_ai.memory_store as memory_store
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


def test_save_persistent_memory_writes_atomically(tmp_path, monkeypatch):
    memory_file = tmp_path / "memory.json"
    monkeypatch.setattr(memory_store, "MEMORY_FILE", memory_file)

    assert memory_store.save_persistent_memory({"entries": [{"content": "Keep this"}]})

    payload = json.loads(memory_file.read_text(encoding="utf-8"))
    assert payload["entries"][0]["content"] == "Keep this"
    assert list(tmp_path.glob("*.tmp")) == []


def test_load_persistent_memory_preserves_corrupt_file(tmp_path, monkeypatch):
    memory_file = tmp_path / "memory.json"
    memory_file.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(memory_store, "MEMORY_FILE", memory_file)

    assert memory_store.load_persistent_memory() == empty_persistent_memory()
    assert not memory_file.exists()

    corrupt_files = list(tmp_path.glob("memory.corrupt-*.json"))
    assert len(corrupt_files) == 1
    assert corrupt_files[0].read_text(encoding="utf-8") == "{not valid json"
