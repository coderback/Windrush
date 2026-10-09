"""
Encryption at rest for stored third-party credentials (the user's job-site password).

Fernet (AES-128-CBC + HMAC-SHA256) keyed by CREDENTIALS_KEY. Kept separate from JWT_SECRET
so rotating the login-token secret doesn't make stored credentials undecryptable.
"""
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger("windrush.crypto")

_KEY = os.environ.get("CREDENTIALS_KEY", "")
if not _KEY:
    raise RuntimeError(
        "CREDENTIALS_KEY is not set — generate one with: "
        "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\" "
        "and add it to .env"
    )
try:
    _fernet = Fernet(_KEY.encode())
except (ValueError, TypeError) as exc:
    raise RuntimeError("CREDENTIALS_KEY is not a valid Fernet key (32 url-safe base64-encoded bytes)") from exc


def encrypt(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    """Decrypt a stored token; '' if it can't be (e.g. CREDENTIALS_KEY was changed)."""
    try:
        return _fernet.decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        logger.warning("Stored credential could not be decrypted — was CREDENTIALS_KEY changed?")
        return ""
