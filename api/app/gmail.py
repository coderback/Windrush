"""
Gmail tracking: reads the user's job emails (read-only) and keeps their applications' statuses up to date.

Connecting is Google's OAuth with the gmail.readonly scope: Windrush can read mail and nothing else (it can't
send, delete or change anything). The refresh token is stored encrypted (crypto.py), like the job-site password.

A sync (every 30 minutes, or on demand) looks only at mail that could be about an application: from an applicant
tracking system, or naming a company the user has applied to, or with an application-style subject. A model
reads each one and says what it means (received / assessment / interview / offer / rejected / other / unrelated)
and which application it is about; code then checks the email really names that company. What happens next:
  - a clear step forward (Applied → Interview, … → Rejected) on a matched application is made at once, and can be undone;
  - anything uncertain, or going backwards (an interview after a rejection), or on an application the user
    discarded, is suggested and waits for them;
  - an email about an application Windrush couldn't match waits for the user to link it.
Only the sender, subject, date and a short snippet of a job email are kept; unrelated mail leaves no content.
"""
import asyncio
import base64
import html
import logging
import os
import re
import secrets
import time
from datetime import datetime, timezone
from email.utils import parseaddr
from urllib.parse import urlencode

from . import agent, http_client, tracker
from .company_names import normalise_company_name

logger = logging.getLogger("windrush.gmail")

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
_API = "https://gmail.googleapis.com/gmail/v1/users/me"

_STATE_TTL_S = 600
_FIRST_SYNC_DAYS = 60       # how far back the first sync reads
_OVERLAP_S = 600            # each sync re-reads the last few minutes, for mail that arrived while one ran
_MAX_MESSAGES = 80          # per sync
_BODY_CHARS = 2500          # of each email, for the model
_MAX_APPLICATIONS = 80      # most recent, offered to the model to match
_EVERY_S = 30 * 60

# Applicant tracking systems' mail domains: mail from these is about an application, whoever it names.
ATS_SENDERS = ("greenhouse.io", "greenhouse-mail.io", "lever.co", "ashbyhq.com", "workable.com", "myworkday.com",
               "workday.com", "smartrecruiters.com", "icims.com", "successfactors.com", "taleo.net", "jobvite.com",
               "bamboohr.com", "teamtailor.com", "recruitee.com", "pinpointhq.com", "eightfold.ai", "hirevue.com",
               "oraclecloud.com", "applytojob.com")
_SUBJECT_TERMS = ("application", "applying", "interview", "assessment", '"next steps"', "offer", "unfortunately",
                  "candidacy", '"your interest"')
_SUBJECT_RE = re.compile(r"applica|applying|applied|interview|assessment|next step|candidacy|offer|unfortunately|"
                         r"regret|your interest|update on your|recruit", re.I)

KIND_STATUS = {"received": "Applied", "assessment": "Responded", "interview": "Interview", "offer": "Offer",
               "rejected": "Rejected"}
# How far along each status is; an email only moves an application forward on its own.
_RANK = {"Saved": 0, "Evaluated": 0, "Pending Review": 1, "Applied": 2, "Responded": 3, "Interview": 4, "Offer": 5}


class GmailError(Exception):
    """Something the user should be told, in their words."""


# ── Configuration and connecting ──────────────────────────────────────────────────────────────

def _client_id() -> str:
    return os.environ.get("GOOGLE_CLIENT_ID", "").strip()


def _client_secret() -> str:
    return os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()


def redirect_uri() -> str:
    return os.environ.get("GOOGLE_REDIRECT_URI", "http://localhost/api/gmail/callback").strip()


def configured() -> bool:
    return bool(_client_id() and _client_secret())


_states: dict[str, tuple[str, float]] = {}            # OAuth state → (user id, expires at)
_tokens: dict[str, tuple[str, float]] = {}            # user id → (access token, expires at)


def auth_url(user_id: str) -> str:
    """Google's consent page for this user; its state ties the callback (a plain redirect) back to them."""
    now = time.time()
    for state, (_, expires) in list(_states.items()):
        if expires < now:
            _states.pop(state, None)
    state = secrets.token_urlsafe(24)
    _states[state] = (user_id, now + _STATE_TTL_S)
    return _AUTH_URL + "?" + urlencode({
        "client_id": _client_id(), "redirect_uri": redirect_uri(), "response_type": "code", "scope": SCOPE,
        "access_type": "offline", "prompt": "consent", "include_granted_scopes": "false", "state": state})


async def _post_form(url: str, data: dict) -> dict:
    async with http_client.async_client(timeout=20) as client:
        resp = await client.post(url, data=data)
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if resp.status_code >= 400:
        raise GmailError(f"Google said: {body.get('error_description') or body.get('error') or resp.status_code}")
    return body


async def finish(state: str, code: str) -> str:
    """Complete the OAuth flow: store the account and return whose it is."""
    user_id, expires = _states.pop(state, (None, 0))
    if not user_id or expires < time.time():
        raise GmailError("That sign-in has expired. Connect Gmail again.")
    tokens = await _post_form(_TOKEN_URL, {"code": code, "client_id": _client_id(), "client_secret": _client_secret(),
                                           "redirect_uri": redirect_uri(), "grant_type": "authorization_code"})
    if SCOPE not in str(tokens.get("scope", "")).split():
        raise GmailError("Google didn't grant read access to Gmail. Connect again and allow it.")
    if not tokens.get("refresh_token"):
        raise GmailError("Google didn't give Windrush lasting access. Remove Windrush from your Google account's "
                         "third-party access, then connect again.")
    access = tokens["access_token"]
    profile = await _get(access, "/profile")
    tracker.save_gmail_account(user_id, str(profile.get("emailAddress") or ""), tokens["refresh_token"])
    _tokens[user_id] = (access, time.time() + int(tokens.get("expires_in", 3600)) - 60)
    return user_id


async def _access_token(user_id: str) -> str:
    cached = _tokens.get(user_id)
    if cached and cached[1] > time.time():
        return cached[0]
    account = tracker.get_gmail_account(user_id)
    if not account or not account["refresh_token"]:
        raise GmailError("Gmail isn't connected.")
    try:
        tokens = await _post_form(_TOKEN_URL, {"client_id": _client_id(), "client_secret": _client_secret(),
                                               "refresh_token": account["refresh_token"], "grant_type": "refresh_token"})
    except GmailError as exc:
        if "invalid_grant" in str(exc) or "expired" in str(exc).lower() or "revoked" in str(exc).lower():
            # Google ends a testing-mode app's access after 7 days, and whenever the user removes it.
            tracker.update_gmail_account(user_id, problem="Google ended Windrush's access to Gmail (it does this "
                                                          "every 7 days for apps in testing). Connect again.")
            raise GmailError("Google ended Windrush's access to Gmail. Connect again.") from exc
        raise
    _tokens[user_id] = (tokens["access_token"], time.time() + int(tokens.get("expires_in", 3600)) - 60)
    return tokens["access_token"]


async def disconnect(user_id: str) -> None:
    """Revoke Windrush's access at Google and forget the account (its email events stay)."""
    account = tracker.get_gmail_account(user_id)
    _tokens.pop(user_id, None)
    if account and account["refresh_token"]:
        try:
            await _post_form(_REVOKE_URL, {"token": account["refresh_token"]})
        except Exception as exc:
            logger.info("revoking the Gmail token failed (it may already be gone): %s", exc)
    tracker.delete_gmail_account(user_id)


async def _get(token: str, path: str, params: dict | None = None) -> dict:
    async with http_client.async_client(timeout=20) as client:
        resp = await client.get(_API + path, params=params, headers={"Authorization": f"Bearer {token}"})
    if resp.status_code == 401:
        raise GmailError("Gmail refused the request. Connect again.")
    resp.raise_for_status()
    return resp.json()


# ── Reading a message ─────────────────────────────────────────────────────────────────────────

def _header(payload: dict, name: str) -> str:
    return next((h.get("value", "") for h in payload.get("headers") or [] if h.get("name", "").lower() == name), "")


def _decode(data: str) -> str:
    try:
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")
    except Exception:
        return ""


def _text_of(payload: dict) -> str:
    """The message's text: its text/plain part, else its HTML with the tags taken out."""
    plain, rich = [], []

    def walk(part):
        mime, data = part.get("mimeType", ""), (part.get("body") or {}).get("data")
        if data and mime == "text/plain":
            plain.append(_decode(data))
        elif data and mime == "text/html":
            rich.append(_decode(data))
        for child in part.get("parts") or []:
            walk(child)
    walk(payload)
    if plain:
        return "\n".join(plain)
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", "\n".join(rich))
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", text)
    return html.unescape(re.sub(r"<[^>]+>", " ", text))


_QUOTE_START = re.compile(r"^(On .{5,200} wrote:|-{2,}\s*Original Message\s*-{2,}|From: .+)$", re.M)


def message_text(payload: dict) -> str:
    """The new part of a message (quoted replies cut off), tidied, at most _BODY_CHARS long."""
    text = _text_of(payload).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]{2,}", " ", line.strip()) for line in text.splitlines()]
    text = "\n".join(line for line in lines if not line.startswith(">"))
    cut = _QUOTE_START.search(text)
    if cut:
        text = text[:cut.start()]
    return re.sub(r"\n{3,}", "\n\n", text).strip()[:_BODY_CHARS]


def parse(message: dict) -> dict:
    payload = message.get("payload") or {}
    sender = _header(payload, "from")
    name, address = parseaddr(sender)
    received = datetime.fromtimestamp(int(message.get("internalDate", "0")) / 1000, tz=timezone.utc)
    return {"gmail_id": message["id"], "thread_id": message.get("threadId"), "received_at": received.isoformat(),
            "sender": sender, "sender_name": name, "sender_address": address.lower(),
            "subject": _header(payload, "subject"), "snippet": html.unescape(message.get("snippet") or ""),
            "text": message_text(payload)}


# ── Which application, and what it means ──────────────────────────────────────────────────────

_DOMAIN_SUFFIXES = {"careers", "career", "jobs", "job", "talent", "recruiting", "recruitment", "hr", "people", "hire",
                    "group", "global", "hq", "uk", "inc", "ltd", "sports", "tech", "mail", "team", "app", "io"}


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def names_company(email: dict, company: str) -> bool:
    """Whether the email names `company`: in the sender's name or address, the subject or the text."""
    norm = normalise_company_name(company or "")
    if not norm:
        return False
    words = " ".join(re.findall(r"[a-z0-9]+", f"{email['sender']} {email['subject']} {email['text']}".lower()))
    if re.search(rf"(?<![a-z0-9]){re.escape(norm)}(?![a-z0-9])", words):
        return True
    # The sender's own domain: catapult.com, catapultsports.com, catapultcareers.co.uk all name Catapult;
    # cambridgeconsultants.com doesn't name a company called Cambridge.
    name = _squash(norm)
    labels = email["sender_address"].split("@")[-1].split(".")
    return len(name) >= 3 and any(label == name or (label.startswith(name) and label[len(name):] in _DOMAIN_SUFFIXES)
                                  for label in labels)


def from_ats(email: dict) -> bool:
    domain = email["sender_address"].split("@")[-1]
    return any(domain == d or domain.endswith("." + d) for d in ATS_SENDERS)


def relevant(email: dict, applications: list[dict]) -> bool:
    """Worth reading at all: from an applicant tracking system, naming a company applied to, or with an
    application-style subject."""
    return (from_ats(email) or bool(_SUBJECT_RE.search(email["subject"]))
            or any(names_company(email, a["company"]) for a in applications))


_CLASSIFY_SYSTEM = (
    "You read one email a job seeker received and say what it means for their job applications. You never guess: "
    "you go by what the email plainly says.\n"
    "kind is one of:\n"
    "- received: it confirms their application was submitted or received;\n"
    "- assessment: it asks them to complete a test, coding challenge, online assessment, questionnaire or recorded "
    "video interview;\n"
    "- interview: it invites them to, or arranges, an interview, call or assessment centre with people;\n"
    "- offer: it offers them the job;\n"
    "- rejected: it says they won't be progressed, the role is filled or closed, or they were unsuccessful;\n"
    "- other: it's about one of their applications but none of the above (still under review, a question for them);\n"
    "- unrelated: anything else, including job alerts, job recommendations, newsletters and marketing.\n"
    "application is the number of the application it is about, from the list given, only when the email names "
    "that company (and, when they applied to several roles there, the role); otherwise null.\n"
    "confidence is high only when the email states its meaning outright and names the company; medium or low "
    "otherwise.\n"
    "summary is one short line in plain words, e.g. \"Invites you to a first interview on 21 October\".\n"
    'Return ONLY JSON: {"kind": str, "application": int | null, "confidence": "high" | "medium" | "low", '
    '"company": str, "role": str, "summary": str}'
)

_FALLBACK = (
    ("rejected", re.compile(r"unfortunately|regret to|not (?:be )?(?:moving|progressing) forward|other candidates|"
                            r"unsuccessful|position has been filled", re.I)),
    ("offer", re.compile(r"pleased to offer|offer letter|job offer", re.I)),
    ("interview", re.compile(r"\binterview\b|schedule a (?:call|chat)|your availability", re.I)),
    ("assessment", re.compile(r"assessment|coding challenge|hackerrank|codility|online test", re.I)),
    ("received", re.compile(r"received your application|thank you for (?:applying|your application)|"
                            r"application (?:has been|was) (?:received|submitted)", re.I)),
)


def _numbered(applications: list[dict]) -> str:
    return "\n".join(f"{n}. {a['company']} - {a['job_title']} (status: {a['status']})"
                     for n, a in enumerate(applications, 1))


async def read(email: dict, applications: list[dict]) -> dict:
    """{kind, application (dict | None), confidence, company, role, summary} for one email. The model's match is
    kept only when the email names that application's company."""
    user = (f"Their applications:\n{_numbered(applications) or '(none)'}\n\n"
            f"Email from: {email['sender']}\nSubject: {email['subject']}\nReceived: {email['received_at'][:10]}\n\n"
            f"{email['text'] or email['snippet']}")
    data = None
    try:
        data = await agent._llm_json(_CLASSIFY_SYSTEM, user, max_tokens=400, label="email_read")
    except Exception as exc:
        logger.warning("reading an email failed: %s", type(exc).__name__)
    if data is None:
        return _read_without_model(email, applications)
    kind = data.get("kind") if data.get("kind") in KIND_STATUS or data.get("kind") in ("other", "unrelated") else "other"
    n = data.get("application")
    app = applications[n - 1] if isinstance(n, int) and 1 <= n <= len(applications) else None
    if app and not names_company(email, app["company"]):
        app = None
    confidence = data.get("confidence") if data.get("confidence") in ("high", "medium", "low") else "low"
    return {"kind": kind, "application": app, "confidence": confidence,
            "company": str(data.get("company") or (app or {}).get("company") or "")[:200],
            "role": str(data.get("role") or "")[:200], "summary": str(data.get("summary") or "")[:300]}


def _read_without_model(email: dict, applications: list[dict]) -> dict:
    """When the model can't be reached: a keyword reading, never confident enough to change anything by itself."""
    text = f"{email['subject']}\n{email['text']}"
    kind = next((k for k, pattern in _FALLBACK if pattern.search(text)), "other")
    named = [a for a in applications if names_company(email, a["company"])]
    app = named[0] if len({a["company"].lower() for a in named}) == 1 and len(named) == 1 else None
    return {"kind": kind, "application": app, "confidence": "low", "company": (app or {}).get("company", ""),
            "role": "", "summary": email["subject"][:300]}


def proposed_change(current: str, kind: str) -> tuple[str | None, bool]:
    """(the status an email of `kind` points to, whether it may be set without asking), or (None, False) when it
    changes nothing. Only a step forward is automatic: never one that goes back, revives a rejected application,
    touches one the user discarded, or overrides an offer."""
    target = KIND_STATUS.get(kind)
    if not target or target == current:
        return None, False
    if current in ("Discarded", "Rejected"):
        return target, False
    if target == "Rejected":
        return target, current != "Offer"
    if current not in _RANK:
        return target, False
    return (target, True) if _RANK[target] > _RANK[current] else (None, False)


# ── Syncing ───────────────────────────────────────────────────────────────────────────────────

def _query(after: int, companies: list[str]) -> str:
    terms = ["from:(" + " OR ".join(ATS_SENDERS) + ")", "subject:(" + " OR ".join(_SUBJECT_TERMS) + ")"]
    terms += ['"' + c.replace('"', "") + '"' for c in companies[:40]]
    return f"after:{after} -in:sent -in:chats -category:promotions -category:social ({' OR '.join(terms)})"


def _first_sync_start(applications: list[dict]) -> int:
    floor = int(time.time()) - _FIRST_SYNC_DAYS * 86400
    dates = [a.get("created_at") for a in applications if a.get("created_at")]
    try:
        earliest = int(min(datetime.fromisoformat(d) for d in dates).timestamp()) - 86400 if dates else floor
    except ValueError:
        earliest = floor
    return max(floor, earliest)


async def _message_ids(token: str, query: str) -> list[str]:
    ids, page = [], None
    while len(ids) < _MAX_MESSAGES:
        params = {"q": query, "maxResults": min(100, _MAX_MESSAGES - len(ids))}
        if page:
            params["pageToken"] = page
        listing = await _get(token, "/messages", params)
        ids += [m["id"] for m in listing.get("messages") or []]
        page = listing.get("nextPageToken")
        if not page:
            break
    return ids


def _apply(user_id: str, email: dict, reading: dict) -> str:
    """Record what an email means, and change the application's status when that is safe. Returns the decision."""
    event = {**{k: email[k] for k in ("gmail_id", "thread_id", "received_at", "sender", "subject")},
             "snippet": email["snippet"][:300], "kind": reading["kind"], "company": reading["company"],
             "role": reading["role"], "summary": reading["summary"]}
    if reading["kind"] == "unrelated":
        # Nothing of an unrelated email is kept but the fact it was read.
        tracker.add_email_event(user_id, {"gmail_id": email["gmail_id"], "received_at": email["received_at"],
                                          "sender": "", "subject": "", "kind": "unrelated", "decision": "ignored"})
        return "ignored"
    app = reading["application"]
    if app is None:
        tracker.add_email_event(user_id, {**event, "decision": "unmatched", "proposed": KIND_STATUS.get(reading["kind"])})
        return "unmatched"
    current = (tracker.get_application(user_id, app["id"]) or app)["status"]
    target, safe = proposed_change(current, reading["kind"])
    if target is None:
        decision = "noted"
    elif safe and reading["confidence"] == "high":
        tracker.update_status(app["id"], target, user_id=user_id)
        decision = "applied"
    else:
        decision = "suggested"
    tracker.add_email_event(user_id, {**event, "application_id": app["id"], "proposed": target, "decision": decision,
                                      "status_before": current})
    return decision


_syncing: set[str] = set()
_last: dict[str, dict] = {}


async def sync(user_id: str) -> dict:
    """Read the job emails that arrived since the last sync and act on them. Returns counts by decision."""
    account = tracker.get_gmail_account(user_id)
    if not account:
        raise GmailError("Gmail isn't connected.")
    if account.get("problem"):
        raise GmailError(account["problem"])
    if user_id in _syncing:
        return {"note": "A sync is already running."}
    _syncing.add(user_id)
    counts: dict[str, int] = {}
    try:
        token = await _access_token(user_id)
        applications = tracker.list_applications(user_id)[:_MAX_APPLICATIONS]
        started = int(time.time())
        after = account.get("synced_until") or _first_sync_start(applications)
        companies = list(dict.fromkeys(a["company"] for a in applications if a.get("company")))
        ids = [i for i in await _message_ids(token, _query(after, companies)) if not tracker.email_seen(user_id, i)]
        emails = []
        for message_id in ids:
            emails.append(parse(await _get(token, f"/messages/{message_id}", {"format": "full"})))
        for email in sorted(emails, key=lambda e: e["received_at"]):   # oldest first: later news wins
            if not relevant(email, applications):
                decision = "ignored"
                tracker.add_email_event(user_id, {"gmail_id": email["gmail_id"], "received_at": email["received_at"],
                                                  "sender": "", "subject": "", "kind": "unrelated", "decision": "ignored"})
            else:
                decision = _apply(user_id, email, await read(email, applications))
                applications = tracker.list_applications(user_id)[:_MAX_APPLICATIONS]   # statuses may have moved
            counts[decision] = counts.get(decision, 0) + 1
        tracker.update_gmail_account(user_id, synced_until=started - _OVERLAP_S,
                                     last_sync_at=datetime.now(timezone.utc).isoformat())
        logger.info("gmail sync: %d messages read, %s", len(emails), counts)
        return {"counts": counts}
    finally:
        _syncing.discard(user_id)
        _last[user_id] = {"finished_at": datetime.now(timezone.utc).isoformat(), "counts": counts}


def start_sync(user_id: str) -> bool:
    if user_id in _syncing:
        return False

    async def go():
        try:
            await sync(user_id)
        except GmailError as exc:
            _last[user_id] = {"finished_at": datetime.now(timezone.utc).isoformat(), "counts": {}, "error": str(exc)}
        except Exception:
            logger.exception("gmail sync failed")
    asyncio.create_task(go())
    return True


def status(user_id: str) -> dict:
    account = tracker.get_gmail_account(user_id)
    return {"configured": configured(), "connected": bool(account), "email": (account or {}).get("email"),
            "problem": (account or {}).get("problem"), "last_sync_at": (account or {}).get("last_sync_at"),
            "syncing": user_id in _syncing, "last": _last.get(user_id), "redirect_uri": redirect_uri()}


# ── What the user does with an email ──────────────────────────────────────────────────────────

def confirm(user_id: str, event_id: str, application_id: str | None = None) -> dict:
    """Make the change an email points to (on `application_id` when the user links an unmatched one)."""
    event = tracker.get_email_event(user_id, event_id)
    if not event:
        raise LookupError("No such email")
    if event["decision"] not in ("suggested", "unmatched", "noted", "dismissed"):
        raise GmailError("That email has already been dealt with.")
    app = tracker.get_application(user_id, application_id or event["application_id"] or "")
    if not app:
        raise GmailError("Choose which application this email is about.")
    target = KIND_STATUS.get(event["kind"])
    if target and target != app["status"]:
        tracker.update_status(app["id"], target, user_id=user_id)
    tracker.update_email_event(user_id, event_id, decision="confirmed", application_id=app["id"],
                               proposed=target, status_before=app["status"])
    return tracker.get_email_event(user_id, event_id)


def dismiss(user_id: str, event_id: str) -> None:
    event = tracker.get_email_event(user_id, event_id)
    if not event:
        raise LookupError("No such email")
    if event["decision"] not in ("suggested", "unmatched", "noted"):
        raise GmailError("That email has already been dealt with.")
    tracker.update_email_event(user_id, event_id, decision="dismissed")


def undo(user_id: str, event_id: str) -> dict:
    """Put the application back to where it was before this email changed it."""
    event = tracker.get_email_event(user_id, event_id)
    if not event:
        raise LookupError("No such email")
    if event["decision"] not in ("applied", "confirmed") or not event["application_id"] or not event["status_before"]:
        raise GmailError("There's nothing to undo for that email.")
    app = tracker.get_application(user_id, event["application_id"])
    if not app:
        raise GmailError("That application no longer exists.")
    if event["proposed"] and app["status"] != event["proposed"]:
        raise GmailError(f"It has moved on since (it's now {app['status']}): change it on the board instead.")
    tracker.update_status(app["id"], event["status_before"], user_id=user_id)
    tracker.update_email_event(user_id, event_id, decision="undone")
    return tracker.get_email_event(user_id, event_id)


async def keep_syncing() -> None:
    """Sync every connected account every 30 minutes."""
    while True:
        await asyncio.sleep(_EVERY_S)
        if not configured():
            continue
        for user_id in tracker.gmail_users():
            try:
                await sync(user_id)
            except GmailError as exc:
                logger.info("gmail sync skipped: %s", exc)
            except Exception:
                logger.exception("gmail sync failed")
