"""Careers pages that load the job from Greenhouse or Ashby are read from that system; a careers page's own title is
never taken for the job's; an ad with no text isn't scored; and a badly read job can be reported."""
import asyncio
from unittest.mock import MagicMock

import httpx
import pytest

from app import job_searcher, jobs_db, main
from tests.conftest import make_job

ASHBY_ID = "c7c68a81-188a-463c-96b7-0bdfac6be655"
AD = "We're hiring a machine learning engineer to build ranking models. " * 6


def _fake_http(monkeypatch, routes: dict) -> list[str]:
    """http_client.async_client answering each URL from routes (status, json); anything else is a 404."""
    asked: list[str] = []

    class Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, **k):
            asked.append(url)
            status, body = routes.get(url, (404, {}))
            return httpx.Response(status, json=body, request=httpx.Request("GET", url))
    monkeypatch.setattr(job_searcher, "http_client", MagicMock(async_client=Client))
    return asked


def test_a_greenhouse_job_on_the_employers_own_page_is_read_from_greenhouse(monkeypatch):
    asked = _fake_http(monkeypatch, {
        "https://boards-api.greenhouse.io/v1/boards/mako/jobs/8921970002": (200, {
            "title": "Graduate Software Engineer, London", "location": {"name": "London"},
            "content": "&lt;p&gt;We are looking for inquisitive problem solvers&lt;/p&gt;"}),
        "https://boards-api.greenhouse.io/v1/boards/mako": (200, {"name": "Mako"}),
    })
    page = '<script src="https://boards.greenhouse.io/embed/job_board/js?for=mako"></script>'
    job = asyncio.run(job_searcher.embedded_job(
        "https://www.mako.com/opportunities/job-listing?gh_jid=8921970002&gh_src=q4jaczou2us", page))
    assert job == {"title": "Graduate Software Engineer, London", "company": "Mako", "location": "London",
                   "description": "We are looking for inquisitive problem solvers", "job_id": "gh-8921970002"}
    assert all(u.startswith("https://boards-api.greenhouse.io/") for u in asked)


def test_an_ashby_job_is_found_on_the_board_named_after_the_site(monkeypatch):
    _fake_http(monkeypatch, {"https://api.ashbyhq.com/posting-api/job-board/quantcast": (200, {"jobs": [
        {"id": "0076d9cc-80d9-43a6-96b3-56407b0cd851", "title": "Marketing Manager", "location": "Toronto"},
        {"id": ASHBY_ID, "title": "Machine Learning Engineer", "location": "London", "descriptionPlain": AD}]})})
    page = '<meta property="og:site_name" content="Quantcast"><title>Careers List</title>'
    job = asyncio.run(job_searcher.embedded_job(f"https://www.quantcast.com/careers-list?id={ASHBY_ID}", page))
    assert (job["title"], job["company"], job["location"], job["job_id"]) == (
        "Machine Learning Engineer", "Quantcast", "London", f"ashby-{ASHBY_ID}")
    assert job["description"] == AD.strip()


@pytest.mark.parametrize("url", [
    "https://www.quantcast.com/careers-list",                                  # no job id in the link
    "https://www.quantcast.com/careers-list?id=42",                            # not an Ashby id
    f"https://www.quantcast.com/careers-list?id={ASHBY_ID.replace('c7', 'ff')}",  # no board has it
    "https://job-boards.greenhouse.io/mako/jobs/8921970002?gh_jid=8921970002",  # the system's own page
])
def test_no_embedded_job_when_the_link_or_the_board_says_nothing(monkeypatch, url):
    _fake_http(monkeypatch, {"https://api.ashbyhq.com/posting-api/job-board/quantcast": (200, {"jobs": [
        {"id": ASHBY_ID, "title": "Machine Learning Engineer", "descriptionPlain": AD}]})})
    assert asyncio.run(job_searcher.embedded_job(url, "")) == {}


@pytest.mark.parametrize("title, names, page", [
    ("Careers List", (), True), ("Job Listing | Mako", ("mako",), True), ("Quantcast Careers", ("Quantcast",), True),
    ("Careers at Mako", ("mako",), True), ("Open Positions", (), True), ("Job Application", (), True),
    ("Mako", ("Mako",), True),
    ("Graduate Software Engineer | Mako", ("mako",), False), ("Machine Learning Engineer", (), False),
    ("Careers Adviser", (), False), ("Data Engineer", ("Data Ltd",), False),
])
def test_a_careers_pages_own_title_is_told_from_a_jobs(title, names, page):
    assert job_searcher._is_page_title(title, *names) is page


def _page(monkeypatch, html: str, description: str = "") -> None:
    async def ok(url):
        return None

    async def fetched(client, url):
        return type("Page", (), {"text": html, "raise_for_status": lambda self: None})()

    async def text(url, max_chars=8000):
        return description

    async def nothing(url, raw_html=""):
        return {}
    monkeypatch.setattr(job_searcher.net_guard, "assert_public_url", ok)
    monkeypatch.setattr(job_searcher.net_guard, "safe_get", fetched)
    monkeypatch.setattr(job_searcher, "fetch_full_description", text)
    monkeypatch.setattr(job_searcher, "embedded_job", nothing)


def test_an_empty_careers_page_is_not_read_as_a_job(monkeypatch):
    _page(monkeypatch, '<meta property="og:title" content="Careers List"><title>Careers List</title>')
    with pytest.raises(ValueError, match="Couldn't read that listing"):
        asyncio.run(job_searcher.scrape_job_from_url("https://www.quantcast.com/careers-list"))


def test_a_page_title_is_passed_over_for_the_job_title(monkeypatch):
    _page(monkeypatch, '<meta property="og:title" content="Job Listing | Mako"><h1>Graduate Software Engineer</h1>', AD)
    job = asyncio.run(job_searcher.scrape_job_from_url("https://www.mako.com/opportunities/job-listing"))
    assert job["title"] == "Graduate Software Engineer"


def test_greenhouses_page_title_gives_the_role(monkeypatch):
    _page(monkeypatch, "<title>Job Application for Software Engineer at Catapult</title>", AD)
    job = asyncio.run(job_searcher.scrape_job_from_url("https://www.catapult.com/jobs/1"))
    assert job["title"] == "Software Engineer"


def test_a_pasted_careers_page_uses_the_feeds_own_copy_of_the_job(client, monkeypatch):
    jobs_db.add_jobs([make_job("gh-8921970002", title="Graduate Software Engineer, London", company="Mako Trading",
                               description=AD, level="junior")])

    async def scraped(url):
        return {"id": "x", "job_id": "y", "title": "Graduate Software Engineer, London", "company": "Mako",
                "description": AD, "url": url, "source": "user-url", "ats_job_id": "gh-8921970002"}
    monkeypatch.setattr(job_searcher, "scrape_job_from_url", scraped)
    job = client.post("/jobs/from-url", json={"url": "https://www.mako.com/x?gh_jid=8921970002"}).json()["job"]
    assert (job["company"], job["level"], job["job_id"]) == ("Mako Trading", "junior", "gh-8921970002")


@pytest.mark.parametrize("title, level", [("Software Engineer", ""), ("Graduate Software Engineer", "junior"),
                                          ("Senior Software Engineer", "senior")])
def test_with_no_ad_text_only_the_titles_own_rank_sets_the_level(client, monkeypatch, title, level):
    async def scraped(url):
        return {"id": "x", "job_id": "y", "title": title, "company": "Acme", "description": "", "url": url,
                "source": "user-url", "ats_job_id": ""}
    monkeypatch.setattr(job_searcher, "scrape_job_from_url", scraped)
    assert client.post("/jobs/from-url", json={"url": "https://acme.example/jobs/1"}).json()["job"]["level"] == level


def test_an_ad_with_no_text_is_not_scored(client, monkeypatch):
    scored = []

    async def as_is(job):
        return job

    async def tool(name, tool_input):
        scored.append(name)
        return {"ranked_jobs": []}
    monkeypatch.setattr(main.jobs_db, "ensure_full_description", as_is)
    monkeypatch.setattr(main, "execute_tool", tool)
    body = client.post("/jobs/analyze", json={"job": {"title": "Careers List", "description": ""}}).text
    assert '"type": "no_text"' in body and scored == []
    client.post("/jobs/analyze", json={"job": {"title": "ML Engineer", "description": AD}})
    assert scored == ["score_job_fit"]


def test_a_badly_read_job_can_be_reported_and_listed(client, client_for, make_user):
    job = {"id": "abc", "title": "Careers List", "company": "Unknown", "level": "mid", "source": "user-url",
           "url": "https://www.quantcast.com/careers-list?id=1", "description": ""}
    assert client.post("/jobs/report", json={"job": job, "note": "It's an ML Engineer job"}).status_code == 200
    reports = client.get("/jobs/reports").json()["reports"]
    assert len(reports) == 1
    assert {k: reports[0][k] for k in ("title", "url", "level", "text_chars", "note")} == {
        "title": "Careers List", "url": job["url"], "level": "mid", "text_chars": 0, "note": "It's an ML Engineer job"}
    assert client.post("/jobs/report", json={"job": {}, "note": "?"}).status_code == 400
    assert client_for(make_user("other@example.com")).get("/jobs/reports").json()["reports"] == []
