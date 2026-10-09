"""The job-site password: encrypted at rest, write-only over the API, handed only to the browser agent."""
import json
import sqlite3

from cryptography.fernet import Fernet

from app import crypto, main, net_guard, tracker, agent

SECRET = "hunter2-Sup3rSecret"
MASK = main.JOB_PASSWORD_MASK


def _put(client, password):
    return client.put("/persona", json={"core_info": {"first_name": "Ada", "job_email": "a@x.com",
                                                      "job_password": password}})


def test_encrypt_round_trip_hides_plaintext():
    token = crypto.encrypt(SECRET)
    assert SECRET not in token and crypto.decrypt(token) == SECRET


def test_token_from_another_key_decrypts_to_empty():
    assert crypto.decrypt(Fernet(Fernet.generate_key()).encrypt(b"x").decode()) == ""


def test_legacy_plaintext_password_is_migrated(tmp_path):
    path = str(tmp_path / "legacy.db")
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,"
                " persona TEXT DEFAULT '{}', onboarding_complete INTEGER DEFAULT 0, created_at TEXT NOT NULL)")
    con.execute("INSERT INTO users VALUES ('legacy', 'l@x.com', 'h', ?, 1, 'now')",
                (json.dumps({"core_info": {"first_name": "Leg", "job_password": SECRET}}),))
    con.commit()
    con.close()

    tracker.init_db(path)

    persona_json, enc = sqlite3.connect(path).execute(
        "SELECT persona, job_password_enc FROM users WHERE id='legacy'").fetchone()
    assert "job_password" not in persona_json and SECRET not in persona_json
    assert json.loads(persona_json)["core_info"]["first_name"] == "Leg"
    assert enc and SECRET not in enc and tracker.get_job_password("legacy") == SECRET


def test_get_returns_mask_and_put_semantics(client, user):
    assert _put(client, SECRET).status_code == 200
    assert client.get("/persona").json()["core_info"]["job_password"] == MASK
    assert tracker.get_job_password(user) == SECRET

    _put(client, MASK)                      # the mask means "unchanged"
    assert tracker.get_job_password(user) == SECRET

    _put(client, "")                        # empty means "clear"
    assert tracker.get_job_password(user) == ""
    assert client.get("/persona").json()["core_info"]["job_password"] == ""


def test_password_is_nowhere_in_plaintext_at_rest_or_in_exports(client, db):
    _put(client, SECRET)
    blob = b"".join(p.read_bytes() for p in db.glob("applications.db*"))
    assert SECRET.encode() not in blob
    export = client.get("/persona/export?format=json")
    assert export.status_code == 200 and SECRET not in export.text and MASK not in export.text


def test_apply_hands_the_stored_password_to_the_agent(client, monkeypatch):
    _put(client, SECRET)
    captured = {}

    async def fake_run_apply(*args, **kwargs):
        captured.update(kwargs)
        yield agent._sse("done", {"message": "Done", "submitted": False})

    async def public(url):
        return None

    monkeypatch.setattr(main, "run_apply", fake_run_apply)
    monkeypatch.setattr(net_guard, "assert_public_url", public)
    client.post("/apply", data={"job_id": "j", "job_title": "T", "company": "C", "job_url": "https://jobs.example.com/1"})
    assert captured["job_password"] == SECRET
