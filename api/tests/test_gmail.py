"""Gmail tracking: connecting (read-only), reading job emails, and what they change on the applications."""
import asyncio
import base64
import sqlite3
import time
from urllib.parse import parse_qs, urlparse

import pytest

from app import agent, gmail, tracker


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def message(mid: str, sender: str, subject: str, body: str, minutes_ago: int = 60, html: bool = False) -> dict:
    return {"id": mid, "threadId": f"t{mid}", "internalDate": str(int((time.time() - minutes_ago * 60) * 1000)),
            "snippet": body[:80],
            "payload": {"mimeType": "multipart/alternative",
                        "headers": [{"name": "From", "value": sender}, {"name": "Subject", "value": subject}],
                        "parts": [{"mimeType": "text/html" if html else "text/plain", "body": {"data": _b64(body)}}]}}


class FakeGoogle:
    def __init__(self):
        self.messages: dict[str, dict] = {}
        self.queries: list[str] = []
        self.revoked: list[str] = []
        self.refresh_error = ""
        self.scope = gmail.SCOPE
        self.slow_down: set[str] = set()     # paths that get Gmail's quota error once

    async def post_form(self, url, data):
        if url == gmail._REVOKE_URL:
            self.revoked.append(data["token"])
            return {}
        if data["grant_type"] == "authorization_code":
            assert data["code"] == "good-code"
            return {"access_token": "at-1", "refresh_token": "rt-secret", "expires_in": 3600, "scope": self.scope}
        if self.refresh_error:
            raise gmail.GmailError(f"Google said: {self.refresh_error}")
        return {"access_token": "at-2", "expires_in": 3600}

    async def get(self, token, path, params=None):
        if path in self.slow_down:
            self.slow_down.discard(path)
            raise gmail._SlowDown()
        if path == "/profile":
            return {"emailAddress": "ada@gmail.com"}
        if path == "/messages":
            self.queries.append(params["q"])
            return {"messages": [{"id": m} for m in self.messages]}
        return self.messages[path.rsplit("/", 1)[1]]


@pytest.fixture
def google(db, monkeypatch):
    fake = FakeGoogle()
    monkeypatch.setattr(gmail, "_FETCH_GAP_S", 0)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(gmail, "_post_form", fake.post_form)
    monkeypatch.setattr(gmail, "_get", fake.get)
    gmail._tokens.clear()
    gmail._states.clear()
    gmail._syncing.clear()
    return fake


@pytest.fixture
def readings(monkeypatch):
    """subject → the model's reading of that email (a dict), or None for a model that can't be reached."""
    by_subject: dict[str, dict | None] = {}

    async def llm_json(system, user, max_tokens=2048, label=""):
        subject = next(line[9:] for line in user.splitlines() if line.startswith("Subject: "))
        return by_subject.get(subject)
    monkeypatch.setattr(agent, "_llm_json", llm_json)
    return by_subject


def _app(uid, company, title, status):
    return tracker.add_application(uid, {"job_id": company, "title": title, "company": company}, {}, "", {},
                                   status=status)


def _connect(client) -> None:
    url = client.get("/gmail/connect").json()["url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    resp = client.get(f"/gmail/callback?state={state}&code=good-code", follow_redirects=False)
    assert resp.headers["location"] == "/inbox?gmail=connected"


def _status(uid, app_id):
    return tracker.get_application(uid, app_id)["status"]


# ── Connecting ────────────────────────────────────────────────────────────────

def test_not_set_up_says_so(db, client, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    assert client.get("/gmail").json()["configured"] is False
    assert "GOOGLE_CLIENT_ID" in client.get("/gmail/connect").json()["detail"]


def test_connecting_asks_only_for_read_access_and_stores_the_token_encrypted(google, client, user, monkeypatch):
    monkeypatch.setattr(gmail, "start_sync", lambda uid: True)
    url = client.get("/gmail/connect").json()["url"]
    query = parse_qs(urlparse(url).query)
    assert query["scope"] == ["https://www.googleapis.com/auth/gmail.readonly"]
    assert query["access_type"] == ["offline"] and query["redirect_uri"] == ["http://localhost/api/gmail/callback"]

    bad = client.get("/gmail/callback?state=forged&code=good-code", follow_redirects=False)
    assert bad.headers["location"].startswith("/inbox?gmail=error") and tracker.get_gmail_account(user) is None
    _connect(client)
    status = client.get("/gmail").json()
    assert status["connected"] and status["email"] == "ada@gmail.com"
    con = sqlite3.connect(tracker._DB_PATH)
    stored = con.execute("SELECT refresh_token_enc FROM gmail_accounts").fetchone()[0]
    con.close()
    assert "rt-secret" not in stored and tracker.get_gmail_account(user)["refresh_token"] == "rt-secret"


def test_a_grant_without_gmail_read_access_is_refused(google, client, user):
    google.scope = "openid email"
    url = client.get("/gmail/connect").json()["url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    resp = client.get(f"/gmail/callback?state={state}&code=good-code", follow_redirects=False)
    assert "gmail=error" in resp.headers["location"] and tracker.get_gmail_account(user) is None


def test_declining_on_googles_page_comes_back_as_an_error(google, client):
    resp = client.get("/gmail/callback?error=access_denied&state=x", follow_redirects=False)
    assert resp.headers["location"].startswith("/inbox?gmail=error&reason=You%20didn")


def test_disconnecting_revokes_access(google, client, user, monkeypatch):
    monkeypatch.setattr(gmail, "start_sync", lambda uid: True)
    _connect(client)
    assert client.delete("/gmail").json() == {"connected": False}
    assert google.revoked == ["rt-secret"] and tracker.get_gmail_account(user) is None


def test_google_ending_access_asks_to_connect_again(google, client, user, monkeypatch):
    monkeypatch.setattr(gmail, "start_sync", lambda uid: True)
    _connect(client)
    gmail._tokens.clear()
    google.refresh_error = "invalid_grant"
    with pytest.raises(gmail.GmailError):
        asyncio.run(gmail.sync(user))
    assert "every 7 days" in client.get("/gmail").json()["problem"]
    assert client.post("/gmail/sync").status_code == 400
    assert user not in tracker.gmail_users()


# ── Syncing ───────────────────────────────────────────────────────────────────

@pytest.fixture
def inbox(google, readings, client, user, monkeypatch):
    monkeypatch.setattr(gmail, "start_sync", lambda uid: True)
    _connect(client)
    apps = {"catapult": _app(user, "Catapult", "Graduate Software Engineer", "Applied"),
            "cambridge": _app(user, "Cambridge Consultants", "Graduate Cloud Engineer", "Pending Review"),
            "dv": _app(user, "DV Trading", "Graduate Software Engineer", "Interview"),
            "acme": _app(user, "Acme", "Junior Developer", "Discarded")}

    def mail(mid, sender, subject, body, reading=None, minutes_ago=60):
        google.messages[mid] = message(mid, sender, subject, body, minutes_ago)
        readings[subject] = reading
    return apps, mail


def _reading(kind, n, confidence="high", summary="", company=""):
    return {"kind": kind, "application": n, "confidence": confidence, "company": company, "role": "", "summary": summary}


def test_clear_news_moves_applications_forward_and_the_rest_waits(inbox, client, user, google):
    apps, mail = inbox
    order = [a["id"] for a in tracker.list_applications(user)]        # how they're numbered for the model
    n = lambda key: order.index(apps[key]) + 1                          # noqa: E731
    mail("m1", "Catapult Talent <no-reply@greenhouse.io>", "Interview invitation - Catapult",
         "Hi Ada, we'd like to invite you to interview for Graduate Software Engineer at Catapult.",
         _reading("interview", n("catapult"), summary="Invites you to a first interview"))
    mail("m2", "Cambridge Consultants <careers@cambridgeconsultants.com>", "Thank you for applying",
         "We have received your application.", _reading("received", n("cambridge")))
    mail("m3", "DV Trading <jobs@dvtrading.co>", "Your application", "Unfortunately we won't be moving forward.",
         _reading("rejected", n("dv")))
    mail("m4", "Acme Recruiting <talent@acme.com>", "Interview at Acme", "We'd like to interview you at Acme.",
         _reading("interview", n("acme")))
    mail("m5", "LinkedIn Job Alerts <jobs-noreply@linkedin.com>", "New jobs for you: Software Engineer",
         "30 new jobs match your preferences.", _reading("unrelated", None))
    mail("m6", "Globex <careers@globex.com>", "Your application to Globex", "Unfortunately we have decided not to "
         "progress your application.", _reading("rejected", None, company="Globex"))
    mail("m7", "Recruiter <hello@agency.io>", "Interview opportunity", "A great interview opportunity for you.",
         _reading("interview", n("catapult")))           # the model's match, but the email never names Catapult
    asyncio.run(gmail.sync(user))

    assert _status(user, apps["catapult"]) == "Interview"
    assert _status(user, apps["cambridge"]) == "Applied"
    assert _status(user, apps["dv"]) == "Rejected"
    assert _status(user, apps["acme"]) == "Discarded"             # discarded: never changed by itself
    events = {e["gmail_id"]: e for e in client.get("/gmail/events").json()}
    assert {k: e["decision"] for k, e in events.items()} == {
        "m1": "applied", "m2": "applied", "m3": "applied", "m4": "suggested", "m6": "unmatched", "m7": "unmatched"}
    assert events["m1"]["summary"] == "Invites you to a first interview" and events["m1"]["status_before"] == "Applied"
    assert events["m4"]["proposed"] == "Interview" and events["m6"]["proposed"] == "Rejected"

    # The job alert left nothing of its content, and isn't listed.
    con = sqlite3.connect(tracker._DB_PATH)
    assert con.execute("SELECT sender, subject, snippet, decision FROM email_events WHERE gmail_id='m5'").fetchone() == \
        ("", "", "", "ignored")
    con.close()
    # The search asked Gmail only for likely job mail, and never sent mail or promotions.
    assert "-in:sent" in google.queries[0] and "-category:promotions" in google.queries[0]
    assert "greenhouse.io" in google.queries[0] and '"Catapult"' in google.queries[0]

    # A second sync doesn't read them again.
    asyncio.run(gmail.sync(user))
    assert len(client.get("/gmail/events").json()) == 6


def test_unsure_or_backward_news_is_only_suggested(inbox, user, client):
    apps, mail = inbox
    order = [a["id"] for a in tracker.list_applications(user)]
    n = lambda key: order.index(apps[key]) + 1                          # noqa: E731
    mail("m1", "Catapult <jobs@catapult.com>", "Catapult: next steps", "Catapult would like to set up a call.",
         _reading("interview", n("catapult"), confidence="medium"))
    mail("m2", "DV Trading <jobs@dvtrading.co>", "Application received - DV Trading", "Thanks for applying to DV Trading.",
         _reading("received", n("dv")))                   # it's at Interview already: an old confirmation
    asyncio.run(gmail.sync(user))
    events = {e["gmail_id"]: e for e in client.get("/gmail/events").json()}
    assert events["m1"]["decision"] == "suggested" and _status(user, apps["catapult"]) == "Applied"
    assert events["m2"]["decision"] == "noted" and _status(user, apps["dv"]) == "Interview"


def test_without_the_model_nothing_changes_by_itself(inbox, user, client):
    apps, mail = inbox
    mail("m1", "Catapult <jobs@catapult.com>", "Catapult update", "Unfortunately we will not be moving forward.", None)
    asyncio.run(gmail.sync(user))
    event = client.get("/gmail/events").json()[0]
    assert (event["kind"], event["decision"], event["application_id"]) == ("rejected", "suggested", apps["catapult"])
    assert _status(user, apps["catapult"]) == "Applied"


# ── What the user does ────────────────────────────────────────────────────────

def test_undo_confirm_link_and_dismiss(inbox, user, client, make_user, client_for):
    apps, mail = inbox
    order = [a["id"] for a in tracker.list_applications(user)]
    n = lambda key: order.index(apps[key]) + 1                          # noqa: E731
    mail("m1", "Catapult <jobs@catapult.com>", "Interview - Catapult", "Catapult invites you to interview.",
         _reading("interview", n("catapult")))
    mail("m2", "Acme <talent@acme.com>", "Interview at Acme", "Acme would like to interview you.",
         _reading("interview", n("acme")))
    mail("m3", "Globex <careers@globex.com>", "Offer from Globex", "We are pleased to offer you the role.",
         _reading("offer", None))
    mail("m4", "Initech <jobs@initech.com>", "Your application", "Initech is reviewing your application.",
         _reading("other", None))
    asyncio.run(gmail.sync(user))
    ev = {e["gmail_id"]: e["id"] for e in client.get("/gmail/events").json()}

    # Undo puts it back; a second undo has nothing to do.
    assert client.post(f"/gmail/events/{ev['m1']}/undo").json()["decision"] == "undone"
    assert _status(user, apps["catapult"]) == "Applied"
    assert client.post(f"/gmail/events/{ev['m1']}/undo").status_code == 400

    # Confirming a suggestion makes the change.
    assert client.post(f"/gmail/events/{ev['m2']}/confirm", json={}).json()["decision"] == "confirmed"
    assert _status(user, apps["acme"]) == "Interview"
    # An unmatched email needs the application it's about.
    assert client.post(f"/gmail/events/{ev['m3']}/confirm", json={}).status_code == 400
    linked = client.post(f"/gmail/events/{ev['m3']}/confirm", json={"application_id": apps["cambridge"]}).json()
    assert linked["application_id"] == apps["cambridge"] and _status(user, apps["cambridge"]) == "Offer"
    # An undo after the application moved on is refused.
    tracker.update_status(apps["cambridge"], "Rejected", user_id=user)
    assert "moved on" in client.post(f"/gmail/events/{ev['m3']}/undo").json()["detail"]

    assert client.post(f"/gmail/events/{ev['m4']}/dismiss").json() == {"dismissed": ev["m4"]}
    assert client.post(f"/gmail/events/{ev['m4']}/dismiss").status_code == 400

    other = client_for(make_user("eve@example.com"))
    assert other.get("/gmail/events").json() == []
    assert other.post(f"/gmail/events/{ev['m2']}/undo").status_code == 404
    # Eve can't link Ada's email to her own application, or Ada's application to her email.
    assert other.post(f"/gmail/events/{ev['m3']}/confirm", json={}).status_code == 404


# ── Reading ───────────────────────────────────────────────────────────────────

def test_message_text_drops_html_and_quoted_replies():
    body = ("<html><style>p{}</style><p>Hi Ada,</p><p>We&rsquo;d like to invite you&nbsp;to interview.</p>"
            "<div>On Mon, 1 Oct 2026 at 09:00 Ada &lt;ada@gmail.com&gt; wrote:</div><p>&gt; my application</p></html>")
    text = gmail.parse(message("x", "a@b.com", "s", body, html=True))["text"]
    assert "We’d like to invite you to interview." in text and "my application" not in text and "p{}" not in text


def test_a_company_is_named_by_words_or_by_the_sender_domain():
    email = {"sender": "Careers <careers@cambridgeconsultants.com>", "sender_address": "careers@cambridgeconsultants.com",
             "subject": "Your application", "text": "Thanks for applying."}
    assert gmail.names_company(email, "Cambridge Consultants Ltd")
    assert not gmail.names_company(email, "Cambridge")       # 'cambridge' is in the domain, but too loosely
    assert gmail.names_company({**email, "text": "Thanks for applying to Cambridge."}, "Cambridge")
    assert not gmail.names_company({**email, "text": "the catapults"}, "Catapult")


@pytest.mark.parametrize("current, kind, expected", [
    ("Applied", "interview", ("Interview", True)),
    ("Pending Review", "received", ("Applied", True)),
    ("Interview", "received", (None, False)),
    ("Interview", "rejected", ("Rejected", True)),
    ("Offer", "rejected", ("Rejected", False)),
    ("Rejected", "interview", ("Interview", False)),
    ("Discarded", "offer", ("Offer", False)),
    ("Applied", "other", (None, False)),
])
def test_only_steps_forward_are_automatic(current, kind, expected):
    assert gmail.proposed_change(current, kind) == expected


# ── Looking back, catching up, and adding what isn't tracked ──────────────────

def test_the_first_sync_reads_back_sixty_days_whatever_is_tracked(inbox, user, google):
    asyncio.run(gmail.sync(user))
    after = int(google.queries[0].split("after:")[1].split()[0])
    assert abs(after - (time.time() - 60 * 86400)) < 120


def test_a_backlog_is_read_oldest_first_over_several_syncs(inbox, user, google, monkeypatch):
    apps, mail = inbox
    monkeypatch.setattr(gmail, "_MAX_MESSAGES", 2)
    for i, minutes in enumerate((10, 20, 30, 40, 50)):       # newest first, as Gmail lists them
        mail(f"b{i}", "Initech <jobs@initech.com>", f"Your application to Initech ({i})", "About your application.",
             _reading("other", None), minutes_ago=minutes)
    first = asyncio.run(gmail.sync(user))
    assert first["counts"]["waiting"] == 3
    read = {e["gmail_id"] for e in tracker.list_email_events(user)}
    assert read == {"b4", "b3"}                               # the two oldest
    start = tracker.get_gmail_account(user)["synced_until"]
    asyncio.run(gmail.sync(user))
    asyncio.run(gmail.sync(user))
    assert {e["gmail_id"] for e in tracker.list_email_events(user)} == {f"b{i}" for i in range(5)}
    assert google.queries[1].split()[0] == f"after:{start}" and tracker.get_gmail_account(user)["synced_until"] > start


def test_an_email_about_an_untracked_application_can_be_added(inbox, user, client, make_user, client_for):
    apps, mail = inbox
    mail("u1", "Globex Careers <careers@globex.com>", "Interview invitation - Globex",
         "We'd like to invite you to interview for Graduate Data Engineer at Globex.",
         _reading("interview", None, company="Globex"))
    asyncio.run(gmail.sync(user))
    event = client.get("/gmail/events").json()[0]
    assert event["decision"] == "unmatched"
    assert client.post(f"/gmail/events/{event['id']}/track", json={"company": "Globex", "role": " "}).status_code == 400

    added = client.post(f"/gmail/events/{event['id']}/track",
                        json={"company": "Globex", "role": "Graduate Data Engineer"}).json()
    assert added["decision"] == "confirmed" and added["proposed"] == "Interview"
    app = tracker.get_application(user, added["application_id"])
    assert (app["company"], app["job_title"], app["status"]) == ("Globex", "Graduate Data Engineer", "Interview")
    assert client.post(f"/gmail/events/{event['id']}/track",
                       json={"company": "Globex", "role": "Graduate Data Engineer"}).status_code == 400
    other = client_for(make_user("eve@example.com"))           # (the shared test client is Eve's from here)
    assert other.post(f"/gmail/events/{event['id']}/track", json={"company": "Globex", "role": "x"}).status_code == 404


def test_googles_one_time_code_stays_out_of_the_access_log():
    import logging
    from app import main
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                               ("1.2.3.4:5", "GET", "/gmail/callback?state=abc&iss=x&code=4/0SECRET&scope=y", "1.1",
                                303), None)
    main._HideOAuthCode().filter(record)
    line = record.getMessage()
    assert "SECRET" not in line and "abc" not in line and "code=<hidden>" in line and "scope=y" in line


def test_gmails_quota_pauses_a_sync_and_the_next_one_carries_on(inbox, user, google):
    apps, mail = inbox
    for i, minutes in enumerate((10, 20, 30)):
        mail(f"q{i}", "Initech <jobs@initech.com>", f"Your application to Initech ({i})", "About your application.",
             _reading("other", None), minutes_ago=minutes)
    google.slow_down.add("/messages/q1")                    # the second oldest hits the quota
    first = asyncio.run(gmail.sync(user))
    assert first["counts"] == {"unmatched": 1, "waiting": 2}
    asyncio.run(gmail.sync(user))
    assert {e["gmail_id"] for e in tracker.list_email_events(user)} == {"q0", "q1", "q2"}
