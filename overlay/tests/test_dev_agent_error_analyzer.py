from fzastro_ai.dev_agent.error_analyzer import analyze_failure_output


def test_analyze_failure_output_extracts_files_and_causes():
    output = '''___ test_startup_imports ___
Traceback (most recent call last):
  File "D:\\Dropbox\\AI\\fzastro_ai\\__init__.py", line 2, in <module>
    missing
AttributeError: module 'fzastro_ai' has no attribute '__version__'
'''

    summary = analyze_failure_output(output)

    assert summary.headline.startswith("1 pytest failure")
    assert "fzastro_ai/__init__.py" in summary.files
    assert summary.likely_causes
