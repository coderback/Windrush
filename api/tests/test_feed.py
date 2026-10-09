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

    async def fake_search(query, location):
        calls.append((query, location))
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
            while discovery.is_running("quantum", "London"):
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
    async def fixture_only(query, location):
        return [dict(j) for j in job_searcher._FIXTURE]
    monkeypatch.setattr(discovery, "search_jobs", fixture_only)
    asyncio.run(discovery._discover("anything", "London"))
    assert jobs_db.job_count() == 0
