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

    jobs = asyncio.run(job_searcher.search_jobs_multi("software engineer", ["London"]))
    assert seen["kw"] == ["engineer", "software"]
    assert jobs and jobs[0]["title"] == "Graduate Software Engineer" and jobs[0].get("source") != "fixture"


def test_fixture_fallback_is_marked_and_copied(monkeypatch):
    for name in LIVE_SOURCES:
        monkeypatch.setattr(job_searcher, name, _empty)
    jobs = asyncio.run(job_searcher.search_jobs_multi("anything", ["London"]))
    assert jobs and all(j["source"] == "fixture" for j in jobs)
    jobs[0]["title"] = "MUTATED"
    assert job_searcher._FIXTURE[0]["title"] != "MUTATED"


def test_only_the_location_dependent_level_fans_out_over_locations(monkeypatch):
    calls = []

    def recorder(name):
        async def fake(*args):
            calls.append((name, *args))
            return []
        return fake
    for name in LIVE_SOURCES[:3]:
        monkeypatch.setattr(job_searcher, name, recorder(name))

    async def fake_adzuna(query, location):
        calls.append(("_search_level4_adzuna", query, location))
        return [{"title": f"Graduate Software Engineer {i}", "company": f"{location} Co {i}",
                 "url": f"https://x/{location}/{i}"} for i in range(15)]
    monkeypatch.setattr(job_searcher, "_search_level4_adzuna", fake_adzuna)

    jobs = asyncio.run(job_searcher.search_jobs_multi("software engineer", ["London", "Toronto"]))
    assert sorted(c[0] for c in calls) == sorted(LIVE_SOURCES[:3]) + ["_search_level4_adzuna"] * 2
    assert sorted(c[2] for c in calls if c[0] == "_search_level4_adzuna") == ["London", "Toronto"]
    assert len(jobs) == 30  # no location crowds the other's out


def test_same_role_in_two_locations_keeps_both_postings(monkeypatch):
    for name in LIVE_SOURCES[:3]:
        monkeypatch.setattr(job_searcher, name, _empty)

    async def fake_ats(queries):
        return [{"title": "Graduate Software Engineer", "company": "Sky", "url": "https://sky/1"}]
    monkeypatch.setattr(job_searcher, "_search_level2_ats_apis", fake_ats)

    async def fake_adzuna(query, location):
        return [
            {"title": "Software Engineer", "company": "BBC", "url": f"https://adzuna/{location}/1"},
            # Reposted in the same location, and a listing the ATS level already found.
            {"title": "Software Engineer", "company": "BBC", "url": f"https://adzuna/{location}/1-repost"},
            {"title": "Graduate Software Engineer", "company": "Sky", "url": f"https://adzuna/{location}/2"},
        ]
    monkeypatch.setattr(job_searcher, "_search_level4_adzuna", fake_adzuna)

    jobs = asyncio.run(job_searcher.search_jobs_multi("software engineer", ["London", "Manchester"]))
    # BBC's posting survives in both locations; repeats within a location or of levels 1-3 don't.
    assert sorted(j["url"] for j in jobs) == ["https://adzuna/London/1", "https://adzuna/Manchester/1",
                                              "https://sky/1"]


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


def test_a_failed_adzuna_call_never_logs_the_key(monkeypatch, caplog):
    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, params=None):
            request = httpx.Request("GET", url, params=params)
            return httpx.Response(429, request=request)

    monkeypatch.setattr(job_searcher, "ADZUNA_APP_ID", "the-app-id")
    monkeypatch.setattr(job_searcher, "ADZUNA_API_KEY", "the-secret-key")
    monkeypatch.setattr(job_searcher, "http_client", MagicMock(async_client=FakeClient))
    with caplog.at_level("DEBUG"):
        assert asyncio.run(job_searcher._search_level4_adzuna("engineer", "London")) == []
    assert "HTTP 429" in caplog.text
    assert "the-secret-key" not in caplog.text and "the-app-id" not in caplog.text


# ── Title filter ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("title, query, expected", [
    ("Graduate Software Engineer", "", True),
    ("International Graduate Programme", "", True),  # "intern" is a whole word, not part of "International"
    ("Software Engineer Intern", "", False),
    ("Software Engineering Internship", "", False),
    ("Senior Machine Learning Engineer", "", False),
    ("Engineering Manager", "", False),
    ("Email Marketing Executive", "", False),          # "AI" isn't part of "email"
    ("HTML Email Designer", "", False),                # nor "ML" of "HTML"
    ("Quantitative Developer", "", True),
    ("Data Engineer", "", True),
    ("Data Scientist", "", True),
    ("Frontend Engineer", "", True),
    ("Java Developer", "", False),
    ("JavaScript Developer", "", True),
    ("Engineering 26 open positions", "", False),
    ("Arm Job Search Results for Graduate", "", False),
    ("Graduate Careers Search for Jobs", "", False),
    # Every word of the search names the role even when no listed role word does.
    ("Trading Systems Engineer", "trading systems engineer", True),
    ("Trading Systems Engineer", "", False),
    ("Quantitative Trader", "quant trader", True),     # 4+ letter words may run on
    ("HTML Engineer", "ml engineer", False),           # short ones may not
])
def test_title_filter(title, query, expected):
    assert job_searcher._passes_title_filter(title, query) is expected


# ── Locations ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("item, expected", [
    ({"location": {"name": "Hybrid"}, "offices": [{"name": "London", "location": "London, United Kingdom"},
                                                   {"name": "Austin, TX", "location": ""}]},
     "London, United Kingdom; Austin, TX (Hybrid)"),
    ({"location": {"name": "Hybrid"}, "offices": []}, "Hybrid"),
    ({"location": {"name": "Multiple Locations"}, "offices": [{"name": "Lisbon", "location": "Lisbon, Portugal"}]},
     "Lisbon, Portugal"),
    ({"location": {"name": "London, UK"}, "offices": [{"location": "Elsewhere"}]}, "London, UK"),
    ({"location": {}}, ""),
])
def test_greenhouse_location_reads_offices_when_the_location_is_a_setting(item, expected):
    assert job_searcher._greenhouse_location(item) == expected


@pytest.mark.parametrize("item, expected", [
    ({"location": "London", "secondaryLocations": [{"location": "Paris"}], "workplaceType": "Hybrid"},
     "London; Paris (Hybrid)"),
    ({"location": "India", "isRemote": True, "workplaceType": "Remote"}, "India (Remote)"),
    ({"location": "Remote", "isRemote": True}, "Remote"),
    ({"location": {"locationName": "Berlin"}}, "Berlin"),
    ({"locationName": "Dublin", "workplaceType": "OnSite"}, "Dublin (On-site)"),
    ({}, ""),
])
def test_ashby_location(item, expected):
    assert job_searcher._ashby_location(item) == expected


def _fake_client(payload):
    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, params=None):
            return httpx.Response(200, json=payload, request=httpx.Request("GET", url))
    return MagicMock(async_client=FakeClient)


def test_ashby_boards_with_a_string_location_are_read(monkeypatch):
    # The posting API gives `location` as a string; reading it as a dict raised, and every Ashby board
    # came back empty.
    monkeypatch.setattr(job_searcher, "http_client", _fake_client({"jobs": [
        {"id": "1", "title": "Graduate Software Engineer", "location": "London", "workplaceType": "Hybrid",
         "secondaryLocations": [], "descriptionPlain": "Build things.", "jobUrl": "https://jobs.ashbyhq.com/x/1"},
    ]}))
    jobs = asyncio.run(job_searcher._fetch_ashby("x", "X", ["software"]))
    assert [(j["title"], j["location"]) for j in jobs] == [("Graduate Software Engineer", "London (Hybrid)")]


@pytest.mark.parametrize("fetch, payload, expected", [
    ("_fetch_greenhouse", {"jobs": [{"id": 1, "title": "Software Engineer", "location": {"name": ""}}]}, ""),
    ("_fetch_lever", [{"id": "1", "text": "Software Engineer", "categories": {}}], ""),
    ("_fetch_lever", [{"id": "1", "text": "Software Engineer", "categories": {"location": "London"},
                       "workplaceType": "hybrid"}], "London (Hybrid)"),
    ("_fetch_workable", {"jobs": [{"shortcode": "1", "title": "Software Engineer"}]}, ""),
])
def test_a_job_without_a_location_is_not_called_remote(monkeypatch, fetch, payload, expected):
    monkeypatch.setattr(job_searcher, "http_client", _fake_client(payload))
    jobs = asyncio.run(getattr(job_searcher, fetch)("x", "X", ["software"]))
    assert [j["location"] for j in jobs] == [expected]


@pytest.mark.parametrize("url, expected", [
    ("https://td.wd3.myworkdayjobs.com/en-US/TD_Bank_Careers/job/London-United-Kingdom/Front-Office-Data-Engineer_R1",
     "London United Kingdom"),
    ("https://careers.arm.com/job/lund/graduate-gpu-software-developer/33099/92566862688", "lund"),
    ("https://lseg.wd3.myworkdayjobs.com/en-US/Careers/job/Junior-Data-Scientist_R0102107-1", ""),
    ("https://lseg.wd3.myworkdayjobs.com/en-US/Careers/job/Junior-Data-Scientist_R0102107-1/apply", ""),
    ("https://lseg.wd3.myworkdayjobs.com/en-US/graduate_careers/job/GBR-London-5-Canada-Square/Programme_R1", ""),
    ("https://example.com/job/Software-Engineer/apply", ""),
    ("https://targetjobs.co.uk/jobs/associate-software-engineer-graduate-program-222186", ""),
])
def test_location_from_a_job_url(url, expected):
    assert job_searcher._location_from_url(url) == expected


# ── What a search keeps ───────────────────────────────────────────────────────

def test_every_match_in_the_searched_locations_is_kept(monkeypatch):
    for name in ("_search_level1_playwright", "_search_level3_websearch", "_search_level4_adzuna"):
        monkeypatch.setattr(job_searcher, name, _empty)

    async def fake_ats(queries):
        here = [{"title": f"Software Engineer {i}", "company": f"Co {i}", "location": "London, United Kingdom",
                 "url": f"https://x/{i}"} for i in range(100)]
        elsewhere = [{"title": f"Software Engineer {i}", "company": f"Far {i}", "location": "Austin, TX",
                      "url": f"https://y/{i}"} for i in range(50)]
        return elsewhere + here
    monkeypatch.setattr(job_searcher, "_search_level2_ats_apis", fake_ats)

    jobs = asyncio.run(job_searcher.search_jobs_multi("software engineer", ["London", "United Kingdom"]))
    assert len(jobs) == 100 and {j["location"] for j in jobs} == {"London, United Kingdom"}


def test_a_posting_elsewhere_does_not_stand_in_for_the_one_here(monkeypatch):
    for name in ("_search_level1_playwright", "_search_level3_websearch", "_search_level4_adzuna"):
        monkeypatch.setattr(job_searcher, name, _empty)

    async def fake_ats(queries):
        return [{"title": "Software Engineer", "company": "Cloudflare", "location": "Austin, TX", "url": "https://x/1"},
                {"title": "Software Engineer", "company": "Cloudflare", "location": "London, UK", "url": "https://x/2"}]
    monkeypatch.setattr(job_searcher, "_search_level2_ats_apis", fake_ats)

    jobs = asyncio.run(job_searcher.search_jobs_multi("software engineer", ["London"]))
    assert [j["url"] for j in jobs] == ["https://x/2"]


def test_nothing_in_the_searched_locations_is_not_the_fixture(monkeypatch):
    for name in ("_search_level1_playwright", "_search_level3_websearch", "_search_level4_adzuna"):
        monkeypatch.setattr(job_searcher, name, _empty)

    async def fake_ats(queries):
        return [{"title": "Software Engineer", "company": "Far", "location": "Austin, TX", "url": "https://x/1"}]
    monkeypatch.setattr(job_searcher, "_search_level2_ats_apis", fake_ats)
    assert asyncio.run(job_searcher.search_jobs_multi("software engineer", ["London"])) == []
