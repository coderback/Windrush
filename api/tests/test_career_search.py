"""Live search for a career plan: a resource is linked only to a result whose title carries its name; a venue is
only ever one of the search results, with that result's link and a date only if the result states it; the searches
carry the role, a skill and a place, nothing that identifies the user; and a failed search leaves the plan as it was."""
import asyncio
import json
from datetime import datetime, timezone

import pytest

from app import career_plan, career_search, main, tracker

TODAY = datetime(2026, 11, 23, tzinfo=timezone.utc)
PERSONA = {"core_info": {"first_name": "Sam", "last_name": "Okafor", "email": "sam@example.com"},
           "preferences": {"target_titles": ["Graduate ML Engineer"], "preferred_locations": ["United Kingdom", "London"]},
           "projects": [{"name": "Cambium", "technologies": ["PyTorch"]}]}
DEMAND = {"roles": ["ML Engineer"], "ads": 0, "skills": []}


def _plan():
    return career_plan.validate({"tracks": [{"skill": "Kubernetes", "resources": ["Kubernetes Up & Running", "The Missing Book"]}]},
                                PERSONA, DEMAND)


RESULTS = {
    "Kubernetes Up & Running": [{"title": "Kubernetes: Up and Running, 3rd Edition [Book] - O'Reilly",
                                 "url": "https://www.oreilly.com/library/view/kubernetes-up-and/9781098110192/", "snippet": ""}],
    "The Missing Book": [{"title": "Missing persons", "url": "https://example.com/missing", "snippet": ""}],
}
VENUES = [
    {"title": "AI & Machine Learning Hackathons in London 2026", "url": "https://www.hackathonradar.com/discover/london/ai/2026",
     "snippet": "Find 196 AI & machine learning hackathons in London in 2026."},
    {"title": "PyData London meetup", "url": "https://www.meetup.com/pydata-london-meetup/",
     "snippet": "Monthly talks. Next: 9 December 2026."},
    {"title": "javascript:alert(1)", "url": "javascript:alert(1)", "snippet": ""},
]


def _search(asked):
    async def search(query, max_results=15):
        asked.append(query)
        return RESULTS.get(query, VENUES)
    return search


@pytest.mark.parametrize("name, title, ok", [
    ("Kubernetes Up & Running", "Kubernetes: Up and Running, 3rd Edition [Book] - O'Reilly", True),
    ("Designing Data-Intensive Applications", "Designing Data-Intensive Applications - Martin Kleppmann", True),
    ("The Missing Book", "Missing persons", False),
    ("Kubernetes Up & Running", "Kubernetes documentation", False),
    ("fast.ai", "Practical Deep Learning for Coders - fast.ai", True),
    ("Python documentation: The Python Profilers", "profiling — Python profilers — Python 3.15.2 documentation", True),
    ("Python documentation: The Python Profilers", "Profiling in Python: How to Find Performance Bottlenecks", False),
    ("Go documentation: Diagnostics", "Diagnostics - The Go Programming Language", True),
    ("Go documentation: Diagnostics", "Diagnostics - Rust compiler development guide", False),
])
def test_a_resource_matches_only_a_title_carrying_its_name(name, title, ok):
    assert career_search.matches_resource(name, title) is ok


def test_the_source_can_be_in_the_results_link():
    assert career_search.matches_resource("GitHub Docs: About pull requests", "About pull requests",
                                          "https://docs.github.com/en/pull-requests/about-pull-requests")
    assert not career_search.matches_resource("GitHub Docs: About pull requests", "About pull requests",
                                              "https://example.com/about-pull-requests")


def test_the_first_two_roles_get_their_own_searches():
    queries = career_search.venue_queries(PERSONA, _plan(), {"roles": ["Software Engineer", "ML Engineer", "AI Engineer"]}, TODAY)
    assert queries == ["Software Engineer hackathon London 2026 2027", "Software Engineer meetup London",
                       "ML Engineer hackathon London 2026 2027", "ML Engineer meetup London",
                       "Software Engineer conference London 2026 2027", "ML Engineer competition 2026 2027",
                       "Kubernetes community London"]


def test_an_empty_page_is_asked_for_again_once():
    calls = []

    async def flaky(query, max_results=8):
        calls.append(query)
        return [] if len(calls) == 1 else [{"title": "x", "url": "https://x.example"}]
    assert asyncio.run(career_search._gentle(flaky, pause_s=0)("q")) == [{"title": "x", "url": "https://x.example"}]
    assert calls == ["q", "q"]


def test_resources_are_checked_and_venues_kept_only_as_the_results_they_point_at():
    asked = []

    async def pick(system, user):
        assert "Search results:\n1. AI & Machine Learning Hackathons in London 2026 |" in user
        assert "today is 2026-11-23" in system
        return {"picks": [
            {"n": 2, "kind": "meetup", "name": "PyData London", "when": "9 December 2026", "why": "ML talks monthly."},
            {"n": 1, "kind": "listing", "when": "March 2027", "why": "Hackathons to enter."},     # date not in result
            {"n": 2, "kind": "meetup"},                                                            # same page again
            {"n": 9, "kind": "event"}, {"n": True}, {"n": "1"},                                    # not a result
        ]}
    plan = asyncio.run(career_search.enrich(_plan(), PERSONA, DEMAND, search=_search(asked), pick=pick, today=TODAY))
    book, missing = plan["tracks"][0]["resources"]
    assert book["checked"] and book["url"].startswith("https://www.oreilly.com/") and not missing["checked"]
    assert plan["venues_searched"] is True
    assert plan["venues"] == [
        {"id": "v1", "name": "PyData London", "url": "https://www.meetup.com/pydata-london-meetup/", "kind": "meetup",
         "when": "9 December 2026", "why": "ML talks monthly."},
        {"id": "v2", "name": "AI & Machine Learning Hackathons in London 2026",
         "url": "https://www.hackathonradar.com/discover/london/ai/2026", "kind": "listing", "when": "", "why": "Hackathons to enter."},
    ]
    assert "v1" in career_plan.item_ids(plan)
    venue_queries = [q for q in asked if q not in RESULTS]
    assert venue_queries == ["ML Engineer hackathon London 2026 2027", "ML Engineer meetup London",
                             "ML Engineer conference London 2026 2027", "ML Engineer competition 2026 2027",
                             "Kubernetes community London"]
    assert not any(x in " ".join(asked) for x in ("Sam", "Okafor", "sam@example.com"))


def test_a_failed_search_leaves_the_plan_unchecked_with_no_venues():
    async def down(query, max_results=15):
        raise OSError("no network")

    async def never(system, user):
        raise AssertionError("no results, so no pick")
    plan = asyncio.run(career_search.enrich(_plan(), PERSONA, DEMAND, search=down, pick=never, today=TODAY))
    assert plan["venues"] == [] and plan["venues_searched"] is False
    assert not any(r["checked"] for r in plan["tracks"][0]["resources"])


def test_no_target_role_means_no_venue_search():
    assert career_search.venue_queries({"preferences": {}}, _plan(), {"roles": []}, TODAY) == []


def test_the_place_is_a_city_before_a_country():
    assert career_search._place(PERSONA) == "London"
    assert career_search._place({"preferences": {"preferred_locations": ["United Kingdom", "Remote"]}}) == "UK"
    assert career_search._place({"preferences": {}}) == ""


class _Brave:
    """Stands in for http_client.async_client: answers the Brave API with `body` and records what was asked."""
    asked: list = []

    def __init__(self, body=None, status=200):
        self.body, self.status = body, status

    def __call__(self, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def get(self, url, params=None, headers=None):
        import httpx
        _Brave.asked.append((url, params, headers))
        return httpx.Response(self.status, json=self.body, request=httpx.Request("GET", url))


def test_brave_results_are_read_and_ddg_is_the_fallback(monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-brave-key")
    monkeypatch.setattr(career_search, "_BRAVE_GAP_S", 0)
    monkeypatch.setattr(career_search.http_client, "async_client", _Brave({"web": {"results": [
        {"title": "<strong>PyData</strong> London", "url": "https://pydata.org/london", "description": "Talks <b>monthly</b>."},
        {"title": "no link"}]}}))
    assert asyncio.run(career_search.web_search("pydata london")) == [
        {"title": "PyData London", "url": "https://pydata.org/london", "snippet": "Talks monthly."}]
    assert _Brave.asked[-1][1]["q"] == "pydata london" and _Brave.asked[-1][2]["X-Subscription-Token"] == "test-brave-key"

    from app import agent
    ddg = []

    async def fake_ddg(query, max_results=15):
        ddg.append(query)
        return [{"title": "x", "url": "https://x.example", "snippet": ""}]
    monkeypatch.setattr(agent, "_ddg_search", fake_ddg)
    monkeypatch.setattr(career_search.http_client, "async_client", _Brave(status=429))
    assert asyncio.run(career_search.web_search("q"))[0]["url"] == "https://x.example" and ddg == ["q"]
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY")
    asyncio.run(career_search.web_search("q2"))
    assert ddg == ["q", "q2"]


def test_the_plan_endpoint_saves_the_looked_up_plan(client, user, monkeypatch):
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    tracker.update_user_persona(user, PERSONA)

    async def tool(name, tool_input):
        return {"plan": _plan()}

    async def search(query, max_results=15):
        return RESULTS.get(query, VENUES)

    async def pick(system, user, max_tokens=1500, label=""):
        return {"picks": [{"n": 2, "kind": "meetup", "name": "PyData London", "why": "Talks."}]}
    monkeypatch.setattr(main, "execute_tool", tool)
    from app import agent
    monkeypatch.setattr(agent, "_ddg_search", search)
    monkeypatch.setattr(agent, "_llm_json", pick)
    events = [json.loads(line[6:]) for line in client.post("/careers/plan").text.splitlines() if line.startswith("data: ")]
    assert "Looking up events and resources…" in [e.get("message") for e in events]
    saved = client.get("/careers/plan").json()["plan"]
    assert [v["name"] for v in saved["venues"]] == ["PyData London"] and saved["tracks"][0]["resources"][0]["checked"]
