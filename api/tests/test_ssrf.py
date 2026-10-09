"""Server-side fetches of user-influenced URLs must never reach internal addresses."""
import asyncio
import socket
import sqlite3

import httpx
import pytest

from app import job_searcher, jobs_db, main, net_guard

PUBLIC_IP = "93.184.216.34"


@pytest.fixture
def fake_dns(monkeypatch):
    """Resolve *.example.com to a public IP offline; everything else resolves for real."""
    real = socket.getaddrinfo

    def getaddrinfo(host, port, *args, **kwargs):
        if host == "example.com" or str(host).endswith(".example.com"):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_IP, port))]
        return real(host, port, *args, **kwargs)
    monkeypatch.setattr(net_guard.socket, "getaddrinfo", getaddrinfo)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://localhost:11434/", "http://10.1.2.3/", "http://172.18.0.5/",
    "http://192.168.1.1/", "http://169.254.169.254/latest/meta-data", "http://[::1]/",
    "http://[::ffff:127.0.0.1]/", "http://0.0.0.0/", "http://100.64.0.1/",
    "file:///etc/passwd", "ftp://example.com/", "http://no-such-host.invalid/",
])
def test_guard_blocks(url):
    with pytest.raises(net_guard.UnsafeURLError):
        net_guard.check_public_url(url)


def test_guard_allows_public_https(fake_dns):
    net_guard.check_public_url("https://jobs.example.com/123")


def test_redirect_to_internal_address_is_blocked(fake_dns):
    def handler(request: httpx.Request):
        if request.url.host == "example.com":
            return httpx.Response(302, headers={"location": "http://127.0.0.1:11434/api/tags"})
        return httpx.Response(200, text="INTERNAL")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            await net_guard.safe_get(c, "https://example.com/job")

    with pytest.raises(net_guard.UnsafeURLError):
        asyncio.run(run())


def test_description_fetch_refuses_internal_urls():
    assert asyncio.run(job_searcher.fetch_full_description("http://169.254.169.254/x")) == ""


def test_pasted_internal_link_is_400(client):
    r = client.post("/jobs/from-url", json={"url": "http://127.0.0.1:8000/health"})
    assert r.status_code == 400


@pytest.mark.parametrize("bad", ["http://127.0.0.1:8000/health", "http://169.254.169.254/latest", "file:///etc/passwd"])
def test_apply_rejects_internal_job_urls(client, bad):
    r = client.post("/apply", data={"job_id": "j", "job_title": "T", "company": "C", "job_url": bad})
    assert r.status_code == 400


def _seed_job(url="https://jobs.example.com/real"):
    con = sqlite3.connect(jobs_db._DB_PATH)
    con.execute("INSERT INTO jobs (id, job_id, title, company, normalized_company, location, description, url, created_at)"
                " VALUES ('victim', 'v', 'SWE', 'Acme', 'acme', 'London', 'short', ?, 'now')", (url,))
    con.commit()
    con.close()


def test_shared_description_refresh_uses_the_stored_url_not_the_clients(db, monkeypatch):
    _seed_job()
    fetched = []

    async def fake_fetch(url, max_chars=8000):
        fetched.append(url)
        return ("ATTACKER " if "evil" in url else "REAL ") * 100
    monkeypatch.setattr(job_searcher, "fetch_full_description", fake_fetch)

    out = asyncio.run(main._ensure_full_description({"id": "victim", "description": "", "url": "https://evil.example/x"}))
    assert fetched == ["https://jobs.example.com/real"]
    assert out["description"].startswith("REAL") and jobs_db.get_job("victim")["description"].startswith("REAL")

    out = asyncio.run(main._ensure_full_description({"id": "unknown", "description": "", "url": "https://evil.example/x"}))
    assert out["description"].startswith("ATTACKER")   # used for this request only…
    assert jobs_db.get_job("unknown") is None            # …never persisted
