"""Assessments on Home: what's still to do and by when, read from job emails."""
import asyncio
from datetime import date, timedelta

import pytest

from app import agent, assessments, gmail, tracker

TODAY = date(2026, 11, 4)
_counter = iter(range(10_000))


def _on(days_ago: int) -> str:
    return f"{(TODAY - timedelta(days=days_ago)).isoformat()}T10:00:00+00:00"


def _mail(uid, kind, days_ago=0, company="Optiver", app_id=None, state=None, deadline=None, minutes=None, decision=None, summary="Asks you to take a test"):
    state = "requested" if state is None and kind == "assessment" else (state or "")
    tracker.add_email_event(uid, {
        "gmail_id": f"m{next(_counter)}", "received_at": _on(days_ago), "sender": "x@example.com", "subject": "s", "kind": kind,
        "company": company, "role": "Graduate Software Engineer", "summary": summary, "application_id": app_id, "assessment": state,
        "deadline": deadline, "minutes": minutes, "decision": decision or ("noted" if app_id else "unmatched")})


def _app(uid, company="Optiver", status="Applied"):
    return tracker.add_application(uid, {"job_id": company, "title": "Graduate Software Engineer", "company": company}, {}, "", {}, status=status)


def _open(uid):
    return assessments.overview(uid, TODAY)["open"]


def _date(days_from_today):
    return (TODAY + timedelta(days=days_from_today)).isoformat()


# ── What's to do ──────────────────────────────────────────────────────────────

def test_a_requested_test_shows_with_its_deadline_and_length(db, user):
    app = _app(user)
    _mail(user, "assessment", 1, app_id=app, deadline=_date(3), minutes=102)
    [row] = _open(user)
    assert row["company"] == "Optiver" and row["days_left"] == 3 and row["minutes"] == 102 and row["tracked"]


def test_reminders_are_one_row_and_keep_the_first_deadline(db, user):
    app = _app(user)
    _mail(user, "assessment", 3, app_id=app, deadline=_date(4), minutes=60)
    _mail(user, "assessment", 2, app_id=app, deadline=_date(9), summary="Reminds you")   # counted again from the reminder
    _mail(user, "assessment", 1, app_id=app, summary="Reminds you again")
    [row] = _open(user)
    assert row["days_left"] == 4 and row["minutes"] == 60 and row["emails"] == 3 and row["summary"] == "Reminds you again"


def test_an_invitation_from_an_untracked_employer_still_shows(db, user):
    _mail(user, "assessment", 1, company="Bank of England", deadline=_date(2))
    [row] = _open(user)
    assert row["company"] == "Bank of England" and not row["tracked"]


def test_two_applications_at_one_employer_are_two_rows(db, user):
    first, second = _app(user, "PwC"), tracker.add_application(user, {"job_id": "b", "title": "Graduate London", "company": "PwC"}, {}, "", {}, status="Applied")
    _mail(user, "assessment", 1, company="PwC", app_id=first, deadline=_date(5))
    _mail(user, "assessment", 1, company="PwC", app_id=second, deadline=_date(6))
    _mail(user, "rejected", 0, company="PwC", app_id=first)
    assert [r["key"] for r in _open(user)] == [f"app:{second}"]


def test_soonest_first_then_no_date_then_late(db, user):
    for company, deadline in (("Late", _date(-2)), ("Open ended", None), ("Later", _date(6)), ("Soon", _date(1))):
        _mail(user, "assessment", 1, company=company, deadline=deadline)
    assert [r["company"] for r in _open(user)] == ["Soon", "Later", "Open ended", "Late"]


def test_a_late_test_stays_a_while_then_goes(db, user):
    _mail(user, "assessment", 20, company="Recent", deadline=_date(-14))
    _mail(user, "assessment", 21, company="Old", deadline=_date(-15))
    assert [r["company"] for r in _open(user)] == ["Recent"]


def test_older_emails_with_no_details_dont_fill_the_list(db, user):
    _mail(user, "assessment", 40, company="Shell", state="")
    _mail(user, "assessment", 5, company="WTW", state="")
    assert [r["company"] for r in _open(user)] == ["WTW"]


# ── What ends one ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", ["rejected", "interview", "offer"])
def test_a_later_verdict_ends_it(db, user, kind):
    app = _app(user)
    _mail(user, "assessment", 3, app_id=app)
    _mail(user, kind, 1, app_id=app)
    assert _open(user) == []


@pytest.mark.parametrize("status", ["Rejected", "Discarded", "Offer"])
def test_an_ended_application_ends_it(db, user, status):
    _mail(user, "assessment", 1, app_id=_app(user, status=status))
    assert _open(user) == []


def test_a_verdict_for_the_same_employer_ends_an_unlinked_one(db, user):
    _mail(user, "assessment", 3, company="Optiver Ltd")
    _mail(user, "rejected", 1, company="Optiver", app_id=_app(user))
    assert _open(user) == []


def test_a_new_test_after_an_interview_shows(db, user):
    app = _app(user)
    _mail(user, "assessment", 9, app_id=app)
    _mail(user, "interview", 6, app_id=app)
    _mail(user, "assessment", 1, app_id=app, deadline=_date(3))
    assert len(_open(user)) == 1


def test_an_email_saying_its_finished_ends_it(db, user):
    app = _app(user)
    _mail(user, "assessment", 3, app_id=app)
    _mail(user, "other", 1, app_id=app, state="completed")
    assert _open(user) == []
    assert assessments.overview(user, TODAY)["record"]["done"] == 1


def test_dismissed_and_ignored_emails_dont_count(db, user):
    _mail(user, "assessment", 1, company="Dismissed", decision="dismissed")
    _mail(user, "assessment", 1, company="Undone", decision="undone")
    assert _open(user) == []


def test_an_unlinked_note_that_its_finished_joins_the_only_application_there(db, user):
    _mail(user, "assessment", 3, app_id=_app(user))
    _mail(user, "other", 1, state="completed")
    assert _open(user) == []


def test_a_finished_note_naming_no_employer_isnt_counted(db, user):
    _mail(user, "other", 1, company="", state="completed")
    assert assessments.overview(user, TODAY)["record"]["done"] == 0


def test_a_request_naming_no_employer_still_shows(db, user):
    _mail(user, "assessment", 1, company="", deadline=_date(2))
    [row] = _open(user)
    assert row["company"] == "Employer not named" and row["days_left"] == 2


# ── Marking ───────────────────────────────────────────────────────────────────

def _today_row(user):
    return assessments.overview(user)["open"]


def _recent(user, app=None, **fields):
    tracker.add_email_event(user, {"gmail_id": f"m{next(_counter)}", "received_at": date.today().isoformat() + "T08:00:00+00:00", "sender": "x", "subject": "s",
                                   "kind": "assessment", "company": "Optiver", "role": "", "summary": "Take a test", "application_id": app, "assessment": "requested",
                                   "decision": "noted" if app else "unmatched", **fields})


def test_marking_done_and_undoing(db, user):
    _recent(user, _app(user))
    [row] = _today_row(user)
    after = assessments.mark(user, row["key"], "done")
    assert after["open"] == [] and after["record"]["done"] == 1
    after = assessments.mark(user, row["key"], "open")
    assert len(after["open"]) == 1 and after["record"]["done"] == 0


def test_not_taking_one_removes_it_without_counting_it_done_or_missed(db, user):
    _recent(user, _app(user), deadline=date.today().isoformat())
    [row] = _today_row(user)
    after = assessments.mark(user, row["key"], "skipped")
    assert after["open"] == [] and after["record"] == {"done": 0, "moved_on": 0, "not_passed": 0, "waiting": 0, "missed": 0}


def test_a_reminder_just_after_marking_done_doesnt_reopen_it(db, user):
    app = _app(user)
    _mail(user, "assessment", 3, app_id=app)
    tracker.set_assessment_mark(user, f"app:{app}", "done")
    _recent(user, app)
    assert _today_row(user) == []


def test_a_new_test_days_after_marking_done_shows(db, user):
    app = _app(user)
    _mail(user, "assessment", 9, app_id=app)
    tracker.set_assessment_mark(user, f"app:{app}", "done")
    con = tracker.sqlite3.connect(tracker._DB_PATH)
    con.execute("UPDATE assessment_marks SET marked_at=?", (_on(6),))
    con.commit()
    con.close()
    _mail(user, "assessment", 1, app_id=app, deadline=_date(3))
    assert len(_open(user)) == 1


def test_endpoints(db, user, client):
    _recent(user, _app(user))
    key = client.get("/assessments").json()["open"][0]["key"]
    assert client.post("/assessments/mark", json={"key": key, "state": "done"}).json()["open"] == []
    assert client.post("/assessments/mark", json={"key": key, "state": "nonsense"}).status_code == 400
    assert client.post("/assessments/mark", json={"key": "app:nope", "state": "done"}).status_code == 404


def test_someone_elses_assessment_cant_be_marked_or_seen(make_user, client_for):
    alice, mallory = make_user("alice@x.com"), make_user("mallory@x.com")
    _recent(alice, _app(alice))
    key = client_for(alice).get("/assessments").json()["open"][0]["key"]
    assert client_for(mallory).get("/assessments").json()["open"] == []
    assert client_for(mallory).post("/assessments/mark", json={"key": key, "state": "done"}).status_code == 404
    assert len(client_for(alice).get("/assessments").json()["open"]) == 1


# ── The record ────────────────────────────────────────────────────────────────

def test_the_record_says_how_finished_tests_went(db, user):
    passed, failed, waiting = _app(user, "Passed", "Interview"), _app(user, "Failed", "Rejected"), _app(user, "Waiting")
    for app, company in ((passed, "Passed"), (failed, "Failed"), (waiting, "Waiting")):
        _mail(user, "assessment", 9, company=company, app_id=app)
        _mail(user, "other", 8, company=company, app_id=app, state="completed")
    _mail(user, "rejected", 2, company="Failed", app_id=failed)
    _mail(user, "interview", 2, company="Passed", app_id=passed)
    _mail(user, "rejected", 2, company="Timed out", state="missed")
    _mail(user, "assessment", 9, company="Ran out", deadline=_date(-3))
    assert assessments.overview(user, TODAY)["record"] == {"done": 3, "moved_on": 1, "not_passed": 1, "waiting": 1, "missed": 2}


# ── Reading the email ─────────────────────────────────────────────────────────

def _read(monkeypatch, reply, text="", received="2026-09-22T10:00:00+00:00", subject="Your assessment"):
    async def model(system, user, **kwargs):
        return {"kind": "assessment", "application": None, "confidence": "high", "company": "Optiver", "role": "", "summary": "x", **reply}
    monkeypatch.setattr(agent, "_llm_json", model)
    email = {"sender": "x@optiver.com", "sender_address": "x@optiver.com", "subject": subject, "text": text, "snippet": "", "received_at": received}
    return asyncio.run(gmail.read(email, []))


def test_the_model_gives_the_deadline_and_length(monkeypatch):
    reading = _read(monkeypatch, {"assessment": "requested", "deadline": "2026-09-29", "minutes": 102})
    assert (reading["assessment"], reading["deadline"], reading["minutes"]) == ("requested", "2026-09-29", 102)


def test_an_assessment_is_a_request_even_when_the_model_doesnt_say(monkeypatch):
    assert _read(monkeypatch, {})["assessment"] == "requested"


@pytest.mark.parametrize("text, expected", [
    ("Please complete it within 7 days of this email.", "2026-09-29"),
    ("You have 4 days (96 hours from when you receive this email).", "2026-09-26"),
    ("You will have 3 days to complete it.", "2026-09-25"),
    ("Please complete it within seven days.", "2026-09-29"),
    ("Complete these tests within 48 hours.", "2026-09-24"),
    ("You have 5 working days.", "2026-09-27"),
    ("We look forward to reading your answers.", None),
])
def test_a_deadline_the_model_missed_is_worked_out(monkeypatch, text, expected):
    assert _read(monkeypatch, {"deadline": ""}, text)["deadline"] == expected


@pytest.mark.parametrize("deadline", ["2020-01-01", "2029-01-01", "soon", "22nd September", None])
def test_a_senseless_deadline_isnt_believed(monkeypatch, deadline):
    assert _read(monkeypatch, {"deadline": deadline})["deadline"] is None


@pytest.mark.parametrize("minutes", [0, -5, 5000, "an hour", True, None])
def test_a_senseless_length_isnt_believed(monkeypatch, minutes):
    assert _read(monkeypatch, {"minutes": minutes})["minutes"] is None


def test_only_an_assessment_email_can_be_a_request(monkeypatch):
    reading = _read(monkeypatch, {"kind": "rejected", "assessment": "requested", "deadline": "2026-09-29"})
    assert reading["assessment"] == "" and reading["deadline"] is None


def test_a_rejection_for_missing_the_deadline_is_recorded_as_missed(monkeypatch):
    assert _read(monkeypatch, {"kind": "rejected", "assessment": "missed"})["assessment"] == "missed"


def test_a_hiring_survey_is_never_a_request(monkeypatch):
    text = "To improve our hiring practices, please complete our anonymous survey."
    reading = _read(monkeypatch, {"assessment": "requested"}, text, subject="Complete our anonymous survey")
    assert reading["kind"] == "other" and reading["assessment"] == ""


def test_without_the_model_a_keyword_reading_still_finds_the_deadline(monkeypatch):
    async def down(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(agent, "_llm_json", down)
    email = {"sender": "x@y.com", "sender_address": "x@y.com", "subject": "Your online assessment", "text": "Complete the assessment within 7 days.",
             "snippet": "", "received_at": "2026-09-22T10:00:00+00:00"}
    reading = asyncio.run(gmail.read(email, []))
    assert reading["assessment"] == "requested" and reading["deadline"] == "2026-09-29"


# ── Finding the emails ────────────────────────────────────────────────────────

@pytest.mark.parametrize("wanted", ["assessments", '"online test"', '"technical challenge"', "arcticshores.com", "hirevue.com", "thomas.co", "testgorilla.com"])
def test_invitations_are_searched_for(wanted):
    assert wanted in gmail._past_query("6m")


def test_a_newsletter_called_coding_challenges_isnt_searched_for():
    assert "coding challenge" not in gmail._past_query("6m").lower()


@pytest.mark.parametrize("sender, subject, text", [
    ("noreply@jobalerts-uk.pwc.com", "Reminder - PwC Job Application: Invitation to complete Online Assessment", "We've noticed that you haven't yet completed your assessment."),
    ("noreply@jobalerts-uk.pwc.com", "PwC Recruitment - Reminder to complete your online test", "Please complete your online test."),
])
def test_a_test_reminder_from_a_job_alerts_address_isnt_an_alert(sender, subject, text):
    assert not gmail.is_job_alert({"sender": sender, "sender_address": sender, "subject": subject, "text": text, "snippet": ""})


@pytest.mark.parametrize("sender, subject, text", [
    ("jobalerts-noreply@linkedin.com", "Graduate Software Engineer at Catapult and 12 more jobs", "Apply now. Be an early applicant."),
    ("jobalerts-noreply@linkedin.com", "Software Engineer at Monzo", "Take a skills test to stand out from other applicants."),
])
def test_real_alerts_stay_alerts(sender, subject, text):
    assert gmail.is_job_alert({"sender": sender, "sender_address": sender, "subject": subject, "text": text, "snippet": ""})


@pytest.mark.parametrize("subject", ["Invitation for assessments", "Invitation to Online Test for London", "Arctic Lake Technical Challenge"])
def test_invitations_count_as_relevant(subject):
    email = {"sender": "x@y.com", "sender_address": "x@y.com", "subject": subject, "text": "", "snippet": ""}
    assert gmail.relevant(email, [])
