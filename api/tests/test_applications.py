"""Application tracker: ownership, and 'Applied' only on a confirmed submission."""
import sqlite3

import pytest

from app import agent, main, net_guard, tracker

JOB = {"job_id": "1", "title": "Engineer", "company": "Acme", "location": "London", "url": "https://x"}
SCORES = {"composite_score": 0, "exposure_score": 0.5, "fit_score": 0, "skill_gaps": [], "level_match": "ok"}


def _status(user_id, app_id):
    return next(a["status"] for a in tracker.list_applications(user_id) if a["id"] == app_id)


def test_cannot_update_another_users_application(make_user, client_for):
    alice, mallory = make_user("alice@x.com"), make_user("mallory@x.com")
    app_id = tracker.add_application(alice, JOB, {}, "", SCORES)

    r = client_for(mallory).patch(f"/applications/{app_id}/status", json={"status": "Discarded", "notes": "pwned"})

    assert r.status_code == 404
    assert _status(alice, app_id) == "Pending Review"


def test_owner_can_update_and_invalid_status_is_400(user, client):
    app_id = tracker.add_application(user, JOB, {}, "", SCORES)
    assert client.patch(f"/applications/{app_id}/status", json={"status": "Interview"}).status_code == 200
    assert _status(user, app_id) == "Interview"
    assert client.patch(f"/applications/{app_id}/status", json={"status": "Bogus"}).status_code == 400


@pytest.fixture
def apply_with(monkeypatch, client):
    """apply_with(submitted, title) → status of the tracked application after one /apply run."""
    async def public(url):
        return None
    monkeypatch.setattr(net_guard, "assert_public_url", public)

    def _apply(submitted: bool, title: str, company: str = "Acme"):
        async def fake_run_apply(*args, **kwargs):
            yield agent._sse("start", {})
            yield agent._sse("done", {"message": "Done", "submitted": submitted})
        monkeypatch.setattr(main, "run_apply", fake_run_apply)
        client.post("/apply", data={"job_id": title, "job_title": title, "company": company,
                                    "job_url": "https://jobs.example.com/x"})
    return _apply


def test_apply_marks_applied_only_when_submitted(user, apply_with):
    apply_with(False, "Role A")
    apply_with(True, "Role B")
    statuses = {a["job_title"]: a["status"] for a in tracker.list_applications(user)}
    assert statuses == {"Role A": "Pending Review", "Role B": "Applied"}


def test_submitting_a_previously_saved_job_marks_it_applied(user, client, apply_with):
    client.post("/jobs/save", json={"job": {"job_id": "9", "title": "Saved Role", "company": "Acme"}})
    apply_with(True, "Saved Role")
    (row,) = [a for a in tracker.list_applications(user) if a["job_title"] == "Saved Role"]
    assert row["status"] == "Applied"


def test_run_apply_reports_submitted_from_the_browser_session(monkeypatch):
    import asyncio, json

    monkeypatch.setattr(tracker, "get_user_persona", lambda uid: {})

    def final_event(step):
        async def gen(*args, **kwargs):
            yield {"action": "step", "done": False}
            yield step
        monkeypatch.setattr(agent, "apply_with_browser", gen)

        async def collect():
            return [json.loads(c[6:]) async for c in
                    agent.run_apply("u", "j", "https://x", "", [], "s", asyncio.Queue(), None)]
        return [e for e in asyncio.run(collect()) if e["type"] == "done"][-1]

    assert final_event({"action": "Cancelled", "done": True})["submitted"] is False
    assert final_event({"action": "ok", "done": True, "submitted": True})["submitted"] is True


# ── Status history ────────────────────────────────────────────────────────────────────────────

def _history(user_id, app_id):
    app = next(a for a in tracker.list_applications(user_id) if a["id"] == app_id)
    return [(s["status"], s["source"]) for s in app["history"]]


def _app(user_id, app_id):
    return next(a for a in tracker.list_applications(user_id) if a["id"] == app_id)


def test_every_status_change_is_logged_with_who_made_it(user):
    app_id = tracker.add_application(user, JOB, {}, "", SCORES, status="Applied", source="autopilot",
                                     at="2026-08-02T10:00:00+00:00")
    tracker.update_status(app_id, "Interview", user_id=user, source="email", at="2026-09-02T10:00:00+00:00")
    tracker.update_status(app_id, "Rejected", user_id=user)
    assert _history(user, app_id) == [("Applied", "autopilot"), ("Interview", "email"), ("Rejected", "you")]
    assert _app(user, app_id)["history"][1]["changed_at"] == "2026-09-02T10:00:00+00:00"


def test_saving_a_note_logs_nothing_and_keeps_the_applied_date(user):
    app_id = tracker.add_application(user, JOB, {}, "", SCORES, status="Applied", at="2026-01-05T09:00:00+00:00")
    assert tracker.update_status(app_id, "Applied", "Spoke to Sam", user_id=user)
    app = _app(user, app_id)
    assert app["date_applied"] == "2026-01-05" and app["notes"] == "Spoke to Sam"
    assert _history(user, app_id) == [("Applied", "you")]


def test_going_back_to_applied_keeps_the_day_it_was_applied(user):
    app_id = tracker.add_application(user, JOB, {}, "", SCORES, status="Applied", at="2026-01-05T09:00:00+00:00")
    tracker.update_status(app_id, "Interview", user_id=user)
    tracker.update_status(app_id, "Applied", user_id=user)
    assert _app(user, app_id)["date_applied"] == "2026-01-05"


def test_applying_again_after_moving_a_card_back_takes_the_new_date(user):
    app_id = tracker.add_application(user, JOB, {}, "", SCORES, status="Applied", at="2026-01-05T09:00:00+00:00")
    tracker.update_status(app_id, "Saved", user_id=user)
    tracker.update_status(app_id, "Applied", user_id=user, at="2026-03-09T09:00:00+00:00")
    assert _app(user, app_id)["date_applied"] == "2026-03-09"


def test_an_undone_change_leaves_the_history(user):
    app_id = tracker.add_application(user, JOB, {}, "", SCORES, status="Applied")
    tracker.update_status(app_id, "Rejected", user_id=user, source="email")
    tracker.update_status(app_id, "Applied", user_id=user, source="undo")
    assert _history(user, app_id) == [("Applied", "you")]


def test_another_users_update_logs_nothing(make_user):
    alice, mallory = make_user("alice@x.com"), make_user("mallory@x.com")
    app_id = tracker.add_application(alice, JOB, {}, "", SCORES, status="Applied")
    assert not tracker.update_status(app_id, "Rejected", user_id=mallory)
    assert _history(alice, app_id) == [("Applied", "you")]


def test_applications_from_before_the_log_get_what_can_be_rebuilt(user, tmp_path):
    db = str(tmp_path / "applications.db")
    earlier = tracker.add_application(user, JOB, {}, "", SCORES, status="Applied", at="2026-02-01T00:00:00+00:00")
    saved = tracker.add_application(user, {**JOB, "title": "Analyst"}, {}, "", SCORES, status="Saved")
    tracker.update_status(earlier, "Rejected", user_id=user)
    tracker.add_email_event(user, {"gmail_id": "m1", "received_at": "2026-03-01T00:00:00+00:00", "sender": "a", "subject": "b",
                                   "kind": "interview", "application_id": earlier, "proposed": "Interview", "decision": "applied"})
    tracker.add_email_event(user, {"gmail_id": "m2", "received_at": "2026-03-02T00:00:00+00:00", "sender": "a", "subject": "b",
                                   "kind": "rejected", "application_id": earlier, "proposed": "Rejected", "decision": "undone"})
    con = sqlite3.connect(db)
    con.execute("DELETE FROM status_history")
    con.commit()
    con.close()

    tracker.init_db(db)
    tracker.init_db(db)                                      # and only once

    assert _history(user, earlier) == [("Applied", "earlier"), ("Interview", "email"), ("Rejected", "earlier")]
    assert _history(user, saved) == [("Saved", "earlier")]
