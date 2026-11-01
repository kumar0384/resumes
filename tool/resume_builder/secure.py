"""Site key: encrypts the resume in the site repo and hides the site behind a secret path.

One random key does two jobs:
  * encryption key for resume.json.enc (Fernet: AES-128 + HMAC-SHA256), so the
    resume is unreadable in a public repo and its history;
  * the secret folder the site is published under, e.g.
    https://you.github.io/resumes/3f9c2a7be1d04c58a6e2f1b9/ - the plain address
    shows an empty page, and the folder can't be guessed or found by searching.

The key lives in two places only: this computer (~/.resume_builder.json) and the
site repo's GitHub Actions secret RESUME_SITE_KEY. Secrets stay hidden even in a
public repo. The path is derived from the key, so the app can show the link.
"""

from __future__ import annotations

import base64
import hashlib
import secrets

ENC_FILE = "resume.json.enc"
SECRET_NAME = "RESUME_SITE_KEY"
MIN_KEY_LEN = 20


class BadKey(Exception):
    """The key is missing, malformed, or doesn't match the encrypted file."""


def new_key() -> str:
    """A fresh random site key (about 190 bits, URL-safe characters)."""
    return secrets.token_urlsafe(24)


def clean_key(key: str | None) -> str:
    k = (key or "").strip()
    if len(k) < MIN_KEY_LEN or any(c.isspace() for c in k):
        raise BadKey(f"A site key is at least {MIN_KEY_LEN} characters with no spaces.")
    return k


def path_token(key: str) -> str:
    """The secret folder name for this key (96 bits, lowercase hex)."""
    return hashlib.sha256(b"resume-site-path:" + clean_key(key).encode()).hexdigest()[:24]


def _fernet(key: str):
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:  # pragma: no cover - dependency is in requirements
        raise BadKey("The 'cryptography' package is missing: pip install cryptography") from exc
    digest = hashlib.sha256(b"resume-site-enc:" + clean_key(key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(text: str, key: str) -> str:
    return _fernet(key).encrypt(text.encode("utf-8")).decode("ascii")


def decrypt(token: str, key: str) -> str:
    from cryptography.fernet import InvalidToken
    try:
        return _fernet(key).decrypt(token.strip().encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise BadKey("This site key doesn't match the encrypted resume.") from exc


def private_url(base_url: str, key: str) -> str:
    return base_url.rstrip("/") + "/" + path_token(key) + "/"
