"""The browser agent only states facts the user has actually given — never a default."""
import json
import sqlite3

import app.browser_agent as ba
from app import tracker

UNSET_FACTS = ["Right to work", "Require visa sponsorship", "Has government ties", "Willing to relocate",
               "Can work in-person", "Can start immediately", "Has reliable transportation",
               "Needs accommodations", "Are you currently employed"]


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
    assert "do NOT guess" in task and "Needs your input" in task


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
    past = {"history": [{"employer": "Old Co", "title": "Intern", "is_current": False}]}
    current = {"history": [{"employer": "Now Co", "title": "Analyst", "is_current": True}]}
    assert _answers(past)["Are you currently employed"] == "No"
    assert _answers(current)["Are you currently employed"] == "Yes"


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


def _legacy_db(path, persona):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,"
                " persona TEXT DEFAULT '{}', onboarding_complete INTEGER DEFAULT 0, created_at TEXT NOT NULL)")
    con.execute("INSERT INTO users VALUES ('u1', 'u@x.com', 'h', ?, 1, 'now')", (json.dumps(persona),))
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
    # Settable in the UI, so it may be a real answer: kept.
    assert persona["preferences"]["relocation_willingness"] is True
    assert persona["core_info"]["first_name"] == "Ada"

    # Answers given after the migration survive later restarts.
    persona["core_info"]["right_to_work_uk"] = True
    tracker.update_user_persona("u1", persona)
    tracker.init_db(path)
    assert tracker.get_user_persona("u1")["core_info"]["right_to_work_uk"] is True
