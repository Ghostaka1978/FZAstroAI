from fzastro_ai.routing.intent_detection import (
    build_web_query,
    extract_last_python_code_block_from_text,
    extract_python_code_from_text,
    is_python_execution_request,
    is_python_generate_and_test_request,
    python_code_has_risky_auto_actions,
)


def test_python_execution_commands_are_detected():
    assert is_python_execution_request("/run-python\nprint('ok')")
    assert is_python_execution_request("/run-py: print(2 + 2)")
    assert is_python_execution_request("/py print('inline')")
    assert not is_python_execution_request("please write python code")


def test_generate_and_test_request_is_detected_without_urls():
    assert is_python_generate_and_test_request("Write a Python function and test it")
    assert is_python_generate_and_test_request("Create a python script and run it")
    assert not is_python_generate_and_test_request(
        "Summarize https://example.com/python-test"
    )


def test_python_code_extraction_prefers_python_fences():
    text = """
Here is code:

```text
not_python = maybe
```

```python
print('hello')
```
"""
    assert extract_python_code_from_text(text) == "print('hello')"
    assert extract_last_python_code_block_from_text(text) == "print('hello')"


def test_risky_auto_actions_are_blocked_for_generated_python():
    assert python_code_has_risky_auto_actions(
        "import subprocess\nsubprocess.run(['cmd'])"
    )
    assert python_code_has_risky_auto_actions("open('x.txt', 'w').write('bad')")
    assert not python_code_has_risky_auto_actions("for i in range(3):\n    print(i)")


def test_risky_auto_actions_detect_common_bypasses():
    assert python_code_has_risky_auto_actions(
        "from pathlib import Path\nPath('x.txt').write_text('bad')"
    )
    assert python_code_has_risky_auto_actions(
        "import os as operating_system\noperating_system.popen('whoami').read()"
    )
    assert python_code_has_risky_auto_actions(
        "getattr(__import__('os'), 'system')('echo bad')"
    )
    assert python_code_has_risky_auto_actions("importlib.import_module('subprocess')")


def test_safe_auto_run_math_code_is_allowed():
    assert not python_code_has_risky_auto_actions(
        "from math import sqrt\nprint(round(sqrt(9), 2))"
    )


def test_stock_price_query_normalization():
    assert (
        build_web_query("crm stock price")
        == "CRM stock price quote marketwatch yahoo finance nasdaq"
    )
