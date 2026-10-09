"""
Shared fixtures for the API test suite.

Several app modules read configuration at import time (JWT_SECRET, CREDENTIALS_KEY,
OLLAMA_HOST, LLM_BACKEND…), so the environment — including a fake Ollama server — is set up
here at module level, before any test imports `app`.
"""
import hashlib
import http.server
import json
import os
import tempfile
import threading
import time

import pytest
from cryptography.fernet import Fernet


# ── Fake Ollama: deterministic 64-d embeddings, call accounting, latency knob ──

def fake_vector(text: str) -> list[float]:
    digest = hashlib.sha256(text.encode()).digest() * 2
    return [(b / 255.0) - 0.5 for b in digest]


class FakeOllama(http.server.BaseHTTPRequestHandler):
    calls: list[tuple[str, int]] = []   # (endpoint, number of inputs)
    delay = 0.0
    embed_404 = False                   # simulate an old Ollama without /api/embed

    @classmethod
    def reset(cls):
        cls.calls, cls.delay, cls.embed_404 = [], 0.0, False

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        time.sleep(FakeOllama.delay)
        if self.path == "/api/embed" and not FakeOllama.embed_404:
            FakeOllama.calls.append(("embed", len(body["input"])))
            payload = {"embeddings": [fake_vector(t) for t in body["input"]]}
        elif self.path == "/api/embeddings":
            FakeOllama.calls.append(("embeddings", 1))
            payload = {"embedding": fake_vector(body["prompt"])}
        else:
            self.send_response(404)
            self.end_headers()
            return
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


_ollama = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
threading.Thread(target=_ollama.serve_forever, daemon=True).start()

os.environ.update({
    "JWT_SECRET": "test-jwt-secret",
    "CREDENTIALS_KEY": Fernet.generate_key().decode(),
    "APP_DATA_PATH": tempfile.mkdtemp(prefix="windrush-tests-"),
    "LLM_BACKEND": "groq",
    "GROQ_API_KEY": "test-key",
    "OLLAMA_HOST": f"http://127.0.0.1:{_ollama.server_address[1]}",
    "ANONYMIZED_TELEMETRY": "false",
})


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def ollama():
    """The fake Ollama handler class (inspect .calls, set .delay / .embed_404)."""
    from app import semantic
    FakeOllama.reset()
    semantic._embedding_cache.clear()
    yield FakeOllama
    FakeOllama.reset()


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Fresh applications.db / jobs.db / PDF + CV dirs for one test."""
    from app import tracker, jobs_db, pdf_generator, discovery, semantic
    monkeypatch.setenv("APP_DATA_PATH", str(tmp_path))
    tracker.init_db(str(tmp_path / "applications.db"))
    jobs_db.init_db(str(tmp_path / "jobs.db"))
    pdf_generator.init_pdf_dir(str(tmp_path))
    discovery._running.clear()
    discovery._finished_at.clear()
    semantic._embedding_cache.clear()
    return tmp_path


@pytest.fixture
def make_user(db):
    from app import tracker
    def _make(email: str = "user@example.com") -> str:
        return tracker.create_user(email, "not-a-real-hash")
    return _make


@pytest.fixture
def user(make_user):
    return make_user()


@pytest.fixture
def client_for(db):
    """client_for(user_id) → TestClient authenticated as that user (no real JWT needed)."""
    from fastapi.testclient import TestClient
    from app import auth, main

    def _client(user_id: str) -> TestClient:
        main.app.dependency_overrides[auth.get_current_user] = lambda: auth.User(id=user_id, email=f"{user_id}@x")
        return TestClient(main.app)

    yield _client
    main.app.dependency_overrides.clear()


@pytest.fixture
def client(client_for, user):
    return client_for(user)


def make_job(job_id, title="Job", company=None, location="London, UK", description="", level="mid", **extra):
    return {"job_id": str(job_id), "title": title, "company": company or f"Co{job_id}", "location": location,
            "description": description, "url": f"https://jobs.example.com/{job_id}", "level": level,
            "source": "ats", **extra}
