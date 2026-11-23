"""
Applications made outside Windrush get the treatment of ones made through it: each application tracked from email
is linked to the feed ad it was made through, and a linked application gets the same fit check (fit score, level
match, skill gaps) and opens that ad's job page.

An ad is a candidate when it's at the same employer, its title has every word that tells the application's role
apart (as Gmail compares roles), and the feed had it before the application (up to six months before). It's linked
only when it's certain enough: the one candidate the user opened the posting of, or the only candidate. Otherwise
the application panel offers the candidates and the user picks. A role the email didn't name is never matched.
"""
import asyncio
import logging
from datetime import datetime, timedelta

from . import jobs_db, tracker

logger = logging.getLogger("windrush.ad_match")

_BEFORE_DAYS = 183       # an ad first seen longer before the application than this is another opening
_AFTER_DAYS = 7          # the feed often collects an ad a few days after it went up (seen in real data: 3 days)
_NO_ROLE = "Role not stated"
# Words in an emailed role that say where, not what: the ad's title often leaves them out.
_PLACE_WORDS = {"london", "leeds", "manchester", "birmingham", "bristol", "edinburgh", "glasgow", "belfast", "cardiff",
                "cambridge", "oxford", "reading", "newcastle", "sheffield", "liverpool", "nottingham", "north", "south",
                "east", "west", "emea", "europe", "eur", "uk", "remote", "hybrid", "roles"}


def role_words(role: str) -> set[str]:
    """What tells the role apart, as Gmail compares roles, without requisition codes ("R210016") or places."""
    from .gmail import _role_words
    return {w for w in _role_words(role) if not any(c.isdigit() for c in w) and w not in _PLACE_WORDS}


def _day(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _in_window(ad: dict, applied: datetime | None) -> bool:
    seen = _day(ad.get("created_at") or "")
    if not seen or not applied:
        return bool(seen)
    return applied - timedelta(days=_BEFORE_DAYS) <= seen <= applied + timedelta(days=_AFTER_DAYS)


def candidates(app: dict, opened: dict[str, str] | None = None, *, any_role: bool = False) -> list[dict]:
    """The feed ads this application may have been made through, the ones the user opened first, then newest.
    `any_role` drops the title test (for the user's own choice when the email named no role)."""
    from .gmail import _key
    opened = opened or {}
    applied = _day(app.get("date_applied") or app.get("created_at") or "")
    role = (app.get("job_title") or "").strip()
    want = set() if role == _NO_ROLE else role_words(role)
    if not want and not any_role:
        return []
    out = []
    for ad in jobs_db.ads_at_company(app.get("company") or ""):
        if not _in_window(ad, applied):
            continue
        if want and not want <= set(_key(ad["title"]).split()):
            continue
        out.append({**ad, "opened": opened.get(ad["id"], "")})
    return sorted(out, key=lambda a: (bool(a["opened"]), a["created_at"]), reverse=True)[:20]


def _choose(found: list[dict]) -> dict | None:
    opened = [a for a in found if a["opened"]]
    if len(opened) == 1:
        return opened[0]
    return found[0] if len(found) == 1 else None


def link_one(app: dict) -> bool:
    """Link this email-tracked application to its ad when one is certain enough; it's tried once."""
    found = candidates(app, tracker.opened_jobs(app["user_id"]))
    ad = _choose(found)
    if ad:
        linked = tracker.link_application(app["user_id"], app["id"], ad, "matched")
        logger.info("ad_match: application %s -> ad %s (%d candidates)", app["id"], ad["id"], len(found))
        return linked
    tracker.mark_ad_checked(app["id"])
    return False


def link_pending(limit: int = 200) -> tuple[int, int]:
    """(tried, linked) over applications tracked from email that matching hasn't tried."""
    apps = tracker.applications_to_match(limit)
    return len(apps), sum(link_one(a) for a in apps)


_MIN_AD_TEXT = 200      # as for /jobs/analyze: below this there's no ad to score against


async def fit_check(app: dict) -> bool:
    """The fit check a Windrush application gets, on this application's linked ad. Stores its score, level match
    and gaps; an ad with no readable text, or a failed call, is recorded and not tried again. False only when the
    model call failed."""
    from .agent import execute_tool
    job = (await asyncio.to_thread(jobs_db.find_by_job_id, app["job_id"])
           or await asyncio.to_thread(jobs_db.get_job, app["job_id"]) or {})
    if job:
        job = await jobs_db.ensure_full_description(job)
    if len((job.get("description") or "").strip()) < _MIN_AD_TEXT:
        tracker.set_fit(app["id"], None)
        return True
    persona = await asyncio.to_thread(tracker.get_user_persona, app["user_id"])
    try:
        result = await execute_tool("score_job_fit", {"jobs": [job], "persona": persona})
        top = (result.get("ranked_jobs") or [None])[0]
    except Exception as exc:
        logger.warning("ad_match: fit check failed for %s: %s", app["id"], type(exc).__name__)
        top = None
    if not isinstance(top, dict) or not isinstance(top.get("fit_score"), (int, float)):
        tracker.set_fit(app["id"], None)
        return False
    tracker.set_fit(app["id"], {"fit_score": top["fit_score"], "level_match": top.get("level_match"),
                                "skill_gaps": [g for g in top.get("skill_gaps") or [] if isinstance(g, str)][:12]})
    return True


_IDLE_S = 60
_BACKOFF_S = 600
_FIT_BATCH = 3


async def keep_linking() -> None:
    """Background task: link newly tracked applications to their ads, then fit-check linked ones a few at a time
    (each check is an LLM call; on whenever LLM job attributes are)."""
    from .job_attributes import enabled
    while True:
        checked = failed = 0
        try:
            tried, linked = await asyncio.to_thread(link_pending)
            if tried:
                logger.info("ad_match: linked %d of %d applications to feed ads", linked, tried)
            if enabled():
                for app in await asyncio.to_thread(tracker.applications_to_fit_check, _FIT_BATCH):
                    checked += 1
                    failed += not await fit_check(app)
        except Exception as exc:
            logger.warning("ad_match: pass failed: %s", exc)
            failed = checked = 1
        await asyncio.sleep(_BACKOFF_S if checked and failed == checked else _IDLE_S if not checked else 0)
