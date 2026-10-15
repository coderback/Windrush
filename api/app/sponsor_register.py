"""
The UK Home Office register of licensed sponsors (workers): a "licensed sponsor" signal per employer.

The register lists every organisation licensed to sponsor work visas, about 120k of them on the
Skilled Worker route. A licence means an employer CAN sponsor, not that it will for a given role,
so it is a weaker signal than an ad that says so, and an ad that rules sponsorship out still wins.
gov.uk republishes it daily as a CSV linked from REGISTER_PAGE; the stored copy is refreshed weekly.
"""
import asyncio
import csv
import io
import logging
import os
import re
from datetime import datetime, timedelta, timezone

from . import http_client, jobs_db
from .company_names import normalise_company_name

logger = logging.getLogger("windrush.sponsor_register")

REGISTER_PAGE = "https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers"
_CSV_LINK = re.compile(r"https://assets\.publishing\.service\.gov\.uk/[^\"'\s<>]+\.csv")
_ROUTE = "Skilled Worker"
_MAX_AGE = timedelta(days=7)
_CHECK_EVERY_S = 24 * 3600
# Far below the real count (~120k): a smaller parse means a truncated or changed file, kept out.
_MIN_SPONSORS = 10_000
_TRADING_AS = re.compile(r"\s+(?:t/a|trading\s+as)\s+", re.I)


def parse_register(csv_text: str) -> dict[str, tuple[str, str]]:
    """{normalised name: (organisation name, town)} for organisations licensed on the Skilled Worker
    route. One with a trading name ("Acme Ltd T/A Rocket Labs") is found under either name."""
    sponsors: dict[str, tuple[str, str]] = {}
    for row in csv.DictReader(io.StringIO(csv_text)):
        if (row.get("Route") or "").strip() != _ROUTE:
            continue
        name = (row.get("Organisation Name") or "").strip()
        town = (row.get("Town/City") or "").strip()
        for part in _TRADING_AS.split(name):
            key = normalise_company_name(part)
            if key:
                sponsors.setdefault(key, (name, town))
    return sponsors


async def refresh(force: bool = False) -> int | None:
    """
    Download the current register into jobs.db unless the stored copy is under a week old. Returns
    how many sponsors were stored, or None when the stored copy was fresh. Raises on failure, leaving
    the stored copy as it was.
    """
    fetched_at = await asyncio.to_thread(jobs_db.sponsor_register_fetched_at)
    if not force and fetched_at and datetime.now(timezone.utc) - fetched_at < _MAX_AGE:
        return None
    async with http_client.async_client(follow_redirects=True, timeout=120.0) as client:
        page = await client.get(REGISTER_PAGE)
        page.raise_for_status()
        link = _CSV_LINK.search(page.text)
        if not link:
            raise ValueError(f"no register CSV linked from {REGISTER_PAGE}")
        csv_resp = await client.get(link.group(0))
        csv_resp.raise_for_status()
    sponsors = await asyncio.to_thread(parse_register, csv_resp.content.decode("utf-8-sig", errors="replace"))
    if len(sponsors) < _MIN_SPONSORS:
        raise ValueError(f"the register parsed to only {len(sponsors)} sponsors; keeping the stored copy")
    await asyncio.to_thread(jobs_db.replace_sponsors, sponsors, link.group(0))
    logger.info("Sponsor register refreshed: %d Skilled Worker sponsors from %s", len(sponsors), link.group(0))
    return len(sponsors)


async def keep_fresh() -> None:
    """Background task: refresh the register when it's over a week old, checking daily. Set
    SPONSOR_REGISTER_REFRESH=0 to turn it off (the stored copy, if any, is still used)."""
    if os.environ.get("SPONSOR_REGISTER_REFRESH", "1") == "0":
        return
    while True:
        try:
            await refresh()
        except Exception as exc:
            logger.warning("Sponsor register refresh failed (will retry tomorrow): %s", exc)
        await asyncio.sleep(_CHECK_EVERY_S)
