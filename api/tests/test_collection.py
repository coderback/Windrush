"""Scheduled collection: one pass over the sources for every target title, the run recorded, the web
search once a day, and jobs nobody lists any more expired."""
import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from conftest import make_job

from app import discovery, job_searcher, jobs_db, tracker


@pytest.fixture
def user(db):
    uid = tracker.create_user("collect@x.com", "h")
    tracker.update_user_persona(uid, {"preferences": {
        "target_titles": ["Graduate Software Engineer", "quant developer ", "Quant Developer"],
        "preferred_locations": ["London", "Remote", "United Kingdom"],
    }})
    return uid


@pytest.fixture
def collected(monkeypatch):
    calls = []

    async def fake(queries, locations, web_search=True):
        calls.append((queries, locations, web_search))
        return [make_job(1, "Graduate Software Engineer", "Acme"), make_job(2, "Quant Developer", "Hedge")]
    monkeypatch.setattr(discovery, "collect_jobs", fake)
    return calls


def _age(job_id: str, days: float) -> None:
    then = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    con = sqlite3.connect(jobs_db._DB_PATH)
    con.execute("UPDATE jobs SET updated_at = ?, created_at = ? WHERE job_id = ?", (then, then, job_id))
    con.commit()
    con.close()


def _visible() -> list[str]:
    return sorted(j["job_id"] for j in jobs_db.get_jobs(limit=50)[0])


# ── One pass over the sources ─────────────────────────────────────────────────

def test_every_board_is_fetched_once_for_all_titles(monkeypatch):
    calls = []

    async def l1(keywords):
        calls.append(("l1", sorted(keywords)))
        return []

    async def l2(queries):
        calls.append(("l2", queries))
        return [{"title": "Graduate Software Engineer", "company": "A", "location": "London", "url": "https://a/1"},
                {"title": "Quantitative Developer", "company": "B", "location": "London", "url": "https://b/1"},
                {"title": "Account Executive", "company": "C", "location": "London", "url": "https://c/1"}]

    async def l3():
        calls.append(("l3",))
        return []

    async def adzuna(query, location):
        calls.append(("adzuna", query, location))
        return [{"title": "Quant Developer", "company": "D", "location": f"{location}, UK", "url": f"https://d/{location}"}]
    monkeypatch.setattr(job_searcher, "_search_level1_playwright", l1)
    monkeypatch.setattr(job_searcher, "_search_level2_ats_apis", l2)
    monkeypatch.setattr(job_searcher, "_search_level3_websearch", l3)
    monkeypatch.setattr(job_searcher, "_search_level4_adzuna", adzuna)

    jobs = asyncio.run(job_searcher.collect_jobs(["Graduate Software Engineer", "Quant Developer"],
                                                 ["London", "Manchester"], web_search=False))
    assert calls[:2] == [("l1", ["developer", "engineer", "graduate", "quant", "software"]),
                         ("l2", ["Graduate Software Engineer", "Quant Developer"])]
    assert sorted(c for c in calls if c[0] == "adzuna") == [
        ("adzuna", q, loc) for q in ("Graduate Software Engineer", "Quant Developer") for loc in ("London", "Manchester")]
    assert ("l3",) not in calls  # the web search is skipped when it isn't due
    # The same Adzuna job found by both titles is one posting.
    assert sorted(j["url"] for j in jobs) == ["https://a/1", "https://b/1", "https://d/London", "https://d/Manchester"]


# ── A collection ──────────────────────────────────────────────────────────────

def test_a_collection_searches_every_title_once_and_records_the_run(user, ollama, collected):
    run = asyncio.run(discovery.collect())
    # Titles without repeats; "Remote" isn't a place to search.
    assert collected == [(["Graduate Software Engineer", "quant developer"], ["London", "United Kingdom"], True)]
    assert (run["found"], run["added"], run["refreshed"], run["expired"], run["error"]) == (2, 2, 0, 0, None)
    assert run["finished_at"] and _visible() == ["1", "2"]


def test_the_web_search_runs_once_a_day(user, ollama, collected, monkeypatch):
    asyncio.run(discovery.collect())
    asyncio.run(discovery.collect())
    assert [web for _, _, web in collected] == [True, False]
    con = sqlite3.connect(jobs_db._DB_PATH)
    con.execute("UPDATE source_runs SET ran_at = ?", ((datetime.now(timezone.utc) - timedelta(days=1, minutes=1)).isoformat(),))
    con.commit()
    con.close()
    asyncio.run(discovery.collect())
    assert collected[-1][2] is True


def test_the_feeds_discovery_shares_the_daily_web_search(user, ollama, collected, monkeypatch):
    searches = []

    async def search(query, locations, web_search=True):
        searches.append(web_search)
        return []
    monkeypatch.setattr(discovery, "search_jobs", search)
    asyncio.run(discovery.collect())
    asyncio.run(discovery._discover("Data Analyst", ["London"]))
    assert searches == [False]


def test_no_target_title_means_no_collection(db, collected):
    tracker.create_user("blank@x.com", "h")
    assert asyncio.run(discovery.collect()) is None and collected == []
    assert jobs_db.last_collection() is None


def test_a_failed_collection_is_recorded(user, monkeypatch):
    async def broken(queries, locations, web_search=True):
        raise RuntimeError("worker died")
    monkeypatch.setattr(discovery, "collect_jobs", broken)
    with pytest.raises(RuntimeError):
        asyncio.run(discovery.collect())
    run = jobs_db.last_collection()
    assert run["finished_at"] and run["error"] == "RuntimeError: worker died"


# ── Expiry ────────────────────────────────────────────────────────────────────

def test_jobs_nobody_lists_any_more_expire_and_come_back_when_listed(user, ollama, collected):
    jobs_db.add_jobs([make_job("old", "Data Engineer"), make_job("recent", "ML Engineer")])
    _age("old", 4)
    _age("recent", 2)
    run = asyncio.run(discovery.collect())
    assert run["expired"] == 1 and _visible() == ["1", "2", "recent"]
    assert jobs_db.get_job(jobs_db.get_jobs(limit=50)[0][0]["id"])  # rows stay readable

    jobs_db.add_jobs([make_job("old", "Data Engineer")])  # a source lists it again
    assert _visible() == ["1", "2", "old", "recent"]


def test_a_collection_that_finds_nothing_expires_nothing(user, ollama, monkeypatch):
    async def nothing(queries, locations, web_search=True):
        return []
    monkeypatch.setattr(discovery, "collect_jobs", nothing)
    jobs_db.add_jobs([make_job("old", "Data Engineer")])
    _age("old", 10)
    assert asyncio.run(discovery.collect())["expired"] == 0 and _visible() == ["old"]


def test_an_expired_job_page_still_opens(db, ollama):
    jobs_db.add_jobs([make_job("gone", "Data Engineer")])
    _age("gone", 5)
    assert jobs_db.expire_unseen((datetime.now(timezone.utc) - timedelta(days=3)).isoformat()) == 1
    (row_id,) = sqlite3.connect(jobs_db._DB_PATH).execute("SELECT id FROM jobs").fetchone()
    assert jobs_db.get_job(row_id)["title"] == "Data Engineer" and _visible() == []


# ── The schedule ──────────────────────────────────────────────────────────────

def test_a_collection_is_due_by_when_the_last_one_started(db, monkeypatch):
    monkeypatch.setattr(discovery, "_COLLECT_EVERY_S", 6 * 3600)
    now = datetime.now(timezone.utc)
    assert discovery._collection_due(now)
    run_id = jobs_db.start_collection(["x"], ["London"])
    jobs_db.finish_collection(run_id, error="boom")  # a failed run still counts
    assert not discovery._collection_due(now + timedelta(hours=5))
    assert discovery._collection_due(now + timedelta(hours=6, minutes=1))


def test_collection_can_be_turned_off(monkeypatch, collected):
    monkeypatch.setattr(discovery, "_COLLECT_EVERY_S", 0)
    asyncio.run(asyncio.wait_for(discovery.keep_collecting(), timeout=1))
    assert collected == []
