"""Autopilot: which jobs it tries, when it sends a form and when it holds it for the user."""
import asyncio
import base64
import os
import uuid

import pytest
from conftest import make_job

from app import agent, autopilot, browser_agent, doc_check, doc_render, jobs_db, pdf_generator, tracker

JPEG = base64.b64encode(b"\xff\xd8\xff\xe0fake-jpeg").decode()
PERSONA = {"core_info": {"first_name": "Ada", "last_name": "Lovelace"},
           "preferences": {"preferred_locations": ["London"]}}
CLEAN = {"question": "Do you have the right to work in the UK?", "options": ["Yes", "No"], "kind": "fact",
         "source": "profile", "answer": "Yes", "because": "", "bank_id": "", "flags": []}


def _answer(question, source, answer="", kind="fact"):
    return {"question": question, "options": [], "kind": kind, "source": source, "answer": answer, "because": "",
            "bank_id": "", "flags": []}


# ── The rule ──────────────────────────────────────────────────────────────────

def test_a_clean_fill_can_go():
    filled = {"ready": True, "error": "", "questions": [CLEAN, _answer("Notice period", "saved", "Immediately")],
              "empty": []}
    assert autopilot.hold_reasons(filled, []) == []


@pytest.mark.parametrize("filled, expected", [
    ({"ready": True, "questions": [_answer("Do you need a visa?", "needs_you")]}, "1 question only you can answer"),
    ({"ready": True, "questions": [_answer("Why us?", "drafted", "Because…", "written")]},
     "1 written answer drafted for this job that you haven't read"),
    ({"ready": True, "questions": [CLEAN], "empty": ["Pronouns", "Salary"]}, "2 required fields still empty"),
    ({"ready": False, "questions": []}, "The agent couldn't finish the form"),
    ({"ready": True, "error": "page crashed", "questions": []}, "The agent hit a problem: page crashed"),
    ({"ready": True, "questions": [{**CLEAN, "flags": ["odd"]}]}, "didn't come from your saved answers or profile"),
    ({"ready": True, "questions": [CLEAN], "self_answered": ["What is your age bracket?: 18 to under 25"]},
     "1 answer the agent chose itself"),
])
def test_anything_new_or_missing_holds_the_form(filled, expected):
    reasons = autopilot.hold_reasons({"error": "", "empty": [], **filled}, [])
    assert len(reasons) == 1 and expected in reasons[0]


def test_a_document_claim_the_profile_doesnt_back_holds_the_form():
    persona = {"core_info": {"first_name": "Ada"}, "skills": [{"category": "Languages", "skills": ["Python"]}]}
    cv = {"summary": "Python and Kubernetes engineer", "experience": [], "projects": []}
    letter = {"paragraphs": ["I have used Python for 2 years."]}
    problems = autopilot.document_problems(cv, letter, persona, {"title": "Engineer", "description": ""})
    assert len(problems) == 2
    assert problems[0].startswith("The tailored CV") and "Kubernetes" in problems[0]
    assert problems[1].startswith("The cover letter") and "2" in problems[1]
    assert autopilot.hold_reasons({"ready": True, "error": "", "questions": [], "empty": []}, problems) == problems


@pytest.mark.parametrize("url, ats", [
    ("https://boards.greenhouse.io/acme/jobs/1", "Greenhouse"),
    ("https://job-boards.greenhouse.io/acme/jobs/1", "Greenhouse"),
    ("https://jobs.lever.co/acme/abc", "Lever"),
    ("https://jobs.ashbyhq.com/acme/abc", "Ashby"),
    ("https://apply.workable.com/acme/j/ABC/", "Workable"),
    ("http://boards.greenhouse.io/acme/jobs/1", ""),          # not https
    ("https://www.linkedin.com/jobs/view/1", ""),
    ("https://uk.indeed.com/viewjob?jk=1", ""),
    ("https://acme.wd3.myworkdayjobs.com/en-US/careers/job/1", ""),
    ("https://greenhouse.io.evil.example/jobs/1", ""),
    ("", ""),
])
def test_only_forms_on_the_supported_trackers(url, ats):
    assert autopilot.ats_of(url) == ats


def test_settings_are_checked():
    assert autopilot.clean_settings({"live": True, "daily_cap": 5, "min_fit": 60, "other": 1}) == \
        {"live": True, "daily_cap": 5, "min_fit": 60}
    for bad in ({"daily_cap": 0}, {"daily_cap": 11}, {"min_fit": 40}, {"min_fit": 80.5}, {"live": "yes"},
                {"enabled": 1}):
        with pytest.raises(ValueError):
            autopilot.clean_settings(bad)
    assert autopilot.clean_settings({"daily_cap": 99, "live": True}, strict=False) == {"live": True}


# ── A run, with the model and the browser faked ───────────────────────────────

URLS = {
    "alpha": "https://boards.greenhouse.io/alpha/jobs/1",
    "beta": "https://jobs.lever.co/beta/2",
    "gamma": "https://jobs.ashbyhq.com/gamma/3",
    "linked": "https://www.linkedin.com/jobs/view/4",
    "workday": "https://delta.wd3.myworkdayjobs.com/careers/job/5",
}


class World:
    """The fakes' script: each company's fit, and what its form leaves behind."""

    def __init__(self):
        self.fit = {name: (90, "strong") for name in URLS}
        self.forms = {name: {"questions": [CLEAN], "empty": [], "confirm": True} for name in URLS}
        self.filled: list[str] = []      # companies whose form was filled
        self.decided: dict[str, bool] = {}
        self.cv_paths: list[str] = []


@pytest.fixture
def world(db, ollama, monkeypatch):
    w = World()

    async def execute_tool(name, tool_input):
        if name == "score_job_fit":
            return {"ranked_jobs": [{"job_id": j["job_id"], "fit_score": w.fit[j["company"]][0],
                                     "level_match": w.fit[j["company"]][1], "reasoning": "why"}
                                    for j in tool_input["jobs"]]}
        if name == "generate_tailored_cv":
            return {"cv": {"summary": "Engineer"}, "template_id": "classic"}
        if name == "generate_cover_letter":
            return {"letter": {"salutation": "Dear Hiring Manager,", "paragraphs": ["I'd like to join."],
                               "signoff": "Yours faithfully,", "candidate_name": "Ada Lovelace"}, "research": ""}
        raise AssertionError(name)

    async def render_pdf(doc_type, doc, template_id=None):
        doc_id = uuid.uuid4().hex
        with open(pdf_generator.get_pdf_path(doc_id), "wb") as f:
            f.write(b"%PDF-1.4 fake")
        return doc_id

    async def ensure_full_description(job):
        return job

    async def apply_with_browser(job_url, persona, cover_letter, queue, frames, *, job_email, job_password, cv_path,
                                 cover_letter_path, answerer, decide):
        company = next(name for name, url in URLS.items() if url == job_url)
        w.filled.append(company)
        w.cv_paths.append(cv_path)
        assert cover_letter.startswith("Dear Hiring Manager,") and os.path.exists(cover_letter_path)
        form = w.forms[company]
        yield {"action": "Step 1: filling", "done": False}
        filled = {"ready": True, "error": "", "notes": "Filled it", "questions": form["questions"],
                  "empty": form["empty"]}
        final = {"action": "Filled in; not sent", "done": True, "submitted": False, "submit_attempted": False,
                 **filled, "form_screenshot": JPEG}
        send = await decide(filled)
        w.decided[company] = send
        if send:
            final.update(submit_attempted=True, submitted=form["confirm"], submit_detail="Thanks for applying",
                         confirm_screenshot=JPEG)
        yield final

    monkeypatch.setattr(agent, "execute_tool", execute_tool)
    monkeypatch.setattr(doc_render, "render_pdf", render_pdf)
    monkeypatch.setattr(jobs_db, "ensure_full_description", ensure_full_description)
    monkeypatch.setattr(browser_agent, "apply_with_browser", apply_with_browser)
    monkeypatch.setattr(doc_check, "check_facts", lambda *a, **k: [])
    jobs_db.add_jobs([make_job(i, f"Graduate Engineer {name}", name, url=url, description="Python")
                      for i, (name, url) in enumerate(URLS.items())])
    return w


@pytest.fixture
def ada(world):
    uid = tracker.create_user("ada@example.com", "h")
    tracker.update_user_persona(uid, PERSONA)
    return uid


def _run(uid, **settings):
    if settings:
        autopilot.save_settings(uid, settings)
    return asyncio.run(autopilot.run(uid))


def _runs(uid) -> dict[str, dict]:
    return {r["company"]: r for r in tracker.list_autopilot_runs(uid)}


def test_practice_mode_fills_but_never_sends(ada, world):
    result = _run(ada)
    assert sorted(world.filled) == ["alpha", "beta", "gamma"]            # LinkedIn and Workday never opened
    assert world.decided == {"alpha": False, "beta": False, "gamma": False}
    runs = _runs(ada)
    assert {r["outcome"] for r in runs.values()} == {"ready"} and all(r["practice"] for r in runs.values())
    assert result["counts"] == {"ready": 3}
    assert tracker.list_applications(ada) == []                           # practice leaves the tracker alone
    assert all(path and os.path.exists(path) for path in world.cv_paths)  # the tailored CV went up


def test_live_mode_sends_clean_forms_and_keeps_screenshots(ada, world):
    _run(ada, live=True)
    runs = _runs(ada)
    assert {name: r["outcome"] for name, r in runs.items()} == \
        {"alpha": "submitted", "beta": "submitted", "gamma": "submitted"}
    for run in runs.values():
        for which in ("form", "confirm"):
            with open(autopilot.screenshot_path({**run, "user_id": ada}, which), "rb") as f:
                assert f.read() == base64.b64decode(JPEG)
    apps = {a["company"]: a for a in tracker.list_applications(ada)}
    assert {a["status"] for a in apps.values()} == {"Applied"} and apps["alpha"]["notes"] == "Sent by autopilot."
    assert apps["alpha"]["questions"] == [CLEAN]
    assert autopilot.sent_last_day(ada) == 3


def test_the_daily_limit_stops_the_run(ada, world):
    _run(ada, live=True, daily_cap=2)
    assert sorted(r["outcome"] for r in _runs(ada).values()) == ["submitted", "submitted"]
    assert len(world.filled) == 2
    result = _run(ada)                                                    # same day: nothing more is tried
    assert "limit of 2 a day" in result["note"] and len(world.filled) == 2


def test_a_form_that_needs_the_user_is_held_with_reasons(ada, world):
    world.forms["alpha"]["questions"] = [CLEAN, _answer("Do you hold SC clearance?", "needs_you")]
    world.forms["beta"]["empty"] = ["Preferred pronouns"]
    _run(ada, live=True)
    runs = _runs(ada)
    assert runs["alpha"]["outcome"] == "needs_you" and "Do you hold SC clearance?" in runs["alpha"]["reasons"][0]
    assert runs["beta"]["outcome"] == "needs_you" and "Preferred pronouns" in runs["beta"]["reasons"][0]
    assert runs["gamma"]["outcome"] == "submitted"
    assert world.decided == {"alpha": False, "beta": False, "gamma": True}
    apps = {a["company"]: a for a in tracker.list_applications(ada)}
    assert apps["alpha"]["status"] == "Pending Review" and apps["gamma"]["status"] == "Applied"


def test_a_click_the_page_doesnt_confirm_is_not_counted_as_applied(ada, world):
    world.forms["alpha"]["confirm"] = False
    _run(ada, live=True)
    run = _runs(ada)["alpha"]
    assert run["outcome"] == "unconfirmed" and "Check whether it went through" in run["reasons"][0]
    assert {a["company"]: a["status"] for a in tracker.list_applications(ada)}["alpha"] == "Pending Review"
    assert autopilot.sent_last_day(ada) == 3                              # still counts toward the limit


def test_poor_fits_and_stretches_are_skipped_without_filling(ada, world):
    world.fit["alpha"] = (60, "strong")
    world.fit["beta"] = (95, "reach")
    _run(ada, live=True)
    runs = _runs(ada)
    assert runs["alpha"]["outcome"] == "skipped" and "under your threshold of 75" in runs["alpha"]["reasons"][0]
    assert runs["beta"]["outcome"] == "skipped" and "stretch" in runs["beta"]["reasons"][0]
    assert world.filled == ["gamma"]


def test_each_job_is_tried_once_but_practice_runs_dont_count_once_live(ada, world):
    world.forms["alpha"]["questions"] = [_answer("Visa?", "needs_you")]
    _run(ada)                                       # practice: all three filled
    _run(ada)                                       # nothing new
    assert len(world.filled) == 3
    _run(ada, live=True)                            # live: the practice ones are tried for real
    assert len(world.filled) == 6
    _run(ada)                                       # and then not again
    assert len(world.filled) == 6


def test_jobs_already_in_the_tracker_are_left_alone(ada, world):
    tracker.add_application(ada, {"job_id": "x", "title": "Graduate Engineer alpha", "company": "alpha"}, {}, "", {},
                            status="Saved")
    _run(ada)
    assert sorted(world.filled) == ["beta", "gamma"]


def test_a_retry_tries_a_held_job_again_even_below_the_threshold(ada, world):
    world.fit["alpha"] = (60, "strong")
    _run(ada, live=True)
    skipped = _runs(ada)["alpha"]
    asyncio.run(autopilot.run(ada, skipped["job_id"]))
    assert _runs(ada)["alpha"]["outcome"] == "submitted"


# ── Endpoints ─────────────────────────────────────────────────────────────────

def test_status_settings_and_runs_endpoints(ada, world, client_for):
    client = client_for(ada)
    status = client.get("/autopilot").json()
    assert status["settings"] == autopilot.DEFAULTS and status["running"] is False and status["sent_last_day"] == 0
    assert client.put("/autopilot/settings", json={"daily_cap": 50}).status_code == 400
    assert client.put("/autopilot/settings", json={"live": True, "daily_cap": 2}).json()["daily_cap"] == 2
    assert client.get("/autopilot").json()["settings"]["live"] is True

    world.forms["alpha"]["questions"] = [_answer("Visa?", "needs_you")]
    asyncio.run(autopilot.run(ada))
    runs = {r["company"]: r for r in client.get("/autopilot/runs").json()}
    assert runs["alpha"]["outcome"] == "needs_you" and runs["alpha"]["screenshots"] == ["form"]
    assert runs["beta"]["screenshots"] == ["form", "confirm"] and "user_id" not in runs["beta"]

    shot = client.get(f"/autopilot/runs/{runs['beta']['id']}/screenshots/confirm")
    assert shot.status_code == 200 and shot.headers["content-type"] == "image/jpeg"
    assert client.get(f"/autopilot/runs/{runs['alpha']['id']}/screenshots/confirm").status_code == 404
    assert client.get(f"/autopilot/runs/{runs['alpha']['id']}/screenshots/passwd").status_code == 404

    assert client.post(f"/autopilot/runs/{runs['beta']['id']}/dismiss").status_code == 400   # sent: stays
    assert client.post(f"/autopilot/runs/{runs['beta']['id']}/retry").status_code == 400
    assert client.post(f"/autopilot/runs/{runs['alpha']['id']}/dismiss").json() == {"dismissed": runs["alpha"]["id"]}
    assert tracker.get_autopilot_run(ada, runs["alpha"]["id"])["outcome"] == "dismissed"


def test_another_users_runs_are_out_of_reach(ada, world, client_for, make_user):
    asyncio.run(autopilot.run(ada))
    run_id = tracker.list_autopilot_runs(ada)[0]["id"]
    other = client_for(make_user("eve@example.com"))
    assert other.get("/autopilot/runs").json() == []
    for path in (f"/autopilot/runs/{run_id}/screenshots/form",):
        assert other.get(path).status_code == 404
    assert other.post(f"/autopilot/runs/{run_id}/dismiss").status_code == 404
    assert other.post(f"/autopilot/runs/{run_id}/retry").status_code == 404


def test_one_run_at_a_time(ada, world, client_for, monkeypatch):
    autopilot._runs[ada] = autopilot._Run(started_at="now", live=False)
    try:
        assert client_for(ada).post("/autopilot/run").status_code == 409
        assert autopilot.start(ada) is False
    finally:
        autopilot._runs.pop(ada, None)


def test_a_restart_finishes_runs_left_running(ada, world):
    run_id = tracker.start_autopilot_run(ada, {"id": "j1", "title": "T", "company": "C"})
    tracker.finish_stale_autopilot_runs()
    run = tracker.get_autopilot_run(ada, run_id)
    assert run["outcome"] == "failed" and "restarted" in run["reasons"][0]
