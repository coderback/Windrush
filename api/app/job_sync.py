"""Run one job collection now (the same one the API schedules, see discovery.keep_collecting):
every user's target titles over their preferred locations.

    docker compose exec api python -m app.job_sync
"""
import asyncio
import logging

from . import discovery, jobs_db, tracker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("windrush.job_sync")


async def sync_jobs() -> None:
    tracker.init_db()
    jobs_db.init_db()
    try:
        run = await discovery.collect()
    finally:
        discovery.shutdown()
    if run:
        logger.info("Collection done: %d found, %d added, %d refreshed, %d expired",
                    run["found"], run["added"], run["refreshed"], run["expired"])


if __name__ == "__main__":
    asyncio.run(sync_jobs())
