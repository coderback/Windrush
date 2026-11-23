"""Applications made outside Windrush get its treatment: one tracked from email is linked to the feed ad it was made
through only when that's certain (the one the user opened, or the only one), the user can pick among the rest, a
linked application gets the fit check, and "I applied" on a job page tracks it with the ad attached."""
import asyncio
import sqlite3

from app import ad_match, agent, jobs_db, tracker
from tests.conftest import make_job

AD = "Build trading systems in Python and C++. " * 20


def _ad(i, title, company="KLA Corporation", **extra):
    jobs_db.add_jobs([make_job(f"wd-{i}", title=title, company=company, description=AD, **extra)])
    return next(a for a in jobs_db.ads_at_company(company) if a["job_id"] == f"wd-{i}")


def _email_app(user, title, company="KLA", at=None):
    return tracker.add_application(user, {"job_id": f"email:{title}", "title": title, "company": company}, {}, "", {},
                                   status="Applied", source="email", at=at)


def _row(user, app_id):
    con = sqlite3.connect(tracker._DB_PATH)
    con.row_factory = sqlite3.Row
    row = dict(con.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone())
    con.close()
    return row


def _age(ad_id, days):
    con = sqlite3.connect(jobs_db._DB_PATH)
    with con:
        con.execute("UPDATE jobs SET created_at = datetime('now', ?) WHERE id = ?", (f"-{days} days", ad_id))
    con.close()


def test_a_candidate_is_the_same_employer_and_role_seen_before_the_application(db, user):
    ml = _ad(1, "AI/ML Software Engineer - Intern")
    _ad(2, "Process Engineer")
    old = _ad(3, "Software Engineer Intern")
    _age(old["id"], 400)
    _ad(4, "Software Engineer Intern", company="Applied Materials")
    app = tracker.application_row(user, _email_app(user, "Software Engineer Intern"))
    assert [a["id"] for a in ad_match.candidates(app)] == [ml["id"]]
    later = tracker.application_row(user, _email_app(user, "ML Software Engineer", at="2025-01-01T00:00:00"))
    assert ad_match.candidates(later) == []                     # the ad came after the application


def test_a_requisition_code_or_a_place_in_the_emailed_role_doesnt_stop_a_match(db, user):
    ad = _ad(1, "Information & Digital Technology (IDT) - Shell Graduate Programme", company="Shell")
    app = tracker.application_row(user, _email_app(user, "R210016 Information & Digital Technology - London", "Shell"))
    assert [a["id"] for a in ad_match.candidates(app)] == [ad["id"]]
    assert ad_match.role_words("EUR - Software Engineer Grad 2026/2027") == {"software", "engineer", "grad"}


def test_an_ad_the_feed_collected_a_few_days_after_the_application_still_counts(db, user):
    ad = _ad(1, "Software Engineer")
    _age(ad["id"], 0)
    import datetime
    five_days_ago = (datetime.datetime.now() - datetime.timedelta(days=5)).isoformat()
    ten_days_ago = (datetime.datetime.now() - datetime.timedelta(days=10)).isoformat()
    assert len(ad_match.candidates(tracker.application_row(user, _email_app(user, "Software Engineer", at=five_days_ago)))) == 1
    assert ad_match.candidates(tracker.application_row(user, _email_app(user, "Software Engineer", "KLA Corp",
                                                                        at=ten_days_ago))) == []


def test_a_role_the_email_didnt_name_is_never_matched_but_can_be_picked(db, user):
    ad = _ad(1, "Software Engineer")
    app = tracker.application_row(user, _email_app(user, "Role not stated"))
    assert ad_match.candidates(app) == []
    assert [a["id"] for a in ad_match.candidates(app, any_role=True)] == [ad["id"]]


def test_the_only_candidate_is_linked_and_the_application_takes_the_ads_details(db, user):
    ad = _ad(1, "Software Engineer, London", location="London, UK")
    app_id = _email_app(user, "Software Engineer")
    assert ad_match.link_pending() == (1, 1)
    row = _row(user, app_id)
    assert (row["job_id"], row["job_url"], row["location"], row["ad_link"]) == (
        "wd-1", ad["url"], "London, UK", "matched")
    assert row["fit_checked"] is None and ad_match.link_pending() == (0, 0)


def test_two_candidates_are_left_for_the_user_unless_one_was_opened(db, user, make_user):
    a = _ad(1, "Software Engineer, Search")
    _ad(2, "Software Engineer, Ads")
    first = _email_app(user, "Software Engineer")
    assert ad_match.link_pending() == (1, 0) and _row(user, first)["ad_link"] is None
    other = make_user("other@example.com")
    tracker.record_job_open(other, a["id"])                      # someone else's open doesn't count
    tracker.record_job_open(user, a["id"])
    second = _email_app(user, "Software Engineer", company="KLA Corp")
    assert ad_match.link_pending() == (1, 1) and _row(user, second)["job_id"] == "wd-1"


def test_a_placeholder_title_takes_the_ads_when_the_user_picks_it(client, user):
    ad = _ad(1, "Graduate Data Engineer")
    app_id = _email_app(user, "Role not stated")
    ads = client.get(f"/applications/{app_id}/ads").json()
    assert [x["id"] for x in ads["ads"]] == [ad["id"]] and ads["linked"] == ""
    assert client.post(f"/applications/{app_id}/ad", json={"job_id": "nope"}).status_code == 400
    assert client.post(f"/applications/{app_id}/ad", json={"job_id": ad["id"]}).json()["job_id"] == "wd-1"
    row = _row(user, app_id)
    assert (row["job_title"], row["ad_link"]) == ("Graduate Data Engineer", "you")


def test_another_users_application_cant_be_read_or_linked(client_for, make_user, user):
    ad = _ad(1, "Software Engineer")
    app_id = _email_app(user, "Software Engineer")
    other = client_for(make_user("other@example.com"))
    assert other.get(f"/applications/{app_id}/ads").status_code == 404
    assert other.post(f"/applications/{app_id}/ad", json={"job_id": ad["id"]}).status_code == 404


def test_a_linked_application_gets_the_fit_check(db, user, monkeypatch):
    _ad(1, "Software Engineer")
    app_id = _email_app(user, "Software Engineer")
    ad_match.link_pending()
    calls = []

    async def tool(name, tool_input):
        calls.append((name, tool_input["jobs"][0]["title"]))
        return {"ranked_jobs": [{"fit_score": 72, "level_match": "strong", "skill_gaps": ["Kubernetes", 3]}]}
    monkeypatch.setattr(agent, "execute_tool", tool)
    [pending] = tracker.applications_to_fit_check()
    assert asyncio.run(ad_match.fit_check(pending)) is True
    row = _row(user, app_id)
    assert calls == [("score_job_fit", "Software Engineer")]
    assert (row["fit_score"], row["level_match"], row["skill_gaps"]) == (72, "strong", '["Kubernetes"]')
    assert tracker.applications_to_fit_check() == []


def test_an_ad_with_no_text_or_a_failed_call_is_recorded_not_retried(db, user, monkeypatch):
    jobs_db.add_jobs([make_job("wd-9", title="Software Engineer", company="KLA", description="Short.")])
    _email_app(user, "Software Engineer")
    ad_match.link_pending()

    async def no_fetch(job):
        return job
    monkeypatch.setattr(jobs_db, "ensure_full_description", no_fetch)
    [pending] = tracker.applications_to_fit_check()
    assert asyncio.run(ad_match.fit_check(pending)) is True and tracker.applications_to_fit_check() == []

    _ad(2, "Data Engineer")
    _email_app(user, "Data Engineer")
    ad_match.link_pending()

    async def broken(name, tool_input):
        raise RuntimeError("model down")
    monkeypatch.setattr(agent, "execute_tool", broken)
    [pending] = tracker.applications_to_fit_check()
    assert asyncio.run(ad_match.fit_check(pending)) is False and tracker.applications_to_fit_check() == []


def test_i_applied_tracks_the_job_with_its_ad_and_the_pages_fit(client, user):
    ad = _ad(1, "Graduate Software Engineer")
    job = {"id": ad["id"], "job_id": "wd-1", "title": ad["title"], "company": "KLA Corporation", "url": ad["url"],
           "location": "London, UK"}
    out = client.post("/jobs/applied", json={"job": job, "fit": {"fit_score": 81, "level_match": "ok",
                                                                 "skill_gaps": ["Go"]}}).json()
    row = _row(user, out["id"])
    assert out["status"] == "Applied" and (row["ad_link"], row["job_id"], row["fit_score"]) == ("you", "wd-1", 81)
    assert row["date_applied"] and tracker.applications_to_fit_check() == []
    assert client.post("/jobs/applied", json={"job": {"title": "x"}}).status_code == 400


def test_i_applied_moves_a_saved_job_on_and_leaves_a_later_stage_alone(client, user):
    job = {"job_id": "wd-1", "title": "Quant Developer", "company": "Optiver", "url": "https://jobs.example.com/1"}
    client.post("/jobs/save", json={"job": job})
    assert client.post("/jobs/applied", json={"job": job}).json()["status"] == "Applied"
    app_id = tracker.find_application_id(user, "Optiver", "Quant Developer")
    tracker.update_status(app_id, "Interview", user_id=user)
    assert client.post("/jobs/applied", json={"job": job}).json()["status"] == "Interview"


def test_opening_a_posting_is_recorded_for_real_jobs_only(client, user):
    ad = _ad(1, "Software Engineer")
    assert client.post(f"/jobs/{ad['id']}/opened").json() == {"ok": True}
    assert client.post("/jobs/nope/opened").status_code == 404
    assert ad["id"] in tracker.opened_jobs(user)
