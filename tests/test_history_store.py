import json

from fzastro_ai import history_store


def test_save_chat_history_writes_atomically_and_loads(tmp_path, monkeypatch):
    history_file = tmp_path / "history.json"
    monkeypatch.setattr(history_store, "HISTORY_FILE", history_file)

    history = [
        {
            "id": "chat-1",
            "title": "Hello",
            "created": "2026-01-01T00:00:00",
            "messages": [{"role": "user", "content": "Hello"}],
        }
    ]

    history_store.save_chat_history(history)

    assert json.loads(history_file.read_text(encoding="utf-8")) == history
    assert history_store.load_chat_history() == history
    assert list(tmp_path.glob("*.tmp")) == []


def test_save_chat_history_preserves_existing_file_when_serialization_fails(
    tmp_path, monkeypatch
):
    history_file = tmp_path / "history.json"
    original_history = [{"id": "existing", "messages": []}]
    history_file.write_text(
        json.dumps(original_history, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    monkeypatch.setattr(history_store, "HISTORY_FILE", history_file)

    history_store.save_chat_history([{"bad": object()}])

    assert json.loads(history_file.read_text(encoding="utf-8")) == original_history
    assert list(tmp_path.glob("*.tmp")) == []


def test_load_chat_history_preserves_corrupt_file_and_returns_empty_list(
    tmp_path, monkeypatch
):
    history_file = tmp_path / "history.json"
    history_file.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(history_store, "HISTORY_FILE", history_file)

    assert history_store.load_chat_history() == []

    assert not history_file.exists()
    corrupt_files = list(tmp_path.glob("history.corrupt-*.json"))
    assert len(corrupt_files) == 1
    assert corrupt_files[0].read_text(encoding="utf-8") == "{not valid json"


def test_create_chat_record_preserves_existing_preview_cleanup_behavior():
    record = history_store.create_chat_record(
        [
            {
                "role": "user",
                "content": "Question\n\n[INTERNET CONTEXT] noisy extracted context",
            }
        ]
    )

    assert record["title"] == "Question"
    assert record["messages"][0]["role"] == "user"
