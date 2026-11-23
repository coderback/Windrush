"""A project the candidate turns off (Project.not_in_documents) stays out of their CVs and cover letters."""
import asyncio
import json

import pytest

from app import agent, autopilot, doc_check
from app.models import Project

ON = {"name": "Algorender: DSA Visualiser", "url": "https://algorender.example", "problem_solved": "Sorting visualiser",
      "outcomes": "53 visualiser pages", "technologies": ["Next.js"], "summary": "", "is_ongoing": False}
OFF = {"name": "Windrush: Job-Ad Platform · AI London 2026", "url": "https://github.com/x/windrush",
       "problem_solved": "Reads job ads with an LLM-OFF-MARKER", "outcomes": "95.7% OFF-OUTCOME", "technologies": ["FastAPI"],
       "summary": "", "is_ongoing": False, "not_in_documents": True}
COMPANY_PROJECT = {"name": "RootLayer", "problem_solved": "Compliance audits", "technologies": ["Playwright"],
                   "not_in_documents": True}
PERSONA = {
    "core_info": {"first_name": "Ada", "last_name": "Lovelace", "city": "London"},
    "summary": "Graduate engineer.",
    "skills": [{"category": "Languages", "skills": ["Python", "TypeScript"]}],
    "history": [{"employer": "Rootlayer Ltd", "title": "Software Engineer", "start_date": "05/2026", "is_current": True,
                 "achievements": ["Built the audit pipeline at Rootlayer"]}],
    "education": [{"institution": "UWE Bristol", "degree": "BSc Computer Science", "end_date": "2025"}],
    "projects": [ON, OFF, COMPANY_PROJECT],
}
JOB = {"job_id": "1", "title": "Graduate Software Engineer", "company": "Acme", "description": "Python and Next.js",
       "location": "London"}


@pytest.fixture
def llm(monkeypatch):
    class Fake:
        reply = "{}"
        prompts: list[str] = []

    async def fake_llm(system, user, max_tokens=2048):
        Fake.prompts.append(system + "\n" + user)
        return Fake.reply

    async def no_research(*args, **kwargs):
        return ""
    Fake.prompts = []
    monkeypatch.setattr(agent, "_llm", fake_llm)
    monkeypatch.setattr(agent, "_research_company", no_research)
    return Fake


def test_the_profile_keeps_the_switch():
    assert Project(name="X").not_in_documents is False
    assert Project(**OFF).not_in_documents is True


def test_documents_persona_leaves_out_only_turned_off_projects():
    names = [p["name"] for p in agent.documents_persona(PERSONA)["projects"]]
    assert names == [ON["name"]]
    assert PERSONA["projects"][1] is OFF   # the profile itself is untouched
    plain = {**PERSONA, "projects": [ON]}
    assert agent.documents_persona(plain) is plain


def test_a_company_that_is_also_the_employer_stays_nameable():
    # 'RootLayer' is the employer 'Rootlayer Ltd': the role still names it, so only Windrush is a name to avoid.
    assert agent.off_project_names(PERSONA) == ["Windrush"]


@pytest.mark.parametrize("tool", ["generate_tailored_cv", "generate_cover_letter"])
def test_the_model_never_sees_a_turned_off_project(llm, tool):
    asyncio.run(agent.execute_tool(tool, {"job": JOB, "persona": PERSONA}))
    assert llm.prompts
    sent = "\n".join(llm.prompts)
    assert "Algorender" in sent
    for marker in ("OFF-MARKER", "OFF-OUTCOME", "Job-Ad Platform", "Compliance audits"):
        assert marker not in sent


def test_the_fallback_cv_has_no_turned_off_project(llm):
    cv = asyncio.run(agent.execute_tool("generate_tailored_cv", {"job": JOB, "persona": PERSONA}))["cv"]
    assert [p["name"] for p in cv["projects"]] == [ON["name"]]


def test_a_turned_off_project_the_model_lists_is_dropped(llm):
    llm.reply = json.dumps({
        "name": "Ada Lovelace", "summary": "Graduate engineer who builds visual tools.",
        "skills": [{"category": "Languages", "items": ["Python", "TypeScript"]}],
        "experience": [{"title": "Software Engineer", "employer": "Rootlayer Ltd", "start_date": "05/2026",
                        "end_date": "Present", "bullets": ["Built the audit pipeline at Rootlayer"]}],
        "projects": [{"name": "Algorender", "description": "Sorting visualiser", "tech": ["Next.js"]},
                     {"name": "Windrush", "description": "Reads job ads", "tech": ["FastAPI"]},
                     {"name": "RootLayer", "description": "Compliance audits", "tech": ["Playwright"]}]})
    cv = asyncio.run(agent.execute_tool("generate_tailored_cv", {"job": JOB, "persona": PERSONA}))["cv"]
    assert [p["name"] for p in cv["projects"]] == ["Algorender"]
    assert "Rootlayer Ltd" in [r["employer"] for r in cv["experience"]]


def test_a_letter_naming_a_turned_off_project_is_sent_back_for_revision(llm):
    llm.reply = json.dumps({"paragraphs": [
        "Building Algorender taught me how people read an algorithm step by step.",
        "Windrush showed I can ship a product end to end.",
        "I'd bring the same care to Acme."]})
    asyncio.run(agent.execute_tool("generate_cover_letter", {"job": JOB, "persona": PERSONA}))
    assert any("a project the candidate keeps off CVs and cover letters" in p for p in llm.prompts)


def test_check_off_projects_finds_whole_names_only():
    letter = {"paragraphs": ["Windrush showed I ship.", "Windrushing is not a word."]}
    found = doc_check.check_off_projects("cover_letter", letter, ["Windrush"])
    assert [f["field"] for f in found] == ["paragraphs.0"]
    cv = {"projects": [{"name": "Windrush", "description": "x"}], "summary": "Engineer."}
    assert [f["field"] for f in doc_check.check_off_projects("cv", cv, ["Windrush"])] == ["projects.0.name"]
    assert doc_check.check_off_projects("cv", cv, []) == []


def test_a_live_send_writes_fresh_documents_when_the_stored_ones_name_a_turned_off_project(monkeypatch):
    stored = {"cv": {"projects": [{"name": "Algorender"}]}, "letter": {"paragraphs": ["Algorender taught me."]},
              "cv_doc_id": "a" * 32, "letter_doc_id": "b" * 32}
    monkeypatch.setattr(autopilot, "_pdf", lambda doc_id: "/tmp/x.pdf")
    monkeypatch.setattr(autopilot.tracker, "autopilot_documents", lambda user_id, job_id: stored)
    assert autopilot._earlier_documents("u", {"id": "1"}, PERSONA) is stored
    stored["letter"] = {"paragraphs": ["Windrush taught me."]}
    assert autopilot._earlier_documents("u", {"id": "1"}, PERSONA) is None
    stored["letter"] = {"paragraphs": ["Algorender taught me."]}
    stored["cv"] = {"projects": [{"name": "RootLayer"}]}
    assert autopilot._earlier_documents("u", {"id": "1"}, PERSONA) is None
