"""Signing in: how long the token the browser keeps lasts."""
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from jose import jwt

from app import auth, main, tracker


def test_a_login_lasts_a_week_not_a_quarter_of_an_hour(db):
    tracker.create_user("ada@example.com", auth.get_password_hash("correct horse"))
    client = TestClient(main.app)
    token = client.post("/login", data={"username": "ada@example.com", "password": "correct horse"}).json()["access_token"]
    expires = jwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])["exp"]
    days = (datetime.fromtimestamp(expires, timezone.utc) - datetime.now(timezone.utc)).total_seconds() / 86400
    assert 6.99 < days <= 7                                   # not the 15-minute default that logged people out
    assert client.get("/persona", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_a_wrong_password_gets_no_token(db):
    tracker.create_user("ada@example.com", auth.get_password_hash("correct horse"))
    reply = TestClient(main.app).post("/login", data={"username": "ada@example.com", "password": "wrong"})
    assert reply.status_code == 401 and "access_token" not in reply.json()
