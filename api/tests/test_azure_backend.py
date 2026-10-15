"""LLM_BACKEND=azure: a reasoning-model deployment used for every LLM feature (no network here)."""
import asyncio
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from openai import AsyncOpenAI

import app.browser_agent as ba
from app import agent, azure_config

API_DIR = Path(__file__).resolve().parents[1]
AZURE_ENV = {
    "AZURE_OPENAI_ENDPOINT": "https://example-resource.openai.azure.com/",
    "AZURE_OPENAI_API_KEY": "test-azure-key",
    "AZURE_OPENAI_DEPLOYMENT": "test-deployment",
}
# What a reasoning model rejects (400) — none of it may reach Azure.
UNSUPPORTED = ("max_tokens", "temperature", "top_p", "frequency_penalty")


@pytest.fixture
def azure_env(monkeypatch):
    for name, value in AZURE_ENV.items():
        monkeypatch.setenv(name, value)
    for name in ("AZURE_OPENAI_API_VERSION", "AZURE_OPENAI_REASONING_EFFORT"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def on_azure(azure_env, monkeypatch):
    monkeypatch.setattr(agent, "_BACKEND", "azure")
    monkeypatch.setattr(agent, "_AZURE", azure_config.load())


class FakeCompletions:
    def __init__(self, content: str = "{}"):
        self.calls: list[dict] = []
        self.content = content

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        message = SimpleNamespace(content=self.content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")], usage=None)


@pytest.fixture
def fake_client(monkeypatch):
    completions = FakeCompletions()
    monkeypatch.setattr(agent, "client", SimpleNamespace(chat=SimpleNamespace(completions=completions)))
    return completions


# ── Text features (agent.py) ────────────────────────────────────────────────

def test_backend_factory_builds_an_azure_client_for_the_deployment(azure_env):
    client, anthropic_client, model = agent._make_client("azure")
    assert isinstance(client, AsyncOpenAI) and anthropic_client is None
    assert str(client.base_url) == "https://example-resource.openai.azure.com/openai/v1/"
    assert client.api_key == "test-azure-key"
    assert model == "test-deployment"


def test_param_helper_translates_for_azure(on_azure):
    assert agent._chat_params(max_tokens=2048, temperature=0.2, top_p=0.9) == {
        "max_completion_tokens": 2048 + azure_config.REASONING_HEADROOM["low"],
        "reasoning_effort": "low",
        "response_format": {"type": "json_object"},
    }


@pytest.mark.parametrize("effort, headroom", [("none", 1024), ("medium", 8192), ("high", 16384), ("future", 32768)])
def test_reasoning_headroom_follows_the_configured_effort(azure_env, monkeypatch, effort, headroom):
    monkeypatch.setenv("AZURE_OPENAI_REASONING_EFFORT", effort)
    monkeypatch.setattr(agent, "_BACKEND", "azure")
    monkeypatch.setattr(agent, "_AZURE", azure_config.load())
    assert agent._chat_params(max_tokens=1024) == {"max_completion_tokens": 1024 + headroom, "reasoning_effort": effort,
                                                    "response_format": {"type": "json_object"}}


@pytest.mark.parametrize("backend", ["groq", "ollama"])
def test_param_helper_leaves_other_backends_alone(monkeypatch, backend):
    monkeypatch.setattr(agent, "_BACKEND", backend)
    assert agent._chat_params(max_tokens=1024, temperature=0.3) == {"max_tokens": 1024, "temperature": 0.3}


def test_only_the_azure_request_changes(azure_env, monkeypatch, fake_client):
    monkeypatch.setattr(agent, "_BACKEND", "groq")
    asyncio.run(agent._llm("sys", "usr", max_tokens=1024))
    monkeypatch.setattr(agent, "_BACKEND", "azure")
    monkeypatch.setattr(agent, "_AZURE", azure_config.load())
    asyncio.run(agent._llm("sys", "usr", max_tokens=1024))
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "usr"}]
    assert fake_client.calls == [
        {"model": agent.LLM_MODEL, "messages": messages, "max_tokens": 1024},  # exactly as before
        {"model": agent.LLM_MODEL, "messages": messages, "max_completion_tokens": 1024 + 4096, "reasoning_effort": "low",
         "response_format": {"type": "json_object"}},
    ]


PERSONA = {"core_info": {"first_name": "Ada", "last_name": "Byron"}, "summary": "Graduate.",
           "skills": [{"category": "Languages", "skills": ["Python"]}],
           "history": [{"employer": "Acme", "title": "Intern", "start_date": "2024", "end_date": "2024"}]}
JOB = {"job_id": "1", "title": "Graduate Engineer", "company": "Acme", "description": "Python role"}


@pytest.mark.parametrize("tool, tool_input", [
    ("extract_cv_profile", {"cv_text": "Ada Byron, Python developer"}),
    ("score_ai_risk", {"skills": ["Python"]}),
    ("score_job_fit", {"jobs": [JOB], "persona": PERSONA}),
    ("generate_cover_letter", {"job": JOB, "persona": PERSONA}),
    ("generate_skill_roadmap", {"skill_risks": [{"skill": "Python", "exposure_score": 78}], "persona": PERSONA}),
    ("generate_tailored_cv", {"job": JOB, "persona": PERSONA}),
])
def test_every_feature_sends_reasoning_model_params_on_azure(on_azure, fake_client, monkeypatch, tool, tool_input):
    async def no_research(*args, **kwargs):
        return ""
    monkeypatch.setattr(agent, "_research_company", no_research)
    asyncio.run(agent.execute_tool(tool, tool_input))
    assert fake_client.calls
    for call in fake_client.calls:
        assert [p for p in UNSUPPORTED if p in call] == []
        assert call["model"] == agent.LLM_MODEL
        assert call["reasoning_effort"] == "low"
        assert call["response_format"] == {"type": "json_object"}  # every feature parses one JSON object
        # the feature's own answer budget (1024 or 2048) plus the reasoning headroom
        assert call["max_completion_tokens"] >= 1024 + azure_config.REASONING_HEADROOM["low"]


# ── Configuration ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("missing", [["AZURE_OPENAI_ENDPOINT"], ["AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT"]])
def test_missing_azure_settings_are_named(azure_env, monkeypatch, missing):
    for name in missing:
        monkeypatch.setenv(name, " ")
    with pytest.raises(RuntimeError) as exc:
        azure_config.load()
    message = str(exc.value)
    assert all(name in message for name in missing) and "test-azure-key" not in message


def test_settings_keep_the_key_out_of_their_repr(azure_env):
    cfg = azure_config.load()
    assert cfg.api_key == "test-azure-key" and "test-azure-key" not in repr(cfg)


def test_api_refuses_to_start_on_azure_without_its_settings():
    # Set empty rather than removed: browser-use calls load_dotenv() on import, which would fill
    # unset variables from any .env up the directory tree (it never overrides a set one).
    env = {**os.environ, "LLM_BACKEND": "azure", **{name: "" for name in azure_config.REQUIRED}}
    r = subprocess.run([sys.executable, "-c", "import app.agent"], cwd=API_DIR, env=env,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode != 0
    assert "LLM_BACKEND=azure" in r.stderr and all(name in r.stderr for name in azure_config.REQUIRED)


# ── Browser agent ───────────────────────────────────────────────────────────

def test_browser_llm_is_the_azure_wrapper_for_the_deployment(azure_env, monkeypatch):
    from browser_use import ChatAzureOpenAI
    monkeypatch.setattr(ba, "_BACKEND", "azure")
    llm = ba._make_browser_llm()
    assert isinstance(llm, ChatAzureOpenAI) and llm.provider == "azure"
    assert llm.model == llm.azure_deployment == "test-deployment"
    assert llm.azure_endpoint == AZURE_ENV["AZURE_OPENAI_ENDPOINT"]
    assert llm.api_version == azure_config.DEFAULT_API_VERSION


def test_browser_llm_sends_only_reasoning_model_params(azure_env, monkeypatch):
    from browser_use.llm.messages import UserMessage
    monkeypatch.setattr(ba, "_BACKEND", "azure")
    llm = ba._make_browser_llm()
    completions = FakeCompletions(content="ok")
    monkeypatch.setattr(llm, "get_client", lambda: SimpleNamespace(chat=SimpleNamespace(completions=completions)))
    asyncio.run(llm.ainvoke([UserMessage(content="hi")]))
    [call] = completions.calls
    assert [p for p in UNSUPPORTED if p in call] == []
    assert call["model"] == "test-deployment" and call["reasoning_effort"] == "low"
    assert call["max_completion_tokens"] == ba._STEP_OUTPUT_TOKENS + azure_config.REASONING_HEADROOM["low"]


# ── Content filter, finish reasons, roadmap target, company research ────────

def _bad_request(code):
    import httpx
    from openai import BadRequestError
    response = httpx.Response(400, request=httpx.Request("POST", "https://example-resource.openai.azure.com/openai/v1/"))
    return BadRequestError("rejected", response=response, body={"code": code, "message": "rejected"})


class RejectingCompletions(FakeCompletions):
    def __init__(self, code):
        super().__init__()
        self.code = code

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        raise _bad_request(self.code)


def test_azure_content_filter_rejection_falls_back_instead_of_failing(on_azure, monkeypatch, caplog):
    monkeypatch.setattr(agent, "client", SimpleNamespace(chat=SimpleNamespace(completions=RejectingCompletions("content_filter"))))
    assert asyncio.run(agent._llm("sys", "usr")) == ""
    assert "content filter" in caplog.text
    # The feature then takes its normal no-answer path rather than raising mid-stream.
    assert asyncio.run(agent.execute_tool("extract_cv_profile", {"cv_text": "Ada Byron"})) == {}


@pytest.mark.parametrize("backend, code", [("azure", "unsupported_parameter"), ("groq", "content_filter")])
def test_other_bad_requests_still_raise(on_azure, monkeypatch, backend, code):
    from openai import BadRequestError
    monkeypatch.setattr(agent, "_BACKEND", backend)
    monkeypatch.setattr(agent, "client", SimpleNamespace(chat=SimpleNamespace(completions=RejectingCompletions(code))))
    with pytest.raises(BadRequestError):
        asyncio.run(agent._llm("sys", "usr"))


@pytest.mark.parametrize("reason", ["length", "content_filter"])
def test_unfinished_answers_are_logged(on_azure, monkeypatch, caplog, reason):
    async def create(**kwargs):
        message = SimpleNamespace(content=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=reason)], usage=None)
    monkeypatch.setattr(agent, "client", SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    assert asyncio.run(agent._llm("sys", "usr")) == ""
    assert f"finish_reason={reason}" in caplog.text


def test_roadmap_targets_the_persona_titles_when_none_is_given(on_azure, fake_client):
    persona = {**PERSONA, "preferences": {"target_titles": ["Graduate Data Engineer", "Junior Data Engineer"]}}
    asyncio.run(agent.execute_tool("generate_skill_roadmap",
                                   {"skill_risks": [{"skill": "Python", "exposure_score": 78}], "persona": persona}))
    prompt = " ".join(m["content"] for m in fake_client.calls[0]["messages"])
    assert "Target role: Graduate Data Engineer, Junior Data Engineer" in prompt


def test_company_research_keeps_only_results_about_that_employer(monkeypatch):
    async def search(query, max_results=15):
        return [
            {"title": "Kestrel Ledger Analytics Ltd - About", "snippet": "Kestrel Ledger Analytics builds payment reconciliation tools for banks."},
            {"title": "Kestrel Audit", "snippet": "Kestrel Audit focuses on producing audit-ready reports for the full transaction population."},
            {"title": "Ledger news", "snippet": "A different ledger company announced quarterly results across the sector today."},
        ]
    monkeypatch.setattr(agent, "_ddg_search", search)
    research = asyncio.run(agent._research_company("Kestrel Ledger Analytics Ltd"))
    assert "payment reconciliation" in research
    assert "audit-ready" not in research and "quarterly results" not in research


def test_company_name_normalisation_drops_legal_suffixes():
    assert agent._normalise_company_name("Kestrel Ledger Analytics Ltd.") == "kestrel ledger analytics"
    assert agent._normalise_company_name("ACME Holdings PLC") == "acme"
