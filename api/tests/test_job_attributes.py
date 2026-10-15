"""LLM-read job attributes: validation of the model's answer, merging with the regex readers, the worker."""
import asyncio
import sqlite3

import pytest
from conftest import make_job

from app import agent, job_attributes, jobs_db
from app.sponsorship import Signals

AD = ("We're hiring a Graduate Engineer. You will need at least 1 year of Python. "
      "Unfortunately we are unable to offer visa sponsorship for this role. "
      "The successful candidate must obtain Security Check (SC) clearance.")


def _answer(**overrides):
    return {"seniority": "junior", "years_experience_min": 1, "degree": "required", "sponsorship": "not_offered",
            "sponsorship_quote": "Unfortunately we are unable to offer visa sponsorship for this role.",
            "clearance": "SC", "clearance_quote": "The successful candidate must obtain Security Check (SC) clearance.",
            **overrides}


def test_a_well_formed_answer_is_kept():
    assert job_attributes.parse(_answer(), "Graduate Engineer", AD) == {
        "seniority": "junior", "years_experience_min": 1, "degree": "required", "sponsorship": "not_offered",
        "sponsorship_evidence": "Unfortunately we are unable to offer visa sponsorship for this role.",
        "clearance": "SC"}


@pytest.mark.parametrize("overrides, field, expected", [
    ({"sponsorship_quote": "We sponsor all visas gladly."}, "sponsorship", ""),     # not in the ad: dropped
    ({"sponsorship_quote": "visa sponsorship"}, "sponsorship", ""),                 # too short to check
    ({"sponsorship_quote": "UNFORTUNATELY  we are <b>unable</b> to offer visa sponsorship"},
     "sponsorship", "not_offered"),                                                  # case / spacing / markup
    ({"clearance_quote": "Must hold DV clearance."}, "clearance", ""),
    ({"clearance": "other", "clearance_quote": "must obtain Security Check (SC) clearance"}, "clearance", "unspecified"),
    ({"clearance": "none", "clearance_quote": ""}, "clearance", ""),
    ({"seniority": "principal"}, "seniority", None),
    ({"years_experience_min": "3"}, "years_experience_min", None),
    ({"years_experience_min": 99}, "years_experience_min", None),
    ({"years_experience_min": True}, "years_experience_min", None),
    ({"degree": "maybe"}, "degree", None),
])
def test_the_answer_is_validated(overrides, field, expected):
    assert job_attributes.parse(_answer(**overrides), "Graduate Engineer", AD)[field] == expected


@pytest.mark.parametrize("raw", [None, [], "junior", {}, {"seniority": "?", "sponsorship": "offered"}])
def test_an_unusable_answer_is_none(raw):
    assert job_attributes.parse(raw, "Engineer", AD) is None


def test_merge_prefers_the_quoted_reading_and_the_stricter_clearance():
    regex = Signals("offered", "Visa sponsorship is available.", "SC")
    llm = job_attributes.parse(_answer(clearance="DV", clearance_quote="must obtain Security Check (SC) clearance"),
                               "Graduate Engineer", AD)
    merged = job_attributes.merge("mid", regex, llm, llm_seniority=True)
    assert merged == {"level": "junior", "sponsorship": "not_offered",
                      "sponsorship_evidence": "Unfortunately we are unable to offer visa sponsorship for this role.",
                      "clearance": "DV", "years_min": 1, "degree": "required"}

    unsure = dict(llm, sponsorship="", sponsorship_evidence="", clearance="", seniority=None)
    merged = job_attributes.merge("mid", regex, unsure, llm_seniority=True)
    assert (merged["level"], merged["sponsorship"], merged["clearance"]) == ("mid", "offered", "SC")
    assert job_attributes.merge("mid", regex, llm, llm_seniority=False)["level"] == "mid"
    assert job_attributes.merge("senior", Signals(), None, llm_seniority=True) == {
        "level": "senior", "sponsorship": "", "sponsorship_evidence": "", "clearance": "", "years_min": None,
        "degree": ""}


def test_extract_sends_only_the_ad_and_survives_a_failed_call(monkeypatch):
    sent = {}

    async def fake(system, user, max_tokens=2048, label=""):
        sent["user"] = user
        return _answer()
    monkeypatch.setattr(agent, "_llm_json", fake)
    got = asyncio.run(job_attributes.extract("Graduate Engineer", "Acme", AD + " x" * 10_000))
    assert got["sponsorship"] == "not_offered"
    assert sent["user"].startswith("Title: Graduate Engineer\nCompany: Acme\n\nAdvert:\n")
    assert len(sent["user"]) < 12_100                                    # long ads are cut

    async def boom(*args, **kwargs):
        raise RuntimeError("rate limited")
    monkeypatch.setattr(agent, "_llm_json", boom)
    assert asyncio.run(job_attributes.extract("Engineer", "Acme", AD)) is None


@pytest.mark.parametrize("env, backend, on", [
    ({}, "azure", True), ({}, "ollama", False), ({"JOB_ATTRIBUTES_LLM": "1"}, "ollama", True),
    ({"JOB_ATTRIBUTES_LLM": "0"}, "azure", False),
])
def test_on_by_default_except_for_the_local_model(monkeypatch, env, backend, on):
    monkeypatch.delenv("JOB_ATTRIBUTES_LLM", raising=False)
    monkeypatch.setenv("LLM_BACKEND", backend)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert job_attributes.enabled() is on


# ── The worker ───────────────────────────────────────────────────────────────

@pytest.fixture
def stored(db, ollama):
    jobs_db.add_jobs([make_job(1, "Software Engineer", "Acme", description=AD, level=None)])
    (job_id,) = sqlite3.connect(jobs_db._DB_PATH).execute("SELECT id FROM jobs").fetchone()
    return job_id


def _fake_extract(monkeypatch, answers):
    calls = []

    async def fake(title, company, description):
        calls.append(title)
        answer = answers.pop(0) if answers else None
        return job_attributes.parse(answer, title, description) if answer else None
    monkeypatch.setattr(job_attributes, "extract", fake)
    return calls


def test_the_worker_stores_the_models_reading(stored, monkeypatch):
    calls = _fake_extract(monkeypatch, [_answer(seniority="senior", years_experience_min=6)])
    assert asyncio.run(job_attributes.extract_pending()) == (1, 1)
    job = jobs_db.get_job(stored)
    assert (job["level"], job["years_min"], job["degree"], job["sponsorship"], job["clearance"]) == (
        "senior", 6, "required", "not_offered", "SC")
    assert asyncio.run(job_attributes.extract_pending()) == (0, 0) and calls == ["Software Engineer"]

    row = jobs_db.get_jobs(limit=5)[0][0]
    assert (row["years_min"], row["degree"]) == (6, "required")


def test_a_job_the_model_keeps_failing_on_is_left_after_three_tries(stored, monkeypatch):
    calls = _fake_extract(monkeypatch, [])
    for _ in range(4):
        asyncio.run(job_attributes.extract_pending())
    assert len(calls) == 3
    assert jobs_db.get_job(stored)["sponsorship"] == "not_offered"        # the regex reading stands


def test_a_fetched_full_ad_is_read_again(stored, monkeypatch):
    _fake_extract(monkeypatch, [_answer(), _answer(seniority="mid", years_experience_min=3)])
    asyncio.run(job_attributes.extract_pending())
    jobs_db.update_description(stored, AD + " You'll bring 3+ years of commercial experience.")
    assert asyncio.run(job_attributes.extract_pending()) == (1, 1)
    assert jobs_db.get_job(stored)["years_min"] == 3
