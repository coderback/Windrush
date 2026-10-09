"""Required secrets: the API must refuse to start without them (no insecure defaults)."""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

API_DIR = Path(__file__).resolve().parents[1]


def _import(module: str, **env_overrides) -> subprocess.CompletedProcess:
    env = {**os.environ, **env_overrides}
    env = {k: v for k, v in env.items() if v is not None}
    return subprocess.run([sys.executable, "-c", f"import {module}"], cwd=API_DIR, env=env,
                          capture_output=True, text=True, timeout=120)


def test_auth_refuses_to_start_without_jwt_secret():
    env = {k: v for k, v in os.environ.items() if k != "JWT_SECRET"}
    r = subprocess.run([sys.executable, "-c", "import app.auth"], cwd=API_DIR, env=env,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode != 0 and "JWT_SECRET" in r.stderr


@pytest.mark.parametrize("key, message", [("", "CREDENTIALS_KEY is not set"),
                                          ("not-a-fernet-key", "not a valid Fernet key")])
def test_crypto_refuses_bad_or_missing_key(key, message):
    r = _import("app.crypto", CREDENTIALS_KEY=key)
    assert r.returncode != 0 and message in r.stderr


def test_crypto_starts_with_a_valid_key():
    assert _import("app.crypto", CREDENTIALS_KEY=Fernet.generate_key().decode()).returncode == 0
