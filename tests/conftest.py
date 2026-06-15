"""Pytest configuration for FZAstro AI.

The app normally writes runtime files into the user's AppData folder. Tests use an
isolated temporary folder by default so importing fzastro_ai.config is safe.
"""

import os
import tempfile
from pathlib import Path

import pytest
import sys

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_TEST_APP_DIR = Path(tempfile.gettempdir()) / f"fzastroai_pytest_{os.getpid()}"
os.environ.setdefault("FZASTRO_APP_DIR", str(_TEST_APP_DIR))


@pytest.fixture
def project_root() -> Path:
    """Return the repository root for release workflow script tests."""
    return _PROJECT_ROOT
