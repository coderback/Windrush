"""The browser agent only states facts the user has actually given — never a default."""
import asyncio
import json
import sqlite3

import pytest

import app.browser_agent as ba
from app import agent, net_guard, tracker

UNSET_FACTS = ["Right to work", "Require visa sponsorship", "Has government ties", "Willing to relocate",
               "Can work in-person", "Can start immediately", "Has reliable transportation",
               "Needs accommodations", "Are you currently employed", "Remote/Hybrid preference"]


def _answers(persona):
    return dict(ba._known_answers(persona))


def test_unanswered_facts_are_left_out_not_defaulted():
    answers = _answers({"core_info": {"first_name": "Ada"}})
    for question in UNSET_FACTS:
        assert not any(q.startswith(question) for q in answers), question


def test_unanswered_facts_are_not_in_the_task_and_the_agent_is_told_not_to_guess():
    task = ba._build_task("https://x.example/job", {"core_info": {"first_name": "Ada"}}, "", "", "", "")
    assert "work authorisation in the UK:" not in task
    assert "Require visa sponsorship:" not in task
    assert "Remote/Hybrid preference:" not in task
    assert "do NOT guess" in task and "Needs your input" in task


def test_agent_is_told_to_open_its_summary_with_what_needs_input():
    task = ba._build_task("https://x.example/job", {}, "", "", "", "")
    assert "In the done text, start with 'Needs your input: ...'" in task


def test_given_answers_are_stated_including_no():
    persona = {
        "core_info": {"right_to_work_uk": False, "require_sponsorship": True, "has_government_ties": False},
        "preferences": {"relocation_willingness": True, "can_start_immediately": False},
    }
    answers = _answers(persona)
    assert answers["Right to work / work authorisation in the UK"] == "No"
    assert answers["Require visa sponsorship"] == "Yes"
    assert answers["Has government ties"] == "No"
    assert answers["Willing to relocate"] == "Yes"
    assert answers["Can start immediately"] == "No"
    assert "Needs accommodations" not in answers


def test_diversity_falls_back_to_prefer_not_to_say_and_maps_stored_values():
    assert _answers({})["Disability"] == "Prefer not to say"
    assert _answers({"diversity": {"disability_status": "no"}})["Disability"] == "No"
    assert _answers({"diversity": {"disability_status": "prefer_not_to_say"}})["Disability"] == "Prefer not to say"
    assert _answers({})["Gender"] == "Prefer not to say"


def test_currently_employed_means_a_current_role_not_any_past_one():
    past = {"history": [{"employer": "Old Co", "title": "Intern", "is_current": False, "end_date": "2022"}]}
    current = {"history": [{"employer": "Now Co", "title": "Analyst", "is_current": True}]}
    assert _answers(past)["Are you currently employed"] == "No"
    assert _answers(current)["Are you currently employed"] == "Yes"


@pytest.mark.parametrize("end_date", ["Present", "current", "NOW", "Ongoing", "to date", "Date", " present. "])
def test_a_present_end_date_counts_as_currently_employed(end_date):
    # How parsed CVs often store a current role: is_current left off, the CV's word in end_date.
    persona = {"history": [{"employer": "Old Co", "end_date": "2019"},
                           {"employer": "Now Co", "is_current": False, "end_date": end_date}]}
    assert _answers(persona)["Are you currently employed"] == "Yes"


def test_currently_employed_is_no_only_when_every_role_has_really_ended():
    ended = {"history": [{"employer": "A", "end_date": "2021"}, {"employer": "B", "end_date": "Mar 2019"}]}
    assert _answers(ended)["Are you currently employed"] == "No"

    # A role with no end date may be the current one: don't claim either way.
    unclear = {"history": [{"employer": "A", "end_date": "2021"}, {"employer": "B", "end_date": ""}]}
    assert "Are you currently employed" not in _answers(unclear)
    assert "Are you currently employed" not in _answers({"history": [{"employer": "A"}]})


def test_remote_preference_is_stated_only_when_the_user_picked_one():
    assert "Remote/Hybrid preference" not in _answers({"preferences": {"remote_preference": ""}})
    assert _answers({"preferences": {"remote_preference": "hybrid"}})["Remote/Hybrid preference"] == "hybrid"


def test_saving_a_profile_without_a_work_setting_leaves_it_unanswered_everywhere(client, user):
    assert client.put("/persona", json={"core_info": {"first_name": "Ada"}}).status_code == 200
    assert tracker.get_user_persona(user)["preferences"]["remote_preference"] == ""
    assert client.get("/persona").json()["preferences"]["remote_preference"] == ""
    export = client.get("/persona/export", params={"format": "md"})
    assert export.status_code == 200 and "Remote preference" not in export.text


def test_unset_salary_reads_negotiable_not_none():
    answers = _answers({"preferences": {"min_salary": None, "expected_hourly_rate": None}})
    assert answers["Salary expectations (Annual)"] == "Negotiable"
    assert answers["Salary expectations (Hourly)"] == "Negotiable"


def test_saving_a_profile_without_eligibility_answers_stores_them_as_unanswered(client, user):
    assert client.put("/persona", json={"core_info": {"first_name": "Ada"}}).status_code == 200
    stored = tracker.get_user_persona(user)
    assert stored["core_info"]["right_to_work_uk"] is None
    assert stored["core_info"]["require_sponsorship"] is None
    assert stored["preferences"]["has_reliable_transportation"] is None
    assert client.get("/persona").json()["core_info"]["right_to_work_uk"] is None


def _legacy_db(path, *personas):
    """A pre-migration DB with users u1, u2, … holding these personas."""
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,"
                " persona TEXT DEFAULT '{}', onboarding_complete INTEGER DEFAULT 0, created_at TEXT NOT NULL)")
    for n, persona in enumerate(personas, 1):
        con.execute("INSERT INTO users VALUES (?, ?, 'h', ?, 1, 'now')", (f"u{n}", f"u{n}@x.com", json.dumps(persona)))
    con.commit()
    con.close()


def test_defaults_the_ui_could_never_set_are_cleared_once(tmp_path):
    path = str(tmp_path / "legacy.db")
    _legacy_db(path, {
        "core_info": {"first_name": "Ada", "right_to_work_uk": True, "require_sponsorship": False},
        "preferences": {"can_work_in_person": True, "relocation_willingness": True},
    })

    tracker.init_db(path)

    persona = tracker.get_user_persona("u1")
    assert persona["core_info"]["right_to_work_uk"] is None
    assert persona["core_info"]["require_sponsorship"] is None
    assert persona["preferences"]["can_work_in_person"] is None
    # Settable in the UI and not its old default (False), so the user chose it: kept.
    assert persona["preferences"]["relocation_willingness"] is True
    assert persona["core_info"]["first_name"] == "Ada"

    # Answers given after the migration survive later restarts.
    persona["core_info"]["right_to_work_uk"] = True
    tracker.update_user_persona("u1", persona)
    tracker.init_db(path)
    assert tracker.get_user_persona("u1")["core_info"]["right_to_work_uk"] is True


# Settable in the UI, but every save on main wrote the model default, so a stored default proves nothing.
OLD_DEFAULTS = {("core_info", "has_government_ties"): False, ("preferences", "relocation_willingness"): False,
                ("preferences", "can_start_immediately"): False, ("preferences", "needs_accommodations"): False,
                ("preferences", "has_reliable_transportation"): True}


def _persona_with(values):
    persona = {"core_info": {"first_name": "Ada"}, "preferences": {}}
    for (section, field), value in values.items():
        persona[section][field] = value
    return persona


def test_old_defaults_are_cleared_but_other_answers_are_the_users_and_kept(tmp_path):
    path = str(tmp_path / "legacy.db")
    chosen = {key: not default for key, default in OLD_DEFAULTS.items()}
    _legacy_db(path, _persona_with(OLD_DEFAULTS), _persona_with(chosen))

    tracker.init_db(path)

    defaulted, answered = tracker.get_user_persona("u1"), tracker.get_user_persona("u2")
    for (section, field), default in OLD_DEFAULTS.items():
        assert defaulted[section][field] is None, field
        assert answered[section][field] is (not default), field
    assert defaulted["core_info"]["first_name"] == "Ada"

    # Once migrated, a user who now answers with the old default value keeps it.
    defaulted["preferences"]["relocation_willingness"] = False
    tracker.update_user_persona("u1", defaulted)
    tracker.init_db(path)
    assert tracker.get_user_persona("u1")["preferences"]["relocation_willingness"] is False


# ── The agent's final summary reaches the review UI whole ─────────────────────

NOTES = "Needs your input:\n- Notice period\n- Criminal record declaration\n\nFilled name, email and CV."


class _FakeHistory:
    def __init__(self, ok: bool, text: str):
        self.ok, self.text = ok, text

    def is_successful(self):
        return self.ok

    def final_result(self):
        return self.text


def _fill_events(monkeypatch, final_result: str, ok: bool = True) -> list[dict]:
    """apply_with_browser's events with browser-use faked out: the fill agent finishes with
    `final_result`, then the user skips the review."""
    class FakeAgent:
        def __init__(self, **kwargs):
            pass

        async def run(self, max_steps):
            return _FakeHistory(ok, final_result)

    class FakeSession:
        def __init__(self, **kwargs):
            pass

        async def kill(self):
            pass

    async def no_screenshot(session):
        return ""

    monkeypatch.setattr(ba, "BROWSER_USE_AVAILABLE", True)
    monkeypatch.setattr(ba, "Agent", FakeAgent)
    monkeypatch.setattr(ba, "BrowserSession", FakeSession)
    monkeypatch.setattr(ba, "_browser_profile", lambda: None)
    monkeypatch.setattr(ba, "_make_browser_llm", lambda: None)
    monkeypatch.setattr(ba, "_has_page", lambda session: True)
    monkeypatch.setattr(ba, "_screenshot_b64", no_screenshot)

    async def run():
        queue: asyncio.Queue = asyncio.Queue()
        queue.put_nowait("skip")
        return [e async for e in ba.apply_with_browser("https://jobs.example.com/1", {}, "", queue)]
    return asyncio.run(run())


def test_review_carries_the_agents_full_summary_as_notes_not_in_the_header(monkeypatch):
    long_tail = " Also checked the cover letter field." * 30   # well past the old 300-char cut
    events = _fill_events(monkeypatch, NOTES + long_tail)

    review = next(e for e in events if e.get("interactive"))
    assert review["notes"] == (NOTES + long_tail).strip()
    assert "\n- Notice period\n" in review["notes"]            # line breaks survive
    assert "Needs your input" not in review["action"] and len(review["action"]) < 100
    assert [e for e in events if e.get("notes")] == [review]    # sent once; the UI keeps it

    no_summary = next(e for e in _fill_events(monkeypatch, "") if e.get("interactive"))
    assert "notes" not in no_summary


def test_notes_are_capped_and_also_shown_when_the_agent_could_not_finish(monkeypatch):
    events = _fill_events(monkeypatch, NOTES + "x" * 5000, ok=False)
    review = next(e for e in events if e.get("interactive"))
    assert "couldn't finish" in review["action"]
    assert review["notes"].startswith("Needs your input:") and len(review["notes"]) == ba._MAX_NOTES_CHARS


def test_apply_stream_passes_the_notes_to_the_client(client, monkeypatch):
    async def public(url):
        return None
    monkeypatch.setattr(net_guard, "assert_public_url", public)

    async def fake_apply_with_browser(*args, **kwargs):
        yield {"action": "Form filled — review it before anything is sent — see the agent's notes",
               "screenshot": None, "blocked": True, "reason": "Type 'submit'…", "done": False,
               "interactive": True, "notes": NOTES}
        yield {"action": "Cancelled by user", "screenshot": None, "blocked": False, "reason": None, "done": True}
    monkeypatch.setattr(agent, "apply_with_browser", fake_apply_with_browser)

    r = client.post("/apply", data={"job_id": "j", "job_title": "T", "company": "C",
                                    "job_url": "https://jobs.example.com/1"})
    events = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
    review = next(e for e in events if e["type"] == "browser_blocked")
    assert review["notes"] == NOTES and review["interactive"] is True
    assert all("notes" not in e for e in events if e is not review)
