"""AI exposure: one published score per role, matched by occupation, and "not enough data" instead of a made-up number."""
import asyncio
import json
import sqlite3

import pytest

from app import agent, job_searcher, jobs_db, risk_scorer, tracker
from conftest import make_job


# ── Titles to occupations, as they appear on real job ads ─────────────────────

@pytest.mark.parametrize("title, occupation", [
    ("Graduate Software Engineer", "Software Developers"),
    ("Junior Software Engineer", "Software Developers"),
    ("Forex Associate Software Engineer (Fresh Graduate)", "Software Developers"),
    ("Software Engineer Graduate Scheme (Manchester)", "Software Developers"),
    ("Backend Engineer", "Software Developers"),
    ("Back End Engineer", "Software Developers"),
    ("Full Stack Developer", "Software Developers"),
    ("Energy Trading Full Stack Engineer", "Software Developers"),
    ("DevOps Engineer", "Software Developers"),
    ("Site Reliability Engineer", "Software Developers"),
    ("ML Ops Engineer II", "Software Developers"),
    ("Quantitative Developer", "Software Developers"),
    ("Agent Deployment Engineer", "Software Developers"),
    ("Frontend Developer", "Web Developers"),
    ("AI Engineer", "Computer and Information Research Scientists"),
    ("Machine Learning Engineer", "Computer and Information Research Scientists"),
    ("Research Engineer", "Computer and Information Research Scientists"),
    ("Data Scientist", "Data Scientists"),
    ("Data Analyst", "Data Scientists"),
    ("Data Engineer", "Database Architects"),
    ("Technology Graduate Programme Associate (Data Engineer)", "Database Architects"),
    ("Quantitative Researcher", "Financial Specialists, All Other"),
    ("Business Analyst", "Management Analysts"),
    ("Cyber Security Engineer Graduate Scheme (Leeds)", "Information Security Analysts"),
    ("2027 Graduate Scheme, Cyber Security", "Information Security Analysts"),
    ("Graduate Mechanical Engineer", "Mechanical Engineers"),
    ("Graduate Electronics Engineer", "Electronics Engineers, Except Computer"),
    ("Data Science &amp; Analytics Graduate Scheme", "Data Scientists"),
    ("Graduate Physicist", "Physicists"),
])
def test_a_title_finds_its_occupation(title, occupation):
    assert risk_scorer.occupation_for(title)["name"] == occupation


@pytest.mark.parametrize("title", [
    "Graduate Program",
    "2027 Technology Graduate Programme",
    "Graduate Analyst Programme - Capabilities",
    "Graduate Trainee - Engineering",
    "2027 Marketing Graduate Programme",
    "Information Technology Graduate Jobs in London",
    "Consultant",
    "Software Engineer / Data Scientist",
    "Data Science &amp; Software Graduate Engineer",
    "",
])
def test_a_title_that_doesnt_clearly_belong_to_one_occupation_isnt_matched(title):
    assert risk_scorer.occupation_for(title) is None


@pytest.mark.parametrize("title", ["Developer Advocate", "Graduate AI Consultant", "Stack Engineer", "Algorithm Developer"])
def test_odd_entries_in_the_title_list_are_not_believed(title):
    assert risk_scorer.occupation_for(title) is None


# ── The score ─────────────────────────────────────────────────────────────────

def test_the_score_is_the_published_one():
    published = risk_scorer.ECONOMIC_INDEX["15-1252"]["overall_exposure"]
    for title in ("Software Engineer", "Graduate Software Engineer", "Backend Engineer"):
        assert risk_scorer.occupation_exposure(title) == published


def test_a_published_zero_is_not_enough_data_rather_than_safe():
    occupation = risk_scorer.occupation_for("Chef")
    assert risk_scorer.ECONOMIC_INDEX[occupation["code"]]["overall_exposure"] == 0
    assert occupation["exposure"] is None and occupation["name"]


def test_no_match_is_not_a_default_score():
    assert risk_scorer.occupation_exposure("Graduate Program") is None
    assert risk_scorer.exposure_fields("Graduate Program") == {"exposure_score": None, "exposure_occupation": None}


def test_a_job_names_the_occupation_its_score_comes_from():
    fields = risk_scorer.exposure_fields("Data Scientist")
    assert fields == {"exposure_score": risk_scorer.ECONOMIC_INDEX["15-2051"]["overall_exposure"],
                      "exposure_occupation": "Data Scientists"}


def test_stored_jobs_show_the_current_score_not_the_old_placeholder(db, ollama):
    jobs_db.add_jobs([make_job(1, "Graduate Program"), make_job(2, "Software Engineer")])
    con = sqlite3.connect(jobs_db._DB_PATH)
    con.execute("UPDATE jobs SET exposure_score = 0.5")
    con.commit()
    con.close()

    listed = {j["title"]: j for j in jobs_db.get_jobs(limit=10)[0]}
    assert listed["Graduate Program"]["exposure_score"] is None
    assert listed["Software Engineer"]["exposure_occupation"] == "Software Developers"
    opened = jobs_db.get_job(listed["Graduate Program"]["id"])
    assert opened["exposure_score"] is None and opened["exposure_occupation"] is None


def test_the_bundled_jobs_get_a_score_or_none():
    jobs = job_searcher._load_fixture()
    assert all(j["exposure_score"] is None or 0 < j["exposure_score"] < 1 for j in jobs)
    assert all("exposure_occupation" in j for j in jobs)


# ── The careers page ──────────────────────────────────────────────────────────

PERSONA = {
    "preferences": {"target_titles": ["Graduate Software Engineer", "Graduate Program"]},
    "history": [{"title": "Chef", "employer": "A"}, {"title": "graduate software engineer", "employer": "B"}],
}


def test_each_role_gets_its_score_or_says_why_not():
    roles = {r["title"]: r for r in risk_scorer.career_exposure(PERSONA)["roles"]}
    assert roles["Graduate Software Engineer"] == {
        "title": "Graduate Software Engineer", "kind": "target", "occupation": "Software Developers",
        "exposure": round(risk_scorer.ECONOMIC_INDEX["15-1252"]["overall_exposure"] * 100)}
    assert roles["Graduate Program"]["occupation"] is None and roles["Graduate Program"]["exposure"] is None
    assert roles["Chef"]["kind"] == "past" and roles["Chef"]["occupation"] and roles["Chef"]["exposure"] is None


def test_a_role_listed_twice_appears_once():
    titles = [r["title"].lower() for r in risk_scorer.career_exposure(PERSONA)["roles"]]
    assert titles.count("graduate software engineer") == 1


def test_evidence_comes_from_the_first_target_that_has_some():
    persona = {"preferences": {"target_titles": ["Graduate Program", "Data Scientist"]}}
    evidence = risk_scorer.career_exposure(persona)["evidence"]
    assert evidence["role"] == "Data Scientist" and evidence["occupation"] == "Data Scientists"
    assert evidence["most_handed_to_ai"][0]["handed_to_ai"] >= evidence["least_handed_to_ai"][0]["handed_to_ai"]


def test_no_target_means_no_evidence():
    assert risk_scorer.career_exposure({"history": [{"title": "Data Scientist"}]})["evidence"] is None


def test_evidence_holds_only_occupations_with_steady_figures():
    for code, entry in risk_scorer.EVIDENCE.items():
        assert code in risk_scorer.ECONOMIC_INDEX or len(code) == 7
        shown = entry["most_handed_to_ai"] + entry["least_handed_to_ai"]
        assert entry["tasks_seen"] >= 4 and len({t["task"] for t in shown}) == len(shown)


def test_the_page_reads_the_persona_without_calling_the_model(client, user, monkeypatch):
    async def no_model(*a, **k):
        raise AssertionError("the model was called")
    monkeypatch.setattr(agent, "_llm", no_model)
    monkeypatch.setattr(agent, "_llm_json", no_model)
    con = sqlite3.connect(tracker._DB_PATH)
    con.execute("UPDATE users SET persona = ? WHERE id = ?", (json.dumps(PERSONA), user))
    con.commit()
    con.close()

    r = client.get("/careers/exposure")

    assert r.status_code == 200
    assert {x["title"] for x in r.json()["roles"]} >= {"Graduate Software Engineer", "Chef"}
    assert r.json()["evidence"]["occupation"] == "Software Developers"


def test_the_old_skill_scores_are_gone(client):
    assert client.post("/score-skills").status_code in (404, 405)


# ── The roadmap ───────────────────────────────────────────────────────────────

def _roadmap_prompt(monkeypatch, persona):
    seen = {}

    async def fake_llm(system, user, max_tokens=2048):
        seen.update(system=system, user=user)
        return json.dumps({"items": []})
    monkeypatch.setattr(agent, "_llm", fake_llm)
    asyncio.run(agent.execute_tool("generate_skill_roadmap", {"persona": persona}))
    return seen


def test_the_roadmap_gets_the_target_occupations_evidence_as_a_hint(monkeypatch):
    persona = {"preferences": {"target_titles": ["Software Engineer"]}, "skills": [{"category": "x", "skills": ["Python", "SQL"]}]}
    seen = _roadmap_prompt(monkeypatch, persona)
    task = risk_scorer.EVIDENCE["15-1252"]["most_handed_to_ai"][0]["task"]
    assert "Usage evidence for Software Developers" in seen["user"] and task in seen["user"]
    assert "never quote its figures" in seen["system"]
    assert "%" not in seen["user"]


def test_the_roadmap_still_knows_the_skills_it_must_not_repeat(monkeypatch):
    seen = _roadmap_prompt(monkeypatch, {"skills": [{"category": "x", "skills": ["Python", "SQL"]}]})
    assert "Skills they already list: Python, SQL" in seen["user"]


def test_the_roadmap_works_without_evidence(monkeypatch):
    seen = _roadmap_prompt(monkeypatch, {"preferences": {"target_titles": ["Graduate Program"]}})
    assert "Usage evidence" not in seen["user"]
