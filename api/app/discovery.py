"""
Background live job discovery for the feed.

When the local jobs table has too few matches, /jobs used to run the whole live search
(a Chromium scrape + ~70 ATS/API calls) and then embed every result *synchronously on the
event loop* — stalling every other request for the duration. Now /jobs calls ensure(),
which starts that work as a background task and returns immediately; the frontend re-polls
the feed while `discovering` is true.

keep_collecting() also runs a scheduled collection for every user's target titles and preferred
locations, so the feed fills and stays current without anyone searching, and expires jobs no source
has listed for a few days.
"""
import asyncio
import logging
import multiprocessing
import os
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from datetime import datetime, timedelta, timezone

from . import job_searcher, jobs_db, tracker

logger = logging.getLogger("windrush.discovery")

_COOLDOWN_S = 30 * 60          # don't re-run the same (query, location) within this window
_MAX_CONCURRENT = 2            # each run may launch Chromium; cap total load
# The web search (level 3) runs fixed site: searches that don't depend on what's searched for, and its
# API has a monthly quota: run it at most once a day, by whichever search or collection comes first.
_WEB_SEARCH = "web_search"
_WEB_SEARCH_EVERY_S = 24 * 3600

# Scheduled collection: every JOB_COLLECT_HOURS (0 turns it off), checked every _COLLECT_TICK_S.
_COLLECT_EVERY_S = float(os.environ.get("JOB_COLLECT_HOURS", "6") or 0) * 3600
_COLLECT_TICK_S = 10 * 60
_COLLECT_FIRST_DELAY_S = 2 * 60   # let the app settle after a restart
_MAX_COLLECT_TITLES = 12
_MAX_COLLECT_LOCATIONS = 4        # each location is one aggregator call per title
# A job no source has listed for this long has closed (or nothing searches for it any more). A
# collection re-lists open jobs every few hours; sources that sample (web search, the aggregator) can
# miss one for a run or two.
_UNSEEN_DAYS = 3
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


def _collect_in_process(queries: list[str], locations: list[str], web_search: bool,
                        boards: dict[str, list[tuple[str, str]]]) -> list[dict]:
    """Worker-process entry point: run the async multi-source search on its own event loop."""
    from .job_searcher import collect_jobs
    return asyncio.run(collect_jobs(queries, locations, web_search=web_search, boards=boards))


def _refresh_boards_in_process(lookups: list[str], checks: list[tuple[str, str]]) -> dict:
    """Worker-process entry point: look employers' boards up and check known ones (big JSON, so not here)."""
    from .job_searcher import refresh_boards
    return asyncio.run(refresh_boards(lookups, checks))


async def _run_in_pool(fn, *args):
    global _pool
    try:
        return await asyncio.get_running_loop().run_in_executor(_get_pool(), fn, *args)
    except BrokenProcessPool:
        _pool = None  # a worker died (e.g. Chromium OOM) — start a fresh pool next time
        raise


def _boards() -> dict[str, list[tuple[str, str]]]:
    """The job boards to fetch: the listed ones and the ones found since, without any that have gone."""
    return job_searcher._all_boards(jobs_db.found_boards(), jobs_db.gone_boards())


async def _in_pool(queries: list[str], locations: list[str], web_search: bool) -> list[dict]:
    boards = await asyncio.to_thread(_boards)
    return await _run_in_pool(_collect_in_process, queries, locations, web_search, boards)


async def search_jobs(query: str, locations: list[str], web_search: bool = True) -> list[dict]:
    """Live multi-source search, executed in a worker process."""
    return await _in_pool([query], locations, web_search)


async def collect_jobs(queries: list[str], locations: list[str], web_search: bool = True) -> list[dict]:
    """Live search for several queries in one pass over the sources, executed in a worker process."""
    return await _in_pool(queries, locations, web_search)


# ── Job boards ────────────────────────────────────────────────────────────────
# Each collection looks a few employers up (ones the aggregators and the web search name, licensed
# sponsors first) and checks a few known boards, so new boards are fetched from then on and a board
# that has gone stops being asked for.

_BOARD_LOOKUPS_PER_RUN = 20
_BOARD_RETRY_DAYS = 30          # look an employer up again after this long: they may have opened a board
_BOARD_CHECK_DAYS = 7
_BOARD_CHECKS_PER_RUN = 40


async def _board_refresh(lookups: list[str], checks: list[tuple[str, str]]) -> dict:
    return await _run_in_pool(_refresh_boards_in_process, lookups, checks)


async def refresh_boards() -> dict | None:
    """Look up employers and check boards (see job_searcher.refresh_boards), and store what's learnt.
    Returns its result, or None when there was nothing to do."""
    listed = job_searcher.listed_boards()
    have = listed + await asyncio.to_thread(jobs_db.found_boards)
    lookups = await asyncio.to_thread(jobs_db.employers_to_look_up, _BOARD_LOOKUPS_PER_RUN, _BOARD_RETRY_DAYS, have)
    checks = await asyncio.to_thread(jobs_db.boards_due_check, listed, _BOARD_CHECK_DAYS, _BOARD_CHECKS_PER_RUN)
    if not lookups and not checks:
        return None
    result = await _board_refresh(lookups, checks)
    await asyncio.to_thread(jobs_db.save_found_boards, result["found"])
    await asyncio.to_thread(jobs_db.mark_looked_up, lookups,
                            {company: f"{ats}/{slug}" for ats, slug, company, _ in result["found"]})
    await asyncio.to_thread(jobs_db.record_board_checks, result["alive"], result["gone"], listed)
    return result


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


async def _web_search_due() -> bool:
    return await asyncio.to_thread(jobs_db.source_due, _WEB_SEARCH, _WEB_SEARCH_EVERY_S)


async def _store(jobs: list[dict]) -> tuple[list[dict], int, int]:
    """(the live jobs, added, refreshed). The searches fall back to the bundled mock fixture when every
    live source is empty; those must never be persisted as real listings."""
    live = [dict(j) for j in jobs if j.get("source") != "fixture"]
    for j in live:
        j["source"] = j.get("source") or "live"
    # Embedding is mostly waiting on Ollama, so a thread is enough here.
    added, refreshed = (await asyncio.to_thread(jobs_db.add_jobs, live)) if live else (0, 0)
    return live, added, refreshed


async def _discover(query: str, locations: list[str]) -> None:
    started = time.monotonic()
    web = await _web_search_due()
    jobs = await search_jobs(query, locations, web_search=web)  # concurrency is capped by the pool size
    if web:
        await asyncio.to_thread(jobs_db.mark_source_run, _WEB_SEARCH)
    live, added, refreshed = await _store(jobs)
    logger.info("discovery %r/%r: %d found, %d added, %d refreshed in %.1fs",
                query, locations, len(live), added, refreshed, time.monotonic() - started)


# ── Scheduled collection ──────────────────────────────────────────────────────

def collection_plan() -> tuple[list[str], list[str]]:
    """(searches, locations) for a collection: every user's target titles over their preferred locations
    ("Remote" isn't a place to search; remote jobs are kept wherever they're found), or London when
    nobody has any, the same default as the feed's discovery."""
    titles, locations = tracker.collection_targets()
    places = [l for l in locations if l.lower() != "remote"][:_MAX_COLLECT_LOCATIONS] or ["London"]
    return titles[:_MAX_COLLECT_TITLES], places


async def collect() -> dict | None:
    """Run one collection now: search every target title in one pass over the sources, store what's
    found, then expire the jobs nobody has listed for _UNSEEN_DAYS. Returns the stored run, or None when
    no user has a target title."""
    searches, locations = await asyncio.to_thread(collection_plan)
    if not searches:
        logger.info("collection skipped: no user has a target title")
        return None
    run_id = await asyncio.to_thread(jobs_db.start_collection, searches, locations)
    started_at, started = datetime.now(timezone.utc), time.monotonic()
    try:
        try:
            await refresh_boards()  # first, so a board found now is fetched in this collection
        except Exception:
            logger.exception("job board refresh failed; collecting with the boards already known")
        web = await _web_search_due()
        jobs = await collect_jobs(searches, locations, web_search=web)
        if web:
            await asyncio.to_thread(jobs_db.mark_source_run, _WEB_SEARCH)
        live, added, refreshed = await _store(jobs)
        # Only after a collection that found something: a run with every source down mustn't empty the feed.
        expired = (await asyncio.to_thread(jobs_db.expire_unseen,
                                           (started_at - timedelta(days=_UNSEEN_DAYS)).isoformat())) if live else 0
    except Exception as exc:
        await asyncio.to_thread(jobs_db.finish_collection, run_id, error=f"{type(exc).__name__}: {exc}"[:300])
        raise
    await asyncio.to_thread(jobs_db.finish_collection, run_id, found=len(live), added=added,
                            refreshed=refreshed, expired=expired)
    logger.info("collection %r over %r: %d found, %d added, %d refreshed, %d expired in %.0fs",
                searches, locations, len(live), added, refreshed, expired, time.monotonic() - started)
    return await asyncio.to_thread(jobs_db.last_collection)


def _collection_due(now: datetime) -> bool:
    last = jobs_db.last_collection()
    if last is None:
        return True
    # From when the last one started, whatever its outcome, so a failing run doesn't repeat every tick.
    return (now - datetime.fromisoformat(last["started_at"])).total_seconds() >= _COLLECT_EVERY_S


async def keep_collecting() -> None:
    """Background task: a collection every JOB_COLLECT_HOURS (default 6; 0 turns it off). The last run
    is stored, so a restart neither repeats a recent one nor waits a whole interval for an overdue one."""
    if _COLLECT_EVERY_S <= 0:
        logger.info("Scheduled job collection is off (JOB_COLLECT_HOURS=0)")
        return
    await asyncio.sleep(_COLLECT_FIRST_DELAY_S)
    while True:
        try:
            if await asyncio.to_thread(_collection_due, datetime.now(timezone.utc)):
                await collect()
        except Exception:
            logger.exception("scheduled job collection failed")
        await asyncio.sleep(_COLLECT_TICK_S)
