"""Browser-agent configuration that doesn't need a browser."""
from importlib.metadata import version

import pytest
from browser_use.utils import match_url_with_domain_pattern

import app.browser_agent as ba


def test_pinned_browser_use_version():
    # browser_agent.py targets the 0.11 CDP API — upgrading needs a deliberate port + `pytest -m browser`.
    assert version("browser-use") == "0.11.13"


@pytest.mark.parametrize("backend, provider", [("claude", "anthropic"), ("groq", "groq"), ("ollama", "ollama")])
def test_llm_factory_uses_browser_use_native_wrappers(monkeypatch, backend, provider):
    monkeypatch.setattr(ba, "_BACKEND", backend)
    assert ba._make_browser_llm().provider == provider


def test_credential_scope_is_the_job_host_over_https():
    scope = ba._credential_scope("https://www.boards.greenhouse.io/acme/jobs/1")
    assert scope == "https://*.boards.greenhouse.io"
    assert match_url_with_domain_pattern("https://boards.greenhouse.io/acme/login", scope)
    assert not match_url_with_domain_pattern("https://evil.example/x", scope)
    assert not match_url_with_domain_pattern("http://boards.greenhouse.io/x", scope)


def test_task_carries_the_placeholder_not_the_password():
    task = ba._build_task("https://x.example/job", {"core_info": {"first_name": "Ada"}}, "", "a@x.com", "hunter2", "")
    assert "hunter2" not in task and "<secret>job_password</secret>" in task
    assert "DO NOT SUBMIT" in task
