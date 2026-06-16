from fzastro_ai.conversation_context import build_recent_chat_context


def test_build_recent_chat_context_includes_recent_turns():
    context = build_recent_chat_context(
        [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "second"},
        ]
    )

    assert "[RECENT CHAT CONTEXT]" in context
    assert "USER: first" in context
    assert "ASSISTANT: second" in context


def test_build_recent_chat_context_omits_large_attachment_body():
    body = (
        "Inspect file\n\n"
        "Attached file: demo.py\n"
        "Attachment metadata:\n"
        "- Filename: demo.py\n\n"
        "BEGIN ATTACHED FILE: demo.py\n"
        "~~~python\n"
        "print('large body')\n"
        "~~~\n"
        "END ATTACHED FILE: demo.py"
    )

    context = build_recent_chat_context([{"role": "user", "content": body}])

    assert "BEGIN ATTACHED FILE: demo.py" in context
    assert "previous attachment body omitted" in context
    assert "print('large body')" not in context
