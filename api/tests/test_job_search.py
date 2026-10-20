"""Live multi-source search: correct inputs per source, fixture handling, Adzuna routing."""
import asyncio
import re
from unittest.mock import MagicMock

import httpx
import pytest

from app import job_searcher

LIVE_SOURCES = ("_search_level1_playwright", "_search_level2_ats_apis", "_search_level3_websearch",
                "_search_level4_adzuna")


async def _empty(*args, **kwargs):
    return []


@pytest.fixture(autouse=True)
def no_workable_job_board(monkeypatch):
    """Workable's job board is searched with Adzuna; tests that want it set their own."""
    monkeypatch.setattr(job_searcher, "_search_level4_workable", _empty)


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

    async def fake_ats(queries, boards=None, locations=None):
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


def _adzuna_params(monkeypatch, query, location):
    seen = []

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, params=None):
            seen.append(dict(params))
            item = {"id": len(seen), "title": "Graduate Software Engineer", "company": {"display_name": "Acme"},
                    "location": {"display_name": "London"}, "redirect_url": f"https://adzuna/{len(seen)}"}
            return httpx.Response(200, json={"results": [item]}, request=httpx.Request("GET", url))

    monkeypatch.setattr(job_searcher, "ADZUNA_APP_ID", "id")
    monkeypatch.setattr(job_searcher, "ADZUNA_API_KEY", "key")
    monkeypatch.setattr(job_searcher, "http_client", MagicMock(async_client=FakeClient))
    jobs = asyncio.run(job_searcher._search_level4_adzuna(query, location))
    return seen, jobs


def test_adzuna_searches_the_role_uk_wide_and_in_its_graduate_category(monkeypatch):
    seen, jobs = _adzuna_params(monkeypatch, "Graduate Software Engineer", "United Kingdom")
    # Adzuna ANDs every word over the ad, so the seniority word goes; the UK index needs no `where`.
    assert [(p["what"], p.get("where"), p.get("category"), p["results_per_page"]) for p in seen] == [
        ("Software Engineer", None, None, 50), ("Software Engineer", None, "graduate-jobs", 50)]
    assert len(jobs) == 1  # the same ad from both searches is one


def test_adzuna_keeps_a_city_and_has_no_graduate_category_abroad(monkeypatch):
    seen, _ = _adzuna_params(monkeypatch, "ML Engineer", "London")
    assert [(p["what"], p["where"]) for p in seen] == [("ML Engineer", "London"), ("ML Engineer", "London")]
    seen, _ = _adzuna_params(monkeypatch, "ML Engineer", "Toronto")
    assert [p.get("category") for p in seen] == [None]


@pytest.mark.parametrize("locations, areas", [
    (["London", "United Kingdom"], ["United Kingdom"]),     # the UK-wide search covers London
    (["UK", "Manchester", "Berlin"], ["UK", "Berlin"]),
    (["London", "Manchester"], ["London", "Manchester"]),
    (["London", "Toronto"], ["London", "Toronto"]),
])
def test_aggregator_areas(locations, areas):
    assert job_searcher._aggregator_areas(locations) == areas


def test_the_workable_job_board_is_searched_per_area(monkeypatch):
    for name in ("_search_level1_playwright", "_search_level2_ats_apis", "_search_level3_websearch",
                 "_search_level4_adzuna"):
        monkeypatch.setattr(job_searcher, name, _empty)
    calls = []

    async def workable(query, location):
        calls.append((query, location))
        return [{"title": "Graduate Software Engineer", "company": "Wk", "location": "London, United Kingdom",
                 "url": "https://w/1"}]
    monkeypatch.setattr(job_searcher, "_search_level4_workable", workable)
    jobs = asyncio.run(job_searcher.collect_jobs(["software engineer"], ["London", "United Kingdom"]))
    assert calls == [("software engineer", "United Kingdom")] and [j["url"] for j in jobs] == ["https://w/1"]


# ── Job boards ────────────────────────────────────────────────────────────────

def test_found_boards_are_fetched_with_the_listed_ones_and_gone_ones_are_not():
    listed = job_searcher.listed_boards()
    gone_ats, gone_slug, _ = listed[0]
    boards = job_searcher._all_boards(found=[("ashby", "newco", "NewCo"), (gone_ats, gone_slug.upper(), "Dup")],
                                      gone={(gone_ats, gone_slug)})
    flat = [(ats, slug) for ats, items in boards.items() for slug, _ in items]
    assert ("ashby", "newco") in flat and (gone_ats, gone_slug) not in flat
    assert len(flat) == len(listed)  # one gone (however its slug is cased) and one found


@pytest.mark.parametrize("company, slugs", [
    ("Squarepoint Capital LLP", ["squarepointcapital", "squarepoint-capital"]),
    ("OpenAI", ["openai"]),
    ("The Trade Desk (UK) Ltd", ["tradedesk", "trade-desk"]),
    ("BP", []),                     # too short to be anyone's alone
])
def test_board_slugs(company, slugs):
    assert job_searcher._board_slugs(company) == slugs


class _Web:
    """A fake httpx client: URL -> (status, json)."""
    def __init__(self, pages):
        self.pages, self.asked = pages, []

    async def get(self, url, params=None):
        self.asked.append(url)
        status, body = self.pages.get(url, (404, {}))
        return httpx.Response(status, json=body, request=httpx.Request("GET", url))


GH = "https://boards-api.greenhouse.io/v1/boards/{}"
ASHBY = "https://api.ashbyhq.com/posting-api/job-board/{}"


def test_a_greenhouse_board_is_the_employers_only_if_it_has_their_name():
    web = _Web({GH.format("squarepointcapital") + "/jobs": (200, {"jobs": [{"id": 1}, {"id": 2}]}),
                GH.format("squarepointcapital"): (200, {"name": "Squarepoint Capital"})})
    assert asyncio.run(job_searcher.find_board(web, "Squarepoint Capital LLP")) == ("greenhouse", "squarepointcapital", 2)
    web = _Web({GH.format("london") + "/jobs": (200, {"jobs": [{"id": 1}]}),
                GH.format("london"): (200, {"name": "London Stock Exchange Group"})})
    assert asyncio.run(job_searcher.find_board(web, "London")) is None


def test_an_ashby_board_is_the_employers_only_if_an_ad_names_them():
    ads = [{"descriptionPlain": "At OpenAI we build safe AGI."}]
    web = _Web({ASHBY.format("openai"): (200, {"jobs": ads})})
    assert asyncio.run(job_searcher.find_board(web, "OpenAI")) == ("ashby", "openai", 1)
    web = _Web({ASHBY.format("openai"): (200, {"jobs": [{"descriptionPlain": "Join our sales team."}]})})
    assert asyncio.run(job_searcher.find_board(web, "OpenAI")) is None


def test_names_that_are_not_employers_are_not_looked_up():
    web = _Web({})
    assert asyncio.run(job_searcher.find_board(web, "Unknown")) is None
    assert asyncio.run(job_searcher.find_board(web, "Myworkdayjobs.com")) is None
    assert web.asked == []


def test_a_board_is_gone_only_on_a_404():
    web = _Web({ASHBY.format("alive"): (200, {"jobs": [{}, {}]}), ASHBY.format("busy"): (503, {})})
    assert asyncio.run(job_searcher.check_board(web, "ashby", "alive")) == 2
    assert asyncio.run(job_searcher.check_board(web, "ashby", "gone")) is None
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(job_searcher.check_board(web, "ashby", "busy"))


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


def test_a_board_on_levers_eu_instance_is_fetched_from_its_own_api(monkeypatch):
    # CoreTech Security's board is on jobs.eu.lever.co; api.lever.co doesn't have its postings.
    asked: list[str] = []

    class Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, params=None):
            asked.append(url)
            return httpx.Response(200, json=[{"id": "1", "text": "Graduate Software Engineer",
                                              "categories": {"location": "London"},
                                              "hostedUrl": "https://jobs.eu.lever.co/x/1"}],
                                  request=httpx.Request("GET", url))
    monkeypatch.setattr(job_searcher, "http_client", MagicMock(async_client=Client))
    jobs = asyncio.run(job_searcher._search_level2_ats_apis(["software"], boards={"lever_eu": [("x", "X")]}))
    assert asked == ["https://api.eu.lever.co/v0/postings/x?mode=json"]
    assert [(j["company"], j["url"]) for j in jobs] == [("X", "https://jobs.eu.lever.co/x/1")]
    web = _Web({"https://api.eu.lever.co/v0/postings/x?mode=json": (200, [{}, {}, {}])})
    assert asyncio.run(job_searcher.check_board(web, "lever_eu", "x")) == 3


class _Workday:
    """A fake Workday site (tenant t, site Site): a search answers from `postings` by its text, a posting read
    from `details` by its path; `status` other than 200 answers every call with it."""
    BASE = "https://t.wd3.myworkdayjobs.com/wday/cxs/t/Site"

    def __init__(self, postings=None, details=None, status=200):
        self.postings, self.details, self.status, self.calls = postings or {}, details or {}, status, []

    def __call__(self, *a, **k):   # as http_client.async_client
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    async def request(self, method, url, json=None, **kwargs):
        self.calls.append((method, url[len(self.BASE):], (json or {}).get("searchText")))
        req = httpx.Request(method, url)
        if self.status != 200:
            return httpx.Response(self.status, json={}, request=req)
        if method == "POST":
            found = self.postings.get(json["searchText"], [])
            page = found[json["offset"]:json["offset"] + json["limit"]]
            return httpx.Response(200, json={"total": len(found), "jobPostings": page}, request=req)
        return httpx.Response(200, json={"jobPostingInfo": self.details[url[len(self.BASE):]]}, request=req)

    async def post(self, url, json=None):
        return await self.request("POST", url, json=json)

    async def get(self, url, **kwargs):
        return await self.request("GET", url, **kwargs)


def _posting(path, title, place):
    return {"externalPath": f"/job/{path}", "title": title, "locationsText": place}


def test_a_workday_board_is_searched_and_only_postings_that_may_be_here_are_read(monkeypatch):
    site = _Workday(
        postings={"Graduate Software Engineer": [
            _posting("London/Grad-SE_1", "Software Engineer Graduate Scheme", "London"),
            _posting("Pune/Grad-SE_2", "Graduate Software Engineer", "Pune, India"),    # elsewhere: not read
            _posting("London/AE_3", "Account Executive", "London"),                      # not the search
            _posting("Many/SE_4", "Software Engineer", "2 Locations"),                   # the posting says where
        ], "Quant Developer": [_posting("London/Grad-SE_1", "Software Engineer Graduate Scheme", "London")]},
        details={
            "/job/London/Grad-SE_1": {"title": "Software Engineer Graduate Scheme", "location": "London",
                                      "jobReqId": "R1", "jobDescription": "<p>Build things.</p>",
                                      "externalUrl": "https://t.wd3.myworkdayjobs.com/Site/job/London/Grad-SE_1"},
            "/job/Many/SE_4": {"title": "Software Engineer", "location": "Leeds", "additionalLocations": ["Austin, TX"],
                               "remoteType": "Hybrid", "jobReqId": "R4", "jobDescription": "Code."}})
    monkeypatch.setattr(job_searcher, "http_client", MagicMock(async_client=site))
    jobs = asyncio.run(job_searcher._fetch_workday(
        "t/wd3/Site", "T", ["graduate", "software", "engineer", "quant", "developer"],
        ["Graduate Software Engineer", "Quant Developer"], ["London", "United Kingdom"]))
    assert [c for c in site.calls if c[0] == "POST"] == [("POST", "/jobs", "Graduate Software Engineer"),
                                                        ("POST", "/jobs", "Quant Developer")]
    assert [c[1] for c in site.calls if c[0] == "GET"] == ["/job/London/Grad-SE_1", "/job/Many/SE_4"]   # once each
    assert [(j["job_id"], j["title"], j["location"], j["description"], j["url"]) for j in jobs] == [
        ("workday-t-R1", "Software Engineer Graduate Scheme", "London", "Build things.",
         "https://t.wd3.myworkdayjobs.com/Site/job/London/Grad-SE_1"),
        ("workday-t-R4", "Software Engineer", "Leeds; Austin, TX (Hybrid)", "Code.",
         "https://t.wd3.myworkdayjobs.com/Site/job/Many/SE_4"),
    ]


def test_a_workday_site_refusing_calls_is_waited_out_once_then_left(monkeypatch):
    site = _Workday(status=429)
    monkeypatch.setattr(job_searcher, "http_client", MagicMock(async_client=site))
    monkeypatch.setattr(job_searcher, "_BACKOFF_S", 0)
    assert asyncio.run(job_searcher._fetch_workday("t/wd3/Site", "T", ["software"], ["Software"], ["London"])) == []
    assert len(site.calls) == 2                     # the call and its one retry; nothing more this collection


def test_a_workday_board_is_checked_by_its_total_and_its_postings_read_whole():
    site = _Workday(postings={"": [_posting("a", "A", "London")] * 7},
                    details={"/job/London/Grad-SE_1": {"jobDescription": "<p>" + "Build things. " * 30 + "</p>"}})
    assert asyncio.run(job_searcher.check_board(site, "workday", "t/wd3/Site")) == 7
    assert asyncio.run(job_searcher.check_board(_Workday(status=404), "workday", "t/wd3/Site")) is None


def test_full_descriptions_come_from_workday_and_levers_eu_instance(monkeypatch):
    asked: list[str] = []

    class Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, **kwargs):
            asked.append(url)
            body = ({"jobPostingInfo": {"jobDescription": "<p>Workday ad.</p>"}} if "myworkdayjobs" in url
                    else {"descriptionPlain": "Lever EU ad."})
            return httpx.Response(200, json=body, request=httpx.Request("GET", url))
    monkeypatch.setattr(job_searcher, "http_client", MagicMock(async_client=Client))
    workday = asyncio.run(job_searcher._ats_full_description(
        "https://lbg.wd3.myworkdayjobs.com/en-GB/Graduate_careers/job/London/Software-Engineer_163384-2"))
    lever = asyncio.run(job_searcher._ats_full_description(
        "https://jobs.eu.lever.co/coretechsecurity/0a1b2c3d-1111-2222-3333-444455556666"))
    assert (workday, lever) == ("Workday ad.", "Lever EU ad.")
    assert asked == ["https://lbg.wd3.myworkdayjobs.com/wday/cxs/lbg/Graduate_careers/job/London/Software-Engineer_163384-2",
                     "https://api.eu.lever.co/v0/postings/coretechsecurity/0a1b2c3d-1111-2222-3333-444455556666"]


class _Site:
    """A fake careers site: `answer(method, url, params)` gives (status, json body or text). Calls are kept."""

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def __call__(self, *a, **k):   # as http_client.async_client
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    async def request(self, method, url, params=None, **kwargs):
        self.calls.append((method, url, dict(params or {})))
        status, body = self.answer(method, url, params or {})
        req = httpx.Request(method, url)
        if isinstance(body, str):
            return httpx.Response(status, text=body, request=req)
        return httpx.Response(status, json=body, request=req)

    async def get(self, url, params=None, **kwargs):
        return await self.request("GET", url, params=params)


def _oracle_posting(pid, title, place, *elsewhere):
    return {"Id": pid, "Title": title, "PrimaryLocation": place, "WorkplaceType": "",
            "secondaryLocations": [{"Name": p} for p in elsewhere]}


def test_an_oracle_board_is_searched_and_only_postings_that_may_be_here_are_read(monkeypatch):
    listed = [_oracle_posting("1", "Graduate Software Engineer", "London, England, United Kingdom"),
              _oracle_posting("2", "Graduate Software Engineer", "Dallas, TX, United States"),
              _oracle_posting("3", "Software Engineer", "Pittsburgh, PA, United States", "London, United Kingdom"),
              _oracle_posting("4", "Account Manager", "London, United Kingdom")]

    def answer(method, url, params):
        if "recruitingCEJobRequisitions?" in url:
            return 200, {"items": [{"TotalJobsCount": 4, "requisitionList": listed}]}
        pid = re.search(r"Id%3D%22(\d+)%22|Id=\"(\d+)\"", url)
        return 200, {"items": [{"ExternalDescriptionStr": f"<p>About {pid.group(1) or pid.group(2)}.</p>",
                                "ExternalQualificationsStr": "<p>Python.</p>"}]}
    site = _Site(answer)
    monkeypatch.setattr(job_searcher, "http_client", MagicMock(async_client=site))
    jobs = asyncio.run(job_searcher._fetch_oracle("h.fa.em3.oraclecloud.com/CX_1", "Co", ["graduate", "software", "engineer"],
                                                  ["Graduate Software Engineer"], ["London", "United Kingdom"]))
    searches = [url for _, url, _ in site.calls if "recruitingCEJobRequisitions?" in url]
    assert len(searches) == 1 and "keyword=Graduate%20Software%20Engineer,sortBy=RELEVANCY" in searches[0]
    assert [(j["job_id"], j["location"], " ".join(j["description"].split()), j["url"]) for j in jobs] == [
        ("oracle-h-1", "London, England, United Kingdom", "About 1. Python.",
         "https://h.fa.em3.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/1"),
        ("oracle-h-3", "Pittsburgh, PA, United States; London, United Kingdom", "About 3. Python.",
         "https://h.fa.em3.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/3"),
    ]


def test_an_oracle_search_drops_the_finders_own_separators():
    url = job_searcher._oracle_search_url("h", "CX_1", "C++, Java; dev=ops")
    assert "keyword=C%2B%2B%20Java%20dev%20ops" in url and "siteNumber=CX_1,limit=25,offset=0" in url


def test_an_eightfold_board_is_searched_in_each_location_and_read_once(monkeypatch):
    def answer(method, url, params):
        if url.endswith("/search"):
            here = params.get("location")
            return 200, {"data": {"count": 2, "positions": [
                {"id": 11, "displayJobId": "R11", "name": "Graduate Software Engineer",
                 "standardizedLocations": ["London, England, GB"], "workLocationOption": "hybrid"},
                {"id": 12, "displayJobId": "R12", "name": "Software Engineer",
                 "standardizedLocations": ["Roy, UT, US"] if here == "London" else ["Roy, UT, US"]},
            ]}}
        return 200, {"data": {"jobDescription": f"<p>Job {params['position_id']}.</p>",
                              "publicUrl": f"https://jobs.example.com/careers/job/{params['position_id']}"}}
    site = _Site(answer)
    monkeypatch.setattr(job_searcher, "http_client", MagicMock(async_client=site))
    jobs = asyncio.run(job_searcher._fetch_eightfold("ngc/ngc.com", "NG", ["software", "engineer"],
                                                     ["Software Engineer"], ["London", "United Kingdom"]))
    searched = [(p["query"], p.get("location"), p["domain"]) for _, url, p in site.calls if url.endswith("/search")]
    assert searched == [("Software Engineer", "London", "ngc.com"), ("Software Engineer", "United Kingdom", "ngc.com")]
    assert [p["position_id"] for _, url, p in site.calls if url.endswith("/position_details")] == [11]
    assert [(j["job_id"], j["location"], j["description"], j["url"]) for j in jobs] == [
        ("eightfold-ngc-R11", "London, England, GB (Hybrid)", "Job 11.", "https://jobs.example.com/careers/job/11")]


TEAMTAILOR_RSS = """<?xml version="1.0"?><rss xmlns:tt="https://teamtailor.com/locations"><channel>
<item><title>Graduate Software Engineer</title>
<description>&lt;p&gt;Build &amp;amp; ship.&lt;/p&gt;</description>
<link>https://careers.example.com/jobs/1-graduate-software-engineer</link><guid>tt-1</guid>
<remoteStatus>hybrid</remoteStatus>
<tt:locations><tt:location><tt:name>HQ</tt:name><tt:city>London</tt:city><tt:country>United Kingdom</tt:country></tt:location>
<tt:location><tt:city>Lisbon</tt:city><tt:country>Portugal</tt:country></tt:location></tt:locations></item>
<item><title><![CDATA[Account Executive]]></title><description>Sell.</description><link>https://careers.example.com/jobs/2</link></item>
</channel></rss>"""


def test_a_teamtailor_board_is_read_from_its_feed():
    jobs = job_searcher._teamtailor_jobs(TEAMTAILOR_RSS, "Co", ["software", "engineer"])
    assert [(j["job_id"], j["title"], j["location"], j["description"], j["url"]) for j in jobs] == [
        ("teamtailor-tt-1", "Graduate Software Engineer", "London, United Kingdom; Lisbon, Portugal (Hybrid)",
         "Build & ship.", "https://careers.example.com/jobs/1-graduate-software-engineer")]


@pytest.mark.parametrize("ats, slug, body, expected", [
    ("oracle", "h.fa.em3.oraclecloud.com/CX_1", {"items": [{"TotalJobsCount": 132}]}, 132),
    ("eightfold", "ngc/ngc.com", {"data": {"count": 26, "positions": []}}, 26),
    ("teamtailor", "careers.example.com", TEAMTAILOR_RSS, 2),
])
def test_searched_and_feed_boards_are_checked(ats, slug, body, expected):
    assert asyncio.run(job_searcher.check_board(_Site(lambda m, u, p: (200, body)), ats, slug)) == expected
    assert asyncio.run(job_searcher.check_board(_Site(lambda m, u, p: (404, {})), ats, slug)) is None


def test_pinpoint_recruitee_and_bamboohr_boards_are_read(monkeypatch):
    def answer(method, url, params):
        if url == "https://co.pinpointhq.com/postings.json":
            return 200, {"data": [
                {"id": 1, "title": "Graduate Software Engineer", "location": {"city": "London", "name": "London HQ"},
                 "workplace_type": "hybrid", "description": "<p>Pinpoint ad.</p>",
                 "url": "https://careers.co.uk/en/postings/1"},
                {"id": 2, "title": "Office Manager", "location": {"city": "London"}, "description": "", "url": "x"}]}
        if url == "https://co.recruitee.com/api/offers/":
            return 200, {"offers": [
                {"id": 7, "title": "Junior Software Engineer", "location": "London, England, United Kingdom",
                 "remote": False, "hybrid": True, "description": "<p>Recruitee ad.</p>",
                 "requirements": "<p>Python.</p>", "careers_url": "https://co.recruitee.com/o/junior-se"}]}
        if url == "https://co.bamboohr.com/careers/list":
            return 200, {"result": [
                {"id": "42", "jobOpeningName": "Software Engineer", "location": {"city": "London", "state": "Greater London"},
                 "isRemote": None},
                {"id": "43", "jobOpeningName": "Sales Lead", "location": {"city": "London"}}]}
        if url == "https://co.bamboohr.com/careers/42/detail":
            return 200, {"result": {"jobOpening": {"description": "<p>BambooHR ad.</p>"}}}
        return 404, {}
    site = _Site(answer)
    monkeypatch.setattr(job_searcher, "http_client", MagicMock(async_client=site))
    boards = {"pinpoint": [("co", "Pin")], "recruitee": [("co", "Rec")], "bamboohr": [("co", "Bam")]}
    jobs = asyncio.run(job_searcher._search_level2_ats_apis(["Software Engineer"], boards=boards))
    got = {j["company"]: (j["job_id"], j["location"], " ".join(j["description"].split()), j["url"]) for j in jobs}
    assert got == {
        "Pin": ("pinpoint-co-1", "London (Hybrid)", "Pinpoint ad.", "https://careers.co.uk/en/postings/1"),
        "Rec": ("recruitee-7", "London, England, United Kingdom (Hybrid)", "Recruitee ad. Python.",
                "https://co.recruitee.com/o/junior-se"),
        "Bam": ("bamboohr-co-42", "London, Greater London", "BambooHR ad.", "https://co.bamboohr.com/careers/42"),
    }
    assert "https://co.bamboohr.com/careers/43/detail" not in [u for _, u, _ in site.calls]   # not the search


@pytest.mark.parametrize("ats, url, body", [
    ("pinpoint", "https://co.pinpointhq.com/postings.json", {"data": [{}, {}]}),
    ("recruitee", "https://co.recruitee.com/api/offers/", {"offers": [{}, {}]}),
    ("bamboohr", "https://co.bamboohr.com/careers/list", {"result": [{}, {}]}),
])
def test_feed_boards_on_json_are_checked(ats, url, body):
    web = _Web({url: (200, body)})
    assert asyncio.run(job_searcher.check_board(web, ats, "co")) == 2
    assert asyncio.run(job_searcher.check_board(_Web({}), ats, "co")) is None


def test_no_board_is_listed_twice():
    listed = [(ats, slug.lower()) for ats, slug, _ in job_searcher.listed_boards()]
    assert len(listed) == len(set(listed))


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


# ── Web search results ────────────────────────────────────────────────────────

@pytest.mark.parametrize("url, expected", [
    ("https://www.gradcracker.com/hub/275/lloyds-banking-group/graduate-job/82966/data-science-and-ai", True),
    ("https://www.gradcracker.com/search/computing-technology/ai-machine-learning-graduate-jobs", False),
    ("https://targetjobs.co.uk/jobs/graduate-software-engineer-2026-232060", True),
    ("https://targetjobs.co.uk/careers-advice/information-technology/how-get-it-graduate", False),
    ("https://targetjobs.co.uk/graduate-jobs/it/data", False),
    ("https://www.totaljobs.com/job/graduate-software-engineer/acme-ltd-job105230817", True),
    ("https://www.totaljobs.com/jobs/graduate-software-engineer/in-london", False),
    ("https://www.reed.co.uk/jobs/software-engineer-ai/56239586", True),
    ("https://www.reed.co.uk/jobs/graduate-information-technology-jobs-in-london", False),
    ("https://wellfound.com/jobs/2871376-machine-learning-ml-engineer-ii", True),
    ("https://wellfound.com/role/l/ai-engineer/india", False),
    ("https://lseg.wd3.myworkdayjobs.com/en-US/Careers/job/Junior-Data-Scientist_R0102107-1", True),
    ("https://lbg.wd3.myworkdayjobs.com/Graduate_careers", False),
    ("https://careers.arm.com/graduates", False),
    ("https://jobs.example.com/anything", True),
])
def test_only_one_posting_pages_of_known_sites_are_jobs(url, expected):
    assert job_searcher._is_a_posting(url) is expected


@pytest.mark.parametrize("tail, url, expected", [
    ("Careers - Myworkdayjobs.com", "https://lseg.wd3.myworkdayjobs.com/en-US/Careers/job/X_R1", ("LSEG", "")),
    ("China", "https://nvidia.wd5.myworkdayjobs.com/en-US/External/job/X_R1", ("NVIDIA", "")),
    ("Engineering Pathways in Austin at Arm", "https://careers.arm.com/job/austin/graduate/1/2", ("Arm", "")),
    ("2027 | Graduate Jobs | Accenture Hub | Gradcracker", "https://www.gradcracker.com/hub/269/accenture/graduate-job/75245/x",
     ("Accenture", "")),
    ("Updated Daily", "https://www.totaljobs.com/job/graduate-developer/bright-network-job105230817", ("Bright Network", "")),
    ("Edinburgh", "https://targetjobs.co.uk/jobs/data-science-ai-graduate-scheme-edinburgh-239709", ("Unknown", "Edinburgh")),
    ("August 2026 - London", "https://targetjobs.co.uk/jobs/software-development-engineering-graduate-210738", ("Unknown", "August 2026 - London")),
    ("Full-Time – London (February Start)", "https://targetjobs.co.uk/jobs/2026-software-engineer-program-184526",
     ("Unknown", "Full-Time – London (February Start)")),
    ("2027 | Wellfound", "https://wellfound.com/jobs/3208571-ml-engineer", ("Unknown", "")),
    ("The Mobilise Academy", "https://targetjobs.co.uk/jobs/graduate-cloud-engineer-mobilise-academy-228516",
     ("The Mobilise Academy", "")),
])
def test_a_search_results_employer_comes_from_its_address_not_the_sites_name(tail, url, expected):
    assert job_searcher._employer_and_place(tail, url) == expected


@pytest.mark.parametrize("title", [
    "Data Scientist Jobs in London", "Backend Engineer Jobs", "IT graduate jobs & schemes 2027",
    "Graduate Software Engineer Job Vacancies", "25 Startups Hiring For Junior Software Engineers",
    "Machine Learning Engineer Salary and Equity",
])
def test_a_job_boards_page_of_jobs_is_not_a_job(title):
    assert not job_searcher._passes_title_filter(title, "software engineer")


def test_an_aggregators_copy_of_a_board_job_is_dropped():
    board = {"title": "Quant Researcher", "company": "Squarepoint Capital", "url": "https://boards.greenhouse.io/x/1"}
    adzuna = {"title": "Quant Researcher", "company": "Squarepoint Capital LLP", "url": "https://www.adzuna.co.uk/jobs/land/ad/9"}
    assert job_searcher._deduplicate([board, adzuna]) == [board]


# ── What a search keeps ───────────────────────────────────────────────────────

def test_every_match_in_the_searched_locations_is_kept(monkeypatch):
    for name in ("_search_level1_playwright", "_search_level3_websearch", "_search_level4_adzuna"):
        monkeypatch.setattr(job_searcher, name, _empty)

    async def fake_ats(queries, boards=None, locations=None):
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

    async def fake_ats(queries, boards=None, locations=None):
        return [{"title": "Software Engineer", "company": "Cloudflare", "location": "Austin, TX", "url": "https://x/1"},
                {"title": "Software Engineer", "company": "Cloudflare", "location": "London, UK", "url": "https://x/2"}]
    monkeypatch.setattr(job_searcher, "_search_level2_ats_apis", fake_ats)

    jobs = asyncio.run(job_searcher.search_jobs_multi("software engineer", ["London"]))
    assert [j["url"] for j in jobs] == ["https://x/2"]


def test_nothing_in_the_searched_locations_is_not_the_fixture(monkeypatch):
    for name in ("_search_level1_playwright", "_search_level3_websearch", "_search_level4_adzuna"):
        monkeypatch.setattr(job_searcher, name, _empty)

    async def fake_ats(queries, boards=None, locations=None):
        return [{"title": "Software Engineer", "company": "Far", "location": "Austin, TX", "url": "https://x/1"}]
    monkeypatch.setattr(job_searcher, "_search_level2_ats_apis", fake_ats)
    assert asyncio.run(job_searcher.search_jobs_multi("software engineer", ["London"])) == []
