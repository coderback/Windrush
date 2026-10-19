"""/jobs: never waits on live discovery or a slow embedder, and never stalls the event loop."""
import asyncio
import time

import httpx
import pytest
from conftest import make_job

from app import auth, discovery, job_searcher, jobs_db, main, tracker

# How long the event loop may be blocked at once while /jobs + discovery run. The old code
# blocked for the whole live search plus one synchronous embedding call per job.
MAX_LOOP_STALL_S = 0.3


@pytest.fixture
def feed_user(db):
    uid = tracker.create_user("feed@x.com", "h")
    tracker.update_user_persona(uid, {"preferences": {"target_titles": ["Quantum Engineer"]}})
    main.app.dependency_overrides[auth.get_current_user] = lambda: auth.User(id=uid, email="feed@x.com")
    yield uid
    main.app.dependency_overrides.clear()


@pytest.fixture
def slow_live_search(monkeypatch):
    calls = []

    async def fake_search(query, locations, web_search=True):
        calls.append((query, locations))
        await asyncio.sleep(1.5)
        return [make_job(f"Q{i}", f"Quantum Engineer {i}", f"QCo{i}", "London, UK", "qubits") for i in range(40)]
    monkeypatch.setattr(discovery, "search_jobs", fake_search)
    return calls


async def _lag_probe(stop: asyncio.Event, lags: list):
    last = time.perf_counter()
    while not stop.is_set():
        await asyncio.sleep(0.02)
        now = time.perf_counter()
        lags.append(now - last - 0.02)
        last = now


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test")


def test_thin_feed_discovers_in_the_background(feed_user, ollama, slow_live_search):
    ollama.delay = 0.3  # embedding batches are slow too

    async def flow():
        lags, stop = [], asyncio.Event()
        probe = asyncio.create_task(_lag_probe(stop, lags))
        async with _client() as c:
            t0 = time.perf_counter()
            first = (await c.get("/jobs", params={"tags": "quantum"})).json()
            latency = time.perf_counter() - t0
            again = (await c.get("/jobs", params={"tags": "quantum"})).json()
            while discovery.is_running("quantum", ["London"]):
                await asyncio.sleep(0.05)
            after = (await c.get("/jobs", params={"tags": "quantum"})).json()
        stop.set()
        await probe
        return first, again, after, latency, max(lags)

    first, again, after, latency, max_stall = asyncio.run(flow())
    assert first["discovering"] is True and first["jobs"] == [] and latency < 1.0
    assert again["discovering"] is True and len(slow_live_search) == 1      # one run per key
    assert max_stall < MAX_LOOP_STALL_S, f"event loop stalled {max_stall:.3f}s"
    assert len(after["jobs"]) == 20 and after["has_more"] is True
    assert after["discovering"] is False and len(slow_live_search) == 1     # cooldown


def test_hung_embedder_falls_back_to_unranked_results(feed_user, ollama, monkeypatch):
    jobs_db.add_jobs([make_job(i, f"Quantum Engineer {i}") for i in range(8)])
    monkeypatch.setattr(main, "_FEED_EMBED_TIMEOUT_S", 0.5)
    ollama.delay = 3.0

    async def flow():
        async with _client() as c:
            t0 = time.perf_counter()
            r = (await c.get("/jobs", params={"tags": "quantum", "limit": 5})).json()
            return r, time.perf_counter() - t0

    r, took = asyncio.run(flow())
    assert took < 2.0 and len(r["jobs"]) == 5


def test_fixture_jobs_from_discovery_are_never_stored(db, ollama, monkeypatch):
    async def fixture_only(query, locations, web_search=True):
        return [dict(j) for j in job_searcher._FIXTURE]
    monkeypatch.setattr(discovery, "search_jobs", fixture_only)
    asyncio.run(discovery._discover("anything", ["London"]))
    assert jobs_db.job_count() == 0


@pytest.fixture
def multi_user(db):
    uid = tracker.create_user("multi@x.com", "h")
    # Raw profile text: duplicates that differ only in case / whitespace, and "Remote".
    tracker.update_user_persona(uid, {"preferences": {
        "target_titles": ["Graduate Data Analyst", "graduate data analyst ", "Junior Software Engineer",
                          "Data Engineer", "ML Engineer"],
        "preferred_locations": ["London", "london ", "LONDON", "Manchester", "Remote"],
    }})
    return uid


@pytest.fixture
def recorded_searches(monkeypatch):
    searches = []

    async def record(query, locations, web_search=True):
        searches.append((query, locations))
        return []
    monkeypatch.setattr(discovery, "search_jobs", record)
    return searches


def _feed_as(uid, params=None):
    """GET /jobs as `uid`, then wait for the discovery runs it started."""
    main.app.dependency_overrides[auth.get_current_user] = lambda: auth.User(id=uid, email="multi@x.com")
    try:
        async def flow():
            async with _client() as c:
                body = (await c.get("/jobs", params=params)).json()
                while any(not t.done() for t in discovery._running.values()):
                    await asyncio.sleep(0.01)
            return body
        return asyncio.run(flow())
    finally:
        main.app.dependency_overrides.clear()


def test_feed_uses_every_preferred_location_and_searches_each_target_title_once(multi_user, ollama,
                                                                               recorded_searches):
    jobs_db.add_jobs([make_job(1, "Analyst", location="London, UK"),
                      make_job(2, "Engineer", location="Manchester, UK"),
                      make_job(3, "Designer", location="Leeds, UK"),
                      make_job(4, "Analyst", company="Maple", location="London, Ontario, Canada")])
    body = _feed_as(multi_user)

    assert sorted(j["location"] for j in body["jobs"]) == ["London, UK", "Manchester, UK"]
    assert body["discovering"] is True and body["location"] == "London, Manchester, Remote"
    # One run per distinct title (duplicates don't use up the cap of 3), each over every
    # distinct location except "Remote".
    assert sorted(recorded_searches) == [(t, ["London", "Manchester"]) for t in
                                         ("Data Engineer", "Graduate Data Analyst", "Junior Software Engineer")]


@pytest.mark.parametrize("params, expected", [
    ({"query": "quantum"}, [("quantum", ["London", "Manchester"])]),
    ({"location": "Berlin"}, [(t, ["Berlin"]) for t in
                              ("Data Engineer", "Graduate Data Analyst", "Junior Software Engineer")]),
    ({"query": "quantum", "location": "Berlin"}, [("quantum", ["Berlin"])]),
])
def test_explicit_search_discovers_only_what_was_asked_for(multi_user, ollama, recorded_searches,
                                                           params, expected):
    assert _feed_as(multi_user, params)["discovering"] is True
    assert sorted(recorded_searches) == expected


def test_discovery_covers_at_most_four_preferred_locations(db, ollama, recorded_searches):
    uid = tracker.create_user("many@x.com", "h")
    cities = [f"City {i}" for i in range(12)]
    tracker.update_user_persona(uid, {"preferences": {
        "target_titles": ["Data Engineer", "ML Engineer", "Data Analyst"],
        "preferred_locations": ["Remote", *cities],
    }})
    _feed_as(uid)
    _feed_as(uid)  # a reload doesn't reach for the remaining locations either
    # 3 titles x 4 locations = 12 Adzuna calls per feed load; "Remote" doesn't take a slot.
    assert sorted(recorded_searches) == [(t, cities[:4]) for t in ("Data Analyst", "Data Engineer", "ML Engineer")]


def test_filtering_to_covered_locations_reuses_the_run(multi_user, ollama, recorded_searches):
    _feed_as(multi_user)  # discovers each title over London + Manchester
    recorded_searches.clear()
    assert _feed_as(multi_user, {"location": "london"})["discovering"] is False  # in cooldown
    assert recorded_searches == []
    _feed_as(multi_user, {"location": "Leeds"})
    assert sorted(recorded_searches) == [(t, ["Leeds"]) for t in
                                         ("Data Engineer", "Graduate Data Analyst", "Junior Software Engineer")]


def test_discovery_state_is_per_query_and_location(db, monkeypatch):
    runs = []

    async def flow():
        release = asyncio.Event()

        async def held_search(query, locations, web_search=True):
            runs.append((query, locations))
            await release.wait()
            return []
        monkeypatch.setattr(discovery, "search_jobs", held_search)

        async def settle():
            while any(not t.done() for t in discovery._running.values()):
                await asyncio.sleep(0.01)

        assert discovery.ensure("Data Analyst", ["London", "london ", "Manchester"]) is True
        await asyncio.sleep(0)
        # While it runs: any subset, in any order / case / spacing, with duplicates, joins it.
        assert discovery.ensure("data  analyst", ["LONDON"]) is True
        assert discovery.ensure("Data Analyst", ["manchester", "London", "MANCHESTER"]) is True
        assert discovery.is_running("Data Analyst", ["Manchester", "Paris"])
        assert not discovery.is_running("Data Analyst", ["Paris"])
        assert not discovery.is_running("Data Engineer", ["London"])  # pairs, not locations
        # A location not yet covered runs alone, not alongside the ones already in flight.
        assert discovery.ensure("Data Analyst", ["London", "Leeds"]) is True
        release.set()
        await settle()
        # Afterwards every covered pair is in cooldown, however the request spells it.
        assert discovery.ensure("Data Analyst", ["Manchester"]) is False
        assert discovery.ensure("DATA ANALYST", ["leeds", "London"]) is False
        assert not discovery.is_running("Data Analyst", ["London", "Manchester", "Leeds"])
        # Adding a new location runs only that one.
        assert discovery.ensure("Data Analyst", ["Manchester", "Bristol", "London"]) is True
        assert discovery.is_running("Data Analyst", ["Bristol"])
        await settle()
        assert discovery._running == {}  # every pair of every run is released when it finishes

    asyncio.run(flow())
    assert sorted(runs) == [("Data Analyst", ["Bristol"]), ("Data Analyst", ["Leeds"]),
                            ("Data Analyst", ["London", "Manchester"])]


# ── What the feed says about itself ───────────────────────────────────────────

@pytest.fixture
def sponsored_user(db, monkeypatch):
    uid = tracker.create_user("sponsor@x.com", "h")
    tracker.update_user_persona(uid, {"core_info": {"require_sponsorship": True},
                                      "preferences": {"target_titles": ["Data Engineer"], "preferred_locations": ["London"]}})

    async def no_search(query, locations, web_search=True):
        return []
    monkeypatch.setattr(discovery, "search_jobs", no_search)
    main.app.dependency_overrides[auth.get_current_user] = lambda: auth.User(id=uid, email="sponsor@x.com")
    yield uid
    main.app.dependency_overrides.clear()


def _call(method, path, **kwargs):
    async def flow():
        async with _client() as c:
            return await getattr(c, method)(path, **kwargs)
    return asyncio.run(flow())


def test_page_one_says_how_many_match_and_what_is_hidden(sponsored_user, ollama):
    jobs_db.add_jobs([make_job(1, "Data Engineer", "Open Co", "London, UK", "pipelines"),
                      make_job(2, "Data Engineer", "Closed Co", "London, UK", "We are unable to sponsor visas."),
                      make_job(3, "Data Engineer", "Done Co", "London, UK", "pipelines")])
    tracker.add_application(sponsored_user, {"job_id": "3", "title": "Data Engineer", "company": "Done Co"}, {}, "", {},
                            status="Applied")
    body = _call("get", "/jobs").json()
    assert [j["company"] for j in body["jobs"]] == ["Open Co"]
    assert body["total"] == 1 and body["hidden"] == {"sponsorship": 1, "dealt_with": 1}
    assert body["collection"] is None  # nothing collected yet

    # With the sponsorship filter off, nothing is hidden by it; later pages don't recount.
    assert _call("get", "/jobs", params={"sponsorship": "any"}).json()["hidden"]["sponsorship"] == 0
    assert "total" not in _call("get", "/jobs", params={"page": 2}).json()


def test_the_feed_says_when_it_was_last_refreshed(sponsored_user, ollama):
    run_id = jobs_db.start_collection(["Data Engineer"], ["London"])
    jobs_db.finish_collection(run_id, found=40, added=12)
    status = _call("get", "/jobs").json()["collection"]
    assert (status["running"], status["found"], status["added"], status["failed"]) == (False, 40, 12, False)
    assert status["finished_at"] and status["next_at"] > status["started_at"]


def test_refresh_starts_a_collection_but_not_twice_in_half_an_hour(sponsored_user, ollama, monkeypatch):
    runs = []

    async def fake_collect():
        runs.append(1)
        run_id = jobs_db.start_collection(["Data Engineer"], ["London"])
        jobs_db.finish_collection(run_id, found=3, added=3)
        return jobs_db.last_collection()
    monkeypatch.setattr(discovery, "_collect", fake_collect)

    async def flow():
        async with _client() as c:
            first = await c.post("/jobs/refresh")
            while discovery.collecting():
                await asyncio.sleep(0.01)
            second = await c.post("/jobs/refresh")
            return first, second
    first, second = asyncio.run(flow())
    assert first.status_code == 200 and first.json()["started"] is True and runs == [1]
    assert second.status_code == 429 and "refreshed 0 min ago" in second.json()["detail"]


def test_refresh_needs_target_titles(db, monkeypatch):
    uid = tracker.create_user("blank@x.com", "h")
    main.app.dependency_overrides[auth.get_current_user] = lambda: auth.User(id=uid, email="blank@x.com")
    try:
        r = _call("post", "/jobs/refresh")
    finally:
        main.app.dependency_overrides.clear()
    assert r.status_code == 429 and "target job titles" in r.json()["detail"]
