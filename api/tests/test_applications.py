"""Application tracker: ownership, and 'Applied' only on a confirmed submission."""
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
