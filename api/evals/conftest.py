"""
Model evaluations call the real LLM, so they only run when asked for:

    cd api && set -a && . ../.env && set +a && WINDRUSH_LLM_EVAL=1 pytest evals

They live outside tests/ so the test suite's fake-LLM environment (tests/conftest.py) never applies.
"""
import os
import sys

import pytest

# Reuse labelled cases that the regex tests already hold.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tests"))


def pytest_collection_modifyitems(config, items):
    if os.environ.get("WINDRUSH_LLM_EVAL") == "1":
        return
    skip = pytest.mark.skip(reason="calls the real LLM: set WINDRUSH_LLM_EVAL=1 with the LLM settings from .env")
    for item in items:
        item.add_marker(skip)
