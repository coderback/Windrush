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
])
def test_a_resource_matches_only_a_title_carrying_its_name(name, title, ok):
    assert career_search.matches_resource(name, title) is ok


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


def test_the_plan_endpoint_saves_the_looked_up_plan(client, user, monkeypatch):
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
