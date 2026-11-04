"""The tests employers have asked for, from what the email reader recorded: what's still to do, by when, and how those
done went. Employers give 3 to 7 days and invitations come in bursts, so it's easy to miss one for want of a reminder.

One row per application, however many reminders it got. An email from an employer not tracked yet counts too, because
the deadline is just as real. Nothing here changes an application.
"""
from datetime import date, timedelta

from . import tracker
from .company_names import normalise_company_name

_STILL_SHOWN_DAYS = 14      # past its deadline, or since the last email when it gave none: some tests can still be taken
_NEW_TEST_AFTER_DAYS = 2    # a request this long after one was marked done or declined is a new test, not a late reminder
_ENDED_BY = ("Rejected", "Discarded", "Offer")
_VERDICTS = ("rejected", "interview", "offer")


def _is_request(event: dict) -> bool:
    # Emails read before tests were tracked only have their kind
    return event["assessment"] == "requested" or (event["kind"] == "assessment" and not event["assessment"])


def _company_key(name: str) -> str:
    return normalise_company_name(name or "").lower()


def _key_of(event: dict, applications_at: dict[str, set[str]]) -> str | None:
    """Which application an email is about. One that isn't linked joins the only application at that employer, or else
    the employer's own row. None when it doesn't even name one: "your assessment was submitted" says nothing useful."""
    if event.get("application_id"):
        return f"app:{event['application_id']}"
    company = _company_key(event.get("company"))
    if not company:
        return f"mail:{event['gmail_id']}" if _is_request(event) else None
    linked = applications_at.get(company, set())
    return next(iter(linked)) if len(linked) == 1 else f"co:{company}"


def _day(event_time: str) -> date:
    return date.fromisoformat(event_time[:10])


def _groups(user_id: str) -> dict[str, dict]:
    events = tracker.assessment_events(user_id)
    verdicts_by_company: dict[str, list[date]] = {}
    applications_at: dict[str, set[str]] = {}
    groups: dict[str, dict] = {}
    for event in events:
        company = _company_key(event.get("app_company") or event["company"])
        if event["kind"] in _VERDICTS:
            verdicts_by_company.setdefault(company, []).append(_day(event["received_at"]))
        if event.get("application_id") and (_is_request(event) or event["assessment"]):
            applications_at.setdefault(company, set()).add(f"app:{event['application_id']}")
    for event in events:
        key = _key_of(event, applications_at)
        if key and (_is_request(event) or event["assessment"] in ("completed", "missed")):
            groups.setdefault(key, {"key": key, "requests": [], "finished": [], "missed": [], "verdicts": [], "last": event})
    for event in events:
        group = groups.get(_key_of(event, applications_at))
        if not group:
            continue
        group["last"] = event
        day = _day(event["received_at"])
        if _is_request(event):
            group["requests"].append(event)
        if event["assessment"] == "completed":
            group["finished"].append(day)
        if event["assessment"] == "missed":
            group["missed"].append(day)
        if event["kind"] in _VERDICTS:
            group["verdicts"].append((day, event["kind"]))
    for key, group in groups.items():
        if key.startswith("co:"):   # not linked to an application yet: its verdict may be, under the same employer
            group["verdicts"] += [(d, "rejected") for d in verdicts_by_company.get(key[3:], []) if (d, "rejected") not in group["verdicts"]]
    return groups


def _row(group: dict, mark: dict | None, today: date) -> dict | None:
    """What's still to do for one application, or None when nothing is."""
    settled = list(group["finished"])
    if mark:
        settled.append(_day(mark["marked_at"]))
    live = group["requests"]
    if settled:
        live = [e for e in live if _day(e["received_at"]) > max(settled) + timedelta(days=_NEW_TEST_AFTER_DAYS)]
    if not live or group["last"].get("app_status") in _ENDED_BY:
        return None
    latest = live[-1]
    if any(day >= _day(latest["received_at"]) for day, _ in group["verdicts"]):
        return None
    due = min((e["deadline"] for e in live if e["deadline"]), default=None)
    last_seen = _day(latest["received_at"])
    if (today - date.fromisoformat(due) if due else today - last_seen) > timedelta(days=_STILL_SHOWN_DAYS):
        return None
    return {
        "key": group["key"],
        "company": latest.get("app_company") or latest["company"] or "Employer not named",
        "role": latest.get("app_title") or latest["role"] or "",
        "tracked": bool(latest.get("application_id")),
        "deadline": due,
        "days_left": (date.fromisoformat(due) - today).days if due else None,
        "minutes": next((e["minutes"] for e in reversed(live) if e["minutes"]), None),
        "summary": latest["summary"],
        "gmail_id": latest["gmail_id"],
        "emails": len(live),
    }


def _record(groups: dict[str, dict], marks: dict[str, dict], today: date) -> dict:
    """How the tests went, counting only those known to be done or missed: older emails don't say."""
    done = moved_on = not_passed = missed = 0
    for key, group in groups.items():
        mark = marks.get(key)
        finished = list(group["finished"])
        if mark and mark["state"] == "done":
            finished.append(_day(mark["marked_at"]))
        status = group["last"].get("app_status")
        if finished:
            done += 1
            after = [kind for day, kind in group["verdicts"] if day >= min(finished)]
            if status in ("Interview", "Offer") or "interview" in after or "offer" in after:
                moved_on += 1
            elif status == "Rejected" or "rejected" in after:
                not_passed += 1
        elif not (mark and mark["state"] == "skipped"):
            due = min((e["deadline"] for e in group["requests"] if e["deadline"]), default=None)
            if group["missed"] or (due and date.fromisoformat(due) < today):
                missed += 1
    return {"done": done, "moved_on": moved_on, "not_passed": not_passed, "waiting": done - moved_on - not_passed, "missed": missed}


def overview(user_id: str, today: date | None = None) -> dict:
    today = today or date.today()
    groups = _groups(user_id)
    marks = tracker.assessment_marks(user_id)
    rows = [row for key, group in groups.items() if (row := _row(group, marks.get(key), today))]
    # What's due first, then those with no date, then those already past
    rows.sort(key=lambda r: (0, r["days_left"]) if (r["days_left"] or 0) >= 0 and r["deadline"] else
              (1, 0) if not r["deadline"] else (2, -r["days_left"]))
    return {"open": rows, "record": _record(groups, marks, today)}


def mark(user_id: str, key: str, state: str) -> dict:
    """Mark a test done or not being taken, or take the mark back with 'open'."""
    if state not in ("done", "skipped", "open"):
        raise ValueError("state must be done, skipped or open")
    if key not in _groups(user_id):
        raise LookupError(key)
    tracker.set_assessment_mark(user_id, key, None if state == "open" else state)
    return overview(user_id)
