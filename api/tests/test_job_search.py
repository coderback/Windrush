"""Live multi-source search: correct inputs per source, fixture handling, Adzuna routing."""
import asyncio
from unittest.mock import MagicMock

import httpx
import pytest

from app import job_searcher

LIVE_SOURCES = ("_search_level1_playwright", "_search_level2_ats_apis", "_search_level3_websearch",
                "_search_level4_adzuna")


async def _empty(*args, **kwargs):
    return []


def test_ats_level_gets_word_keywords_not_characters(monkeypatch):
    seen = {}

    async def fake_greenhouse(slug, name, keywords):
        seen["kw"] = sorted(keywords)
        return [{"title": "Graduate Software Engineer", "company": name, "url": f"https://x/{slug}"}]

    monkeypatch.setattr(job_searcher, "_fetch_greenhouse", fake_greenhouse)
    for name in ("_fetch_ashby", "_fetch_lever", "_fetch_workable", "_fetch_smartrecruiters",
                 "_search_level1_playwright", "_search_level3_websearch", "_search_level4_adzuna"):
        monkeypatch.setattr(job_searcher, name, _empty)

    jobs = asyncio.run(job_searcher.search_jobs_multi("software engineer", "London"))
    assert seen["kw"] == ["engineer", "software"]
    assert jobs and jobs[0]["title"] == "Graduate Software Engineer" and jobs[0].get("source") != "fixture"


def test_fixture_fallback_is_marked_and_copied(monkeypatch):
    for name in LIVE_SOURCES:
        monkeypatch.setattr(job_searcher, name, _empty)
    jobs = asyncio.run(job_searcher.search_jobs_multi("anything", "London"))
    assert jobs and all(j["source"] == "fixture" for j in jobs)
    jobs[0]["title"] = "MUTATED"
    assert job_searcher._FIXTURE[0]["title"] != "MUTATED"


@pytest.mark.parametrize("location, country", [
    ("Sydney, Australia", "au"), ("Austin, US", "us"), ("New York", "us"), ("Toronto", "ca"),
    ("London", "gb"), ("Houston", "gb"), ("Belarus", "gb"),
])
def test_adzuna_routes_by_whole_words(monkeypatch, location, country):
    urls = []

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, params=None):
            urls.append(url)
            return httpx.Response(200, json={"results": []}, request=httpx.Request("GET", url))

    monkeypatch.setattr(job_searcher, "ADZUNA_APP_ID", "id")
    monkeypatch.setattr(job_searcher, "ADZUNA_API_KEY", "key")
    monkeypatch.setattr(job_searcher, "http_client", MagicMock(async_client=FakeClient))
    asyncio.run(job_searcher._search_level4_adzuna("engineer", location))
    assert urls[0].split("/jobs/")[1].split("/")[0] == country
