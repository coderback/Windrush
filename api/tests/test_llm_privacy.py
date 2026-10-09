"""Prompts sent to third-party LLMs must not carry credentials or sensitive personal data."""
import asyncio
import json

import pytest

from app import agent

FULL_PERSONA = {
    "core_info": {"first_name": "Ada", "last_name": "Lovelace", "dob": "1815-12-10", "email": "ada@private.example",
                  "phone": "+44 7700 900123", "address_line_1": "12 Secret Lane", "postcode": "SW1A 2AA",
                  "job_email": "ada.jobs@private.example", "job_password": "hunter2-Sup3rSecret",
                  "visa_status": "Citizen", "city": "London"},
    "diversity": {"gender": "female-marker", "ethnicity": "ethnicity-marker",
                  "sexual_orientation": "orientation-marker", "disability_status": "disability-marker"},
    "screening": {"salary_canonical": "salary-marker-90000", "why_this_role": "role-motivation-text"},
    "skills": [{"category": "Languages", "skills": ["Python"]}],
    "history": [{"employer": "Analytical Engines", "title": "Engineer", "start_date": "2020", "end_date": "2023"}],
    "summary": "Mathematician.",
}
SENSITIVE = ["hunter2-Sup3rSecret", "1815-12-10", "ada@private.example", "7700 900123", "12 Secret Lane",
             "SW1A 2AA", "ada.jobs@private.example", "female-marker", "ethnicity-marker", "orientation-marker",
             "disability-marker", "salary-marker-90000"]
JOB = {"job_id": "1", "title": "Engineer", "company": "Acme", "description": "Python role", "location": "London"}


def test_llm_persona_is_an_allowlist():
    slim = json.dumps(agent._llm_persona(FULL_PERSONA))
    assert [s for s in SENSITIVE if s in slim] == []
    for kept in ("Ada", "Python", "Analytical Engines", "Citizen", "role-motivation-text"):
        assert kept in slim


@pytest.fixture
def prompts(monkeypatch):
    sent: list[str] = []

    async def fake_llm(system, user, max_tokens=2048):
        sent.append(system + "\n" + user)
        return "{}"

    async def no_research(*args, **kwargs):
        return ""
    monkeypatch.setattr(agent, "_llm", fake_llm)
    monkeypatch.setattr(agent, "_research_company", no_research)
    return sent


@pytest.mark.parametrize("tool, tool_input", [
    ("score_job_fit", {"jobs": [JOB], "persona": FULL_PERSONA}),
    ("generate_cover_letter", {"job": JOB, "persona": FULL_PERSONA}),
    ("generate_tailored_cv", {"job": JOB, "persona": FULL_PERSONA}),
])
def test_prompts_carry_no_sensitive_data(prompts, tool, tool_input):
    asyncio.run(agent.execute_tool(tool, tool_input))
    assert prompts and [s for p in prompts for s in SENSITIVE if s in p] == []


def test_documents_still_get_contact_details_from_the_persona(prompts):
    cv = asyncio.run(agent.execute_tool("generate_tailored_cv", {"job": JOB, "persona": FULL_PERSONA}))
    letter = asyncio.run(agent.execute_tool("generate_cover_letter", {"job": JOB, "persona": FULL_PERSONA}))
    assert cv["cv"]["contact"]["email"] == "ada@private.example"
    assert letter["letter"]["contact"]["email"] == "ada@private.example"
