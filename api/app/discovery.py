"""
Background live job discovery for the feed.

When the local jobs table has too few matches, /jobs used to run the whole live search
(a Chromium scrape + ~70 ATS/API calls) and then embed every result *synchronously on the
event loop* — stalling every other request for the duration. Now /jobs calls ensure(),
which starts that work as a background task and returns immediately; the frontend re-polls
the feed while `discovering` is true.
"""
import asyncio
import logging
import multiprocessing
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool

from . import jobs_db

logger = logging.getLogger("windrush.discovery")

_COOLDOWN_S = 30 * 60          # don't re-run the same (query, location) within this window
_MAX_CONCURRENT = 2            # each run may launch Chromium; cap total load
# State is kept per normalised (query, location) pair, not per location set, so filtering the
# feed to a subset of the locations a run covers reuses that run instead of starting another.
# A run over several locations is registered under each of its pairs.
_Pair = tuple[str, str]
_running: dict[_Pair, asyncio.Task] = {}
_finished_at: dict[_Pair, float] = {}

# The live search runs in worker *processes*: it fans out to ~70 job boards and does a lot of
# CPU work on the results (multi-MB JSON, HTML-to-text, exposure scoring). In threads that
# work contends for the GIL with the event loop and stalls the API for ~1s at a time; in a
# separate process it can't. 'spawn' avoids forking a process that has live threads.
_pool: ProcessPoolExecutor | None = None


def _get_pool() -> ProcessPoolExecutor:
    global _pool
    if _pool is None:
        _pool = ProcessPoolExecutor(max_workers=_MAX_CONCURRENT,
                                    mp_context=multiprocessing.get_context("spawn"))
    return _pool


def shutdown() -> None:
    """Stop worker processes (called from the app's lifespan on exit)."""
    global _pool
    if _pool is not None:
        _pool.shutdown(wait=False, cancel_futures=True)
        _pool = None


def _search_in_process(query: str, locations: list[str]) -> list[dict]:
    """Worker-process entry point: run the async multi-source search on its own event loop."""
    from .job_proxy import search_jobs
    return asyncio.run(search_jobs(query, locations))


async def search_jobs(query: str, locations: list[str]) -> list[dict]:
    """Live multi-source search, executed in a worker process."""
    global _pool
    try:
        return await asyncio.get_running_loop().run_in_executor(_get_pool(), _search_in_process, query, locations)
    except BrokenProcessPool:
        _pool = None  # a worker died (e.g. Chromium OOM) — start a fresh pool next time
        raise


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _pairs(query: str, locations: list[str]) -> dict[_Pair, str]:
    """Normalised (query, location) pair -> the first spelling of that location."""
    pairs: dict[_Pair, str] = {}
    for loc in locations:
        pairs.setdefault((_norm(query), _norm(loc)), loc)
    return pairs


def is_running(query: str, locations: list[str]) -> bool:
    """True while a discovery covering any of these locations for `query` is in flight."""
    tasks = [_running.get(pair) for pair in _pairs(query, locations)]
    return any(task is not None and not task.done() for task in tasks)


def ensure(query: str, locations: list[str]) -> bool:
    """
    Start one background discovery for `query` over those `locations` that are neither in
    flight nor ran recently (only the location-dependent sources fan out over them).
    Returns True while a discovery for any of the locations is in flight (the caller reports
    `discovering`).
    """
    now = time.monotonic()
    # A pair still in _running is in flight, or finished with its _done callback pending.
    todo = {pair: loc for pair, loc in _pairs(query, locations).items()
            if pair not in _running and now - _finished_at.get(pair, -_COOLDOWN_S) >= _COOLDOWN_S}
    if todo:
        task = asyncio.create_task(_discover(query, list(todo.values())), name=f"discover:{list(todo)}")
        for pair in todo:
            _running[pair] = task
        task.add_done_callback(lambda t, ps=tuple(todo): _done(ps, t))
    return is_running(query, locations)


def _done(pairs: tuple[_Pair, ...], task: asyncio.Task) -> None:
    finished = time.monotonic()
    for pair in pairs:
        _running.pop(pair, None)
        _finished_at[pair] = finished
    if len(_finished_at) > 1000:  # bound memory: forget the oldest entries
        for k in sorted(_finished_at, key=_finished_at.get)[:500]:
            _finished_at.pop(k, None)
    if not task.cancelled() and task.exception():
        logger.warning("discovery %r failed: %s", pairs, task.exception())


async def _discover(query: str, locations: list[str]) -> None:
    started = time.monotonic()
    jobs = await search_jobs(query, locations)  # concurrency is capped by the pool size
    # search_jobs falls back to the bundled mock fixture when every live source is empty;
    # those must never be persisted as real listings.
    live = [dict(j) for j in jobs if j.get("source") != "fixture"]
    for j in live:
        j["source"] = j.get("source") or "live"
    # Embedding is mostly waiting on Ollama, so a thread is enough here.
    added, refreshed = (await asyncio.to_thread(jobs_db.add_jobs, live)) if live else (0, 0)
    logger.info("discovery %r/%r: %d found, %d added, %d refreshed in %.1fs",
                query, locations, len(live), added, refreshed, time.monotonic() - started)
