"""Sponsorship in the job store, the feed filter, the user's marks and the sponsor register."""
import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from conftest import make_job

from app import auth, discovery, http_client, jobs_db, main, sponsor_register, tracker

SPONSORS = {"acme": ("Acme Ltd", "London"), "orbital robotics": ("Orbital Robotics Limited", "Bristol")}

ADS = {
    "offers": "Visa sponsorship is available for this role.",
    "refuses": "Unfortunately we are unable to offer visa sponsorship.",
    "clearance": "You must be able to obtain SC clearance.",
    "silent": "Join our team building things.",
}


def _store(*jobs):
    jobs_db.add_jobs(list(jobs))
    con = sqlite3.connect(jobs_db._DB_PATH)
    ids = dict(con.execute("SELECT title, id FROM jobs").fetchall())
    con.close()
    return ids


def _titles(**kwargs):
    jobs, _ = jobs_db.get_jobs(limit=50, **kwargs)
    return sorted(j["title"] for j in jobs)


@pytest.fixture
def feed(db, ollama):
    """Five ads (one per signal, plus a silent one at a licensed sponsor) and the register."""
    jobs_db.replace_sponsors(SPONSORS, "https://example.gov.uk/register.csv")
    return _store(
        make_job(1, "Offers", "Startup Co", description=ADS["offers"]),
        make_job(2, "Refuses", "Acme Ltd", description=ADS["refuses"]),   # licensed, but this ad says no
        make_job(3, "Clearance", "Defence Co", description=ADS["clearance"]),
        make_job(4, "Silent sponsor", "Orbital Robotics", description=ADS["silent"]),
        make_job(5, "Silent", "Unknown Co", description=ADS["silent"]),
    )


def test_stored_jobs_carry_their_signals_and_only_offers_are_tagged(feed):
    jobs = {j["title"]: j for j in jobs_db.get_jobs(limit=50)[0]}
    assert jobs["Offers"]["sponsorship"] == "offered" and "sponsorship" in jobs["Offers"]["tags"]
    assert jobs["Refuses"]["sponsorship"] == "not_offered" and "sponsorship" not in jobs["Refuses"]["tags"]
    assert jobs["Refuses"]["sponsorship_evidence"] == ADS["refuses"]
    assert jobs["Clearance"]["clearance"] == "SC"
    assert [t for t, j in jobs.items() if j["licensed_sponsor"]] == ["Refuses", "Silent sponsor"]
    assert _titles(tags=["sponsorship"]) == ["Offers"]        # the tag filter no longer finds "we cannot sponsor"


def test_sponsorship_filters(feed):
    assert len(_titles(sponsorship="any")) == len(_titles()) == 5
    assert _titles(sponsorship="possible") == ["Offers", "Silent", "Silent sponsor"]
    assert _titles(sponsorship="likely") == ["Offers", "Silent sponsor"]


def test_the_users_marks_win_over_the_ad_and_the_register(feed):
    marks = {feed["Refuses"]: "offered", feed["Silent sponsor"]: "not_offered", feed["Silent"]: "offered"}
    assert _titles(sponsorship="possible", marks=marks) == ["Offers", "Refuses", "Silent"]
    assert _titles(sponsorship="likely", marks=marks) == ["Offers", "Refuses", "Silent"]


def test_the_full_ad_updates_the_signals(feed):
    jobs_db.update_description(feed["Silent"], "Great team. We cannot sponsor visas. Must be SC cleared.")
    job = jobs_db.get_job(feed["Silent"])
    assert (job["sponsorship"], job["clearance"]) == ("not_offered", "SC")
    assert jobs_db.get_job(feed["Silent sponsor"])["sponsor_name"] == "Orbital Robotics Limited"


def test_jobs_stored_before_the_signals_get_them_once(db, ollama, tmp_path):
    path = str(tmp_path / "old_jobs.db")
    jobs_db.init_db(path)
    con = sqlite3.connect(path)
    con.execute("PRAGMA user_version = 1")
    con.execute("INSERT INTO jobs (id, job_id, title, company, normalized_company, location, description, level, "
                "source, created_at) VALUES ('a', '1', 'Engineer', 'Acme Ltd', 'acme', 'London', ?, 'mid', 'ats', "
                "'2026-01-01')", (ADS["refuses"],))
    con.commit()
    con.close()

    jobs_db.init_db(path)
    con = sqlite3.connect(path)
    assert con.execute("SELECT sponsorship, sponsor_key FROM jobs WHERE id='a'").fetchone() == ("not_offered", "acme")
    assert con.execute("PRAGMA user_version").fetchone()[0] == 2


# ── The register ─────────────────────────────────────────────────────────────

REGISTER_CSV = (
    "﻿Organisation Name,Town/City,County,Type & Rating,Route\n"
    "Acme Ltd,London,,Worker (A rating),Skilled Worker\n"
    "Acme Ltd,London,,Worker (A rating),Global Business Mobility: Senior or Specialist Worker\n"
    "Northwind Holdings Limited T/A Rocket Labs,Leeds,,Worker (A rating),Skilled Worker\n"
    "Grace Church,York,,Worker (A rating),Religious Worker\n"
)


def test_the_register_keeps_skilled_worker_sponsors_under_every_name():
    parsed = sponsor_register.parse_register(REGISTER_CSV.lstrip("﻿"))
    assert parsed == {"acme": ("Acme Ltd", "London"),
                      "northwind": ("Northwind Holdings Limited T/A Rocket Labs", "Leeds"),
                      "rocket labs": ("Northwind Holdings Limited T/A Rocket Labs", "Leeds")}


@pytest.fixture
def fake_gov_uk(monkeypatch):
    """gov.uk serving the publication page and a register of `rows` sponsors."""
    served = {"rows": 20_000, "hits": 0}
    link = "https://assets.publishing.service.gov.uk/media/abc/SP_-_Worker_Register_-_2026-10-15.csv"

    def handler(request: httpx.Request) -> httpx.Response:
        served["hits"] += 1
        if request.url.host == "www.gov.uk":
            return httpx.Response(200, text=f'<a href="{link}">Register (CSV)</a>')
        body = "Organisation Name,Town/City,County,Type & Rating,Route\n" + "".join(
            f"Org {i} Ltd,Leeds,,Worker (A rating),Skilled Worker\n" for i in range(served["rows"]))
        return httpx.Response(200, content=body.encode())
    monkeypatch.setattr(http_client, "async_client",
                        lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return served


def test_refresh_stores_the_register_then_waits_a_week(db, fake_gov_uk):
    assert asyncio.run(sponsor_register.refresh()) == 20_000
    assert jobs_db.licensed_sponsor("org 7") == ("Org 7 Ltd", "Leeds")
    fetched = jobs_db.sponsor_register_fetched_at()
    assert datetime.now(timezone.utc) - fetched < timedelta(minutes=1)

    hits = fake_gov_uk["hits"]
    assert asyncio.run(sponsor_register.refresh()) is None and fake_gov_uk["hits"] == hits   # fresh: no download
    assert asyncio.run(sponsor_register.refresh(force=True)) == 20_000


def test_a_truncated_register_keeps_the_stored_one(db, fake_gov_uk):
    jobs_db.replace_sponsors(SPONSORS, "old")
    fake_gov_uk["rows"] = 50
    with pytest.raises(ValueError, match="only 50"):
        asyncio.run(sponsor_register.refresh(force=True))
    assert jobs_db.licensed_sponsor("acme") == ("Acme Ltd", "London")


def test_the_background_refresher_survives_a_failure(db, monkeypatch):
    calls = []

    async def failing_refresh():
        calls.append(1)
        raise httpx.ConnectError("offline")

    async def stop(_seconds):
        raise asyncio.CancelledError
    monkeypatch.setattr(sponsor_register, "refresh", failing_refresh)
    monkeypatch.setattr(sponsor_register.asyncio, "sleep", stop)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(sponsor_register.keep_fresh())     # logged, then on to the daily wait
    assert calls == [1]


# ── The API ──────────────────────────────────────────────────────────────────

@pytest.fixture
def api_user(feed, monkeypatch):
    monkeypatch.setattr(discovery, "ensure", lambda *a, **k: False)
    uid = tracker.create_user("sponsor@x.com", "h")
    main.app.dependency_overrides[auth.get_current_user] = lambda: auth.User(id=uid, email="sponsor@x.com")
    from fastapi.testclient import TestClient
    yield uid, TestClient(main.app)
    main.app.dependency_overrides.clear()


def _feed_titles(client, **params):
    body = client.get("/jobs", params={"location": "London", **params}).json()
    return body["sponsorship"], sorted(j["title"] for j in body["jobs"])


def test_the_feed_hides_jobs_that_rule_out_a_candidate_who_needs_sponsorship(api_user):
    uid, client = api_user
    assert _feed_titles(client)[0] == "any"                                  # not answered: no filter
    tracker.update_user_persona(uid, {"core_info": {"require_sponsorship": True}})
    assert _feed_titles(client) == ("possible", ["Offers", "Silent", "Silent sponsor"])
    assert _feed_titles(client, sponsorship="any")[0] == "any"               # asking for everything wins
    assert _feed_titles(client, sponsorship="likely") == ("likely", ["Offers", "Silent sponsor"])


def test_marking_a_job(api_user, feed):
    uid, client = api_user
    job_id = feed["Silent"]
    assert client.get(f"/jobs/{job_id}/sponsorship").json()["mark"] == ""
    marked = client.put(f"/jobs/{job_id}/sponsorship", json={"mark": "offered"}).json()
    assert marked["mark"] == "offered" and marked["sponsorship"] == ""
    assert _feed_titles(client, sponsorship="likely")[1] == ["Offers", "Silent", "Silent sponsor"]
    row = next(j for j in client.get("/jobs", params={"location": "London"}).json()["jobs"] if j["id"] == job_id)
    assert row["sponsorship_mark"] == "offered"

    assert client.put(f"/jobs/{job_id}/sponsorship", json={"mark": None}).json()["mark"] == ""
    assert tracker.get_job_marks(uid) == {}
    assert client.put(f"/jobs/{job_id}/sponsorship", json={"mark": "maybe"}).status_code == 422
    assert client.put("/jobs/nope/sponsorship", json={"mark": "offered"}).status_code == 404


def test_the_sponsorship_view_names_the_licensed_sponsor(api_user, feed):
    _, client = api_user
    view = client.get(f"/jobs/{feed['Refuses']}/sponsorship").json()
    assert view == {"sponsorship": "not_offered", "evidence": ADS["refuses"], "clearance": "",
                    "licensed_sponsor": True, "sponsor_name": "Acme Ltd", "mark": ""}
