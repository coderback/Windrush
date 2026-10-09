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
_running: dict[tuple[str, str], asyncio.Task] = {}
_finished_at: dict[tuple[str, str], float] = {}

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


def _search_in_process(query: str, location: str) -> list[dict]:
    """Worker-process entry point: run the async multi-source search on its own event loop."""
    from .job_proxy import search_jobs
    return asyncio.run(search_jobs(query, location))


async def search_jobs(query: str, location: str) -> list[dict]:
    """Live multi-source search, executed in a worker process."""
    global _pool
    try:
        return await asyncio.get_running_loop().run_in_executor(_get_pool(), _search_in_process, query, location)
    except BrokenProcessPool:
        _pool = None  # a worker died (e.g. Chromium OOM) — start a fresh pool next time
        raise


def _key(query: str, location: str) -> tuple[str, str]:
    return (" ".join(query.lower().split()), " ".join(location.lower().split()))


def is_running(query: str, location: str) -> bool:
    task = _running.get(_key(query, location))
    return bool(task and not task.done())


def ensure(query: str, location: str) -> bool:
    """
    Start a background discovery for (query, location) unless one is running or ran recently.
    Returns True while a discovery for this key is in flight (the caller reports `discovering`).
    """
    key = _key(query, location)
    if is_running(query, location):
        return True
    if time.monotonic() - _finished_at.get(key, -_COOLDOWN_S) < _COOLDOWN_S:
        return False
    task = asyncio.create_task(_discover(query, location), name=f"discover:{key}")
    _running[key] = task
    task.add_done_callback(lambda t, k=key: _done(k, t))
    return True


def _done(key: tuple[str, str], task: asyncio.Task) -> None:
    _running.pop(key, None)
    _finished_at[key] = time.monotonic()
    if len(_finished_at) > 1000:  # bound memory: forget the oldest entries
        for k in sorted(_finished_at, key=_finished_at.get)[:500]:
            _finished_at.pop(k, None)
    if not task.cancelled() and task.exception():
        logger.warning("discovery %r failed: %s", key, task.exception())


async def _discover(query: str, location: str) -> None:
    from .main import _infer_level  # deferred: main imports this module
    started = time.monotonic()
    jobs = await search_jobs(query, location)  # concurrency is capped by the pool size
    # search_jobs falls back to the bundled mock fixture when every live source is empty;
    # those must never be persisted as real listings.
    live = [dict(j) for j in jobs if j.get("source") != "fixture"]
    for j in live:
        j["source"] = j.get("source") or "live"
        j["level"] = _infer_level(j.get("title", ""))
    # Embedding is mostly waiting on Ollama, so a thread is enough here.
    added, refreshed = (await asyncio.to_thread(jobs_db.add_jobs, live)) if live else (0, 0)
    logger.info("discovery %r/%r: %d found, %d added, %d refreshed in %.1fs",
                query, location, len(live), added, refreshed, time.monotonic() - started)
