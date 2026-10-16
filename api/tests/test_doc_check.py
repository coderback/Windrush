"""Document checks: keywords against the ad, claims the persona doesn't back, style, ATS read-back."""
import asyncio
import copy
import json

import pytest

from app import agent, doc_check, tracker
from tests.test_documents import GRADUATE, needs_weasyprint

AD = {
    "title": "Graduate Backend Engineer",
    "company": "Northwind Labs",
    "description": "You'll build Python and FastAPI services on PostgreSQL, deployed with Docker and Kubernetes. "
                   "Experience with Redis or Kafka is a plus. Our team of 40 engineers ships daily.",
}


def _cv(**changes) -> dict:
    cv = agent._persona_to_cvdoc(copy.deepcopy(GRADUATE))
    cv.update(changes)
    return cv


# ── Matching terms and numbers ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, expected", [
    ("REST APIs in Python", {"REST", "Python"}),
    ("the rest of the team", set()),                       # an ordinary word, not REST
    ("JavaScript, not Java", {"JavaScript", "Java"}),
    ("PostgreSQL and MySQL", {"PostgreSQL", "MySQL"}),     # no bare SQL inside either name
    ("Postgres with k8s", {"PostgreSQL", "Kubernetes"}),   # aliases map to one name
    ("Go and gRPC; the go-live date", {"Go"}),
    ("GitHub Actions", {"GitHub Actions"}),                # not Git
    ("C++ and C# on .NET", {"C++", "C#", ".NET"}),
    ("Next, we ship", set()),
])
def test_terms_are_matched_as_whole_names(text, expected):
    assert doc_check.terms_in(text) == expected


def test_numbers_skip_years_and_dates_and_read_units():
    found = dict(doc_check.numbers_in("From 06/2024 in 2024: 40k readings, 52% to 81%, £2m, 2,500 users, 10x, "
                                      "300+ people, GPT-4 on S3"))
    assert found == {"40k": 40_000, "52%": 52, "81%": 81, "£2m": 2_000_000, "2,500": 2500, "10x": 10, "300+": 300}


# ── Keywords ──────────────────────────────────────────────────────────────────────────────────

def test_keywords_split_into_shown_worth_adding_and_gaps():
    cv = _cv(summary="Computer Science graduate who builds Python and FastAPI services.", experience=[], projects=[])
    cv["skills"] = [{"category": "Backend", "items": ["Python", "FastAPI", "PostgreSQL"]}]
    kw = doc_check.check_keywords("cv", cv, GRADUATE, AD)
    assert kw["matched"] == ["FastAPI", "PostgreSQL", "Python"]
    # Docker and Redis are in the persona, so the CV can show them; Kubernetes and Kafka are real gaps.
    assert kw["missing_have"] == ["Docker", "Redis"]
    assert kw["gaps"] == ["Kafka", "Kubernetes"]
    assert kw["score"] == 60                                # 3 of the 5 the candidate has


# ── Facts ─────────────────────────────────────────────────────────────────────────────────────

def test_claims_the_persona_backs_are_not_flagged():
    cv = _cv()
    cv["experience"][0]["bullets"] = ["Built a FastAPI service ingesting 40k sensor readings a day into PostgreSQL, "
                                      "and cut dashboard load time from 6 s to 1.5 s with Redis caching."]
    assert doc_check.check_facts("cv", cv, GRADUATE, AD) == []


def test_invented_numbers_technologies_employers_and_projects_are_flagged():
    cv = _cv()
    cv["experience"][0]["bullets"] = ["Cut latency by 35% by moving the service to Kubernetes."]
    cv["experience"].append({"title": "Engineer", "employer": "Initech", "bullets": []})
    cv["projects"].append({"name": "Quantum Ledger", "description": "A ledger.", "tech": ["Rust"]})
    found = {(f["kind"], f["value"]) for f in doc_check.check_facts("cv", cv, GRADUATE, AD)}
    assert found == {("number", "35%"), ("technology", "Kubernetes"), ("employer", "Initech"),
                     ("project", "Quantum Ledger"), ("technology", "Rust")}


def test_a_letter_may_quote_the_ad():
    letter = {"paragraphs": ["Your team of 40 engineers runs Kubernetes, and I have shipped FastAPI services.",
                             "I raised test coverage to 95%."]}
    found = [(f["kind"], f["value"]) for f in doc_check.check_facts("cover_letter", letter, GRADUATE, AD)]
    # The ad's own number and stack are fine to mention; a coverage figure the persona lacks isn't.
    assert found == [("number", "95%")]


def test_findings_name_the_field_they_are_in():
    cv = _cv()
    cv["summary"] = "Graduate with 7 years of Kotlin."
    f = doc_check.check_facts("cv", cv, GRADUATE, AD)
    assert {(x["field"], x["label"], x["value"]) for x in f} == {("summary", "Summary", "7"), ("summary", "Summary", "Kotlin")}


def test_machine_sounding_words_are_flagged():
    letter = {"paragraphs": ["I leveraged robust pipelines.", "A seamless handover."]}
    words = [(f["field"], f["value"].lower()) for f in doc_check.check_style("cover_letter", letter)]
    assert words == [("paragraphs.0", "leveraged"), ("paragraphs.0", "robust"), ("paragraphs.1", "seamless")]


# ── Endpoint and ATS read-back ────────────────────────────────────────────────────────────────

def test_check_endpoint_uses_the_signed_in_persona(client, user):
    tracker.update_user_persona(user, copy.deepcopy(GRADUATE))
    cv = _cv()
    cv["experience"][0]["bullets"] = ["Shipped 12 releases."]
    r = client.post("/documents/check", json={"type": "cv", "doc": cv, "job": AD, "ats": False})
    assert r.status_code == 200
    body = r.json()
    assert [(f["kind"], f["value"]) for f in body["facts"]] == [("number", "12")]
    assert "Kubernetes" in body["keywords"]["gaps"]
    assert body["ats"] is None
    assert client.post("/documents/check", json={"type": "memo", "doc": {}}).status_code == 400


@needs_weasyprint
def test_ats_reads_the_cv_back_from_its_pdf():
    report = doc_check.check_ats("cv", {**_cv(), "seniority": "junior"})
    by_name = {c["check"]: c for c in report["checks"]}
    assert all(c["ok"] for c in report["checks"]), report
    assert {"Text can be read", "Your name is at the top", "Email can be read", "Phone can be read",
            "Standard section headings, in order", "Every skill reads back", "Role dates read back",
            "Fits on 1 page"} <= set(by_name)
    assert report["pages"] == 1


@needs_weasyprint
def test_ats_reads_the_letter_back():
    letter = {"candidate_name": "Sam Okafor", "salutation": "Dear Hiring Manager,", "signoff": "Yours faithfully,",
              "paragraphs": ["I build backend services that keep working under uneven load. " * 3,
                             "Northwind's logistics APIs are the kind of problem I want to work on. " * 3]}
    report = doc_check.check_ats("cover_letter", letter)
    assert all(c["ok"] for c in report["checks"]), report


# ── Generation: skills top-up and the targeted revision ──────────────────────────────────────

@pytest.fixture
def replies(monkeypatch):
    """The model's replies in order (one per call); the prompts it was sent are kept too."""
    import asyncio as _asyncio  # noqa: F401

    class Q:
        queue: list[str] = []
        prompts: list[str] = []

    async def fake_llm(system, user, max_tokens=2048):
        Q.prompts.append(system + "\n" + user)
        return Q.queue.pop(0) if Q.queue else "{}"

    async def no_research(*args, **kwargs):
        return ""
    monkeypatch.setattr(agent, "_llm", fake_llm)
    monkeypatch.setattr(agent, "_research_company", no_research)
    return Q


def _model_cv(bullet: str) -> dict:
    return {
        "name": "Sam Okafor", "headline": "", "contact": {},
        "summary": "Computer Science graduate who builds Python and FastAPI services.",
        "skills": [{"category": "Languages", "items": ["Python", "TypeScript", "Java", "SQL"]},
                   {"category": "Backend", "items": ["FastAPI", "Node.js", "Spring Boot"]},
                   {"category": "Frontend", "items": ["React", "Next.js", "Tailwind CSS"]},
                   {"category": "Data", "items": ["PostgreSQL", "pandas"]},
                   {"category": "Testing", "items": ["pytest", "Jest", "Playwright"]},
                   {"category": "Tools", "items": ["Git", "GitHub Actions", "CI/CD"]}],
        "experience": [{"title": "Software Engineering Intern", "employer": "Brightwave Analytics",
                        "start_date": "06/2024", "end_date": "09/2024", "bullets": [bullet]}],
        "education": [], "certifications": [],
        "projects": [{"name": "Pantry Planner", "description": "A meal planner matching 12,000 recipes.", "tech": ["FastAPI"]}],
    }


def _text_reply(bullet: str) -> str:
    return json.dumps({"summary": "Computer Science graduate who builds Python and FastAPI services.",
                       "experience": [{"title": "Software Engineering Intern", "employer": "Brightwave Analytics",
                                       "bullets": [bullet]}],
                       "projects": [{"name": "Pantry Planner", "description": "A meal planner matching 12,000 recipes.",
                                     "tech": ["FastAPI"]}]})


def _generate_cv() -> dict:
    return asyncio.run(agent.execute_tool("generate_tailored_cv", {"job": AD, "persona": GRADUATE}))["cv"]


def test_skills_the_ad_wants_and_the_candidate_has_are_added(replies):
    replies.queue = [json.dumps(_model_cv("Built a FastAPI service ingesting 40k readings a day into PostgreSQL."))]
    cv = _generate_cv()
    rows = {g["category"]: g["items"] for g in cv["skills"]}
    # The ad asks for Docker and Redis; the profile lists both (Cloud, Data), the model left them out.
    assert "Redis" in rows["Data"]
    assert any("Docker" in items for items in rows.values())
    assert not any("Kubernetes" in items or "Kafka" in items for items in rows.values())   # real gaps stay out
    assert not any("scikit-learn" in items for items in rows.values())     # still the model's choice, topped up
    assert len(replies.prompts) == 1                         # nothing flagged, so no revision call


def test_an_invented_figure_is_revised_away(replies):
    replies.queue = [json.dumps(_model_cv("Cut API latency by 35% with Redis caching.")),
                     _text_reply("Cut dashboard load time from 6 s to 1.5 s with Redis caching.")]
    cv = _generate_cv()
    assert cv["experience"][0]["bullets"] == ["Cut dashboard load time from 6 s to 1.5 s with Redis caching."]
    assert "35%" in replies.prompts[1] and "isn't in your persona" in replies.prompts[1]


def test_a_revision_that_invents_something_new_is_dropped(replies):
    replies.queue = [json.dumps(_model_cv("Cut API latency by 35% with Redis caching.")),
                     _text_reply("Cut API latency with Redis caching across 9 services.")]
    cv = _generate_cv()
    assert cv["experience"][0]["bullets"] == ["Cut API latency by 35% with Redis caching."]   # original kept


def test_a_revision_in_the_wrong_shape_is_dropped(replies):
    replies.queue = [json.dumps(_model_cv("Cut API latency by 35% with Redis caching.")), json.dumps({"summary": "x"})]
    assert _generate_cv()["experience"][0]["bullets"] == ["Cut API latency by 35% with Redis caching."]


def test_a_letter_with_a_flagged_word_is_revised(replies):
    first = {"salutation": "Dear Hiring Manager,", "signoff": "Yours faithfully,", "headline": "Graduate",
             "paragraphs": ["I leverage FastAPI daily.", "Your team of 40 engineers ships daily."]}
    replies.queue = [json.dumps(first),
                     json.dumps({"paragraphs": ["I use FastAPI daily.", "Your team of 40 engineers ships daily."]})]
    letter = asyncio.run(agent.execute_tool("generate_cover_letter", {"job": AD, "persona": GRADUATE}))["letter"]
    assert letter["paragraphs"] == ["I use FastAPI daily.", "Your team of 40 engineers ships daily."]


# ── Critique and revise (writing quality) ─────────────────────────────────────────────────────

@pytest.fixture
def critique(monkeypatch, replies):
    monkeypatch.setattr(agent, "_DOC_CRITIQUE", {"cv", "letter"})
    return replies


GOOD_BULLET = "Built a FastAPI service ingesting 40k readings a day into PostgreSQL."


def _critique_reply(summary: str, bullet: str = GOOD_BULLET, issues=("Summary misses the ad's FastAPI focus",)) -> str:
    text = json.loads(_text_reply(bullet))
    text["summary"] = summary
    return json.dumps({"issues": list(issues), "revised": text})


def _generate(kind: str):
    tool = "generate_tailored_cv" if kind == "cv" else "generate_cover_letter"
    return asyncio.run(agent.execute_tool(tool, {"job": AD, "persona": GRADUATE}))


def test_a_critique_rewrite_that_holds_up_is_kept(critique):
    better = "Computer Science graduate building Python and FastAPI services on PostgreSQL."
    critique.queue = [json.dumps(_model_cv(GOOD_BULLET)), _critique_reply(better)]
    out = _generate("cv")
    assert out["cv"]["summary"] == better
    assert out["review"] == {"issues": ["Summary misses the ad's FastAPI focus"], "kept": True}
    assert "demanding recruiter" in critique.prompts[1] and "RELEVANCE" in critique.prompts[1]


def test_a_critique_rewrite_that_invents_a_claim_is_dropped(critique):
    critique.queue = [json.dumps(_model_cv(GOOD_BULLET)),
                      _critique_reply("Graduate who cut latency by 35% with FastAPI.")]
    out = _generate("cv")
    assert out["cv"]["summary"] == "Computer Science graduate who builds Python and FastAPI services."
    assert out["review"]["kept"] is False


def test_a_critique_rewrite_that_runs_long_is_dropped(critique):
    long_summary = "Computer Science graduate who builds Python and FastAPI services. " * 6
    critique.queue = [json.dumps(_model_cv(GOOD_BULLET)), _critique_reply(long_summary)]
    assert _generate("cv")["review"]["kept"] is False


def test_no_issues_leaves_the_cv_alone(critique):
    critique.queue = [json.dumps(_model_cv(GOOD_BULLET)), json.dumps({"issues": [], "revised": {}})]
    out = _generate("cv")
    assert out["cv"]["experience"][0]["bullets"] == [GOOD_BULLET]
    assert out["review"] == {"issues": [], "kept": False}


def test_the_letter_critique_rewrites_the_flagged_paragraph(critique):
    first = {"salutation": "Dear Hiring Manager,", "signoff": "Yours faithfully,", "headline": "Graduate",
             "paragraphs": ["I am writing to apply for this role.", "I build FastAPI services on PostgreSQL."]}
    critique.queue = [json.dumps(first), json.dumps({
        "issues": ["Opening is generic"],
        "paragraphs": ["Northwind's API platform is where I want to build.", "I build FastAPI services on PostgreSQL."]})]
    out = _generate("letter")
    assert out["letter"]["paragraphs"][0] == "Northwind's API platform is where I want to build."
    assert out["review"] == {"issues": ["Opening is generic"], "kept": True}
