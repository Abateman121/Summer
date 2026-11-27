"""Parent PIN authentication.

The app uses a single shared PIN stored in the PARENT_PIN env var. After the
parent enters the PIN on /login, we set a session flag that the
`require_parent` dependency checks on every admin route.
"""
from __future__ import annotations

import hmac
import logging
import os
import threading
import time
from datetime import timedelta

from fastapi import HTTPException, Request, status

SESSION_KEY = "parent_authenticated"
SESSION_MAX_AGE_SECONDS = int(timedelta(days=7).total_seconds())

_INSECURE_SECRET = "dev-only-insecure-secret"


def parent_pin() -> str:
    """Return the configured parent PIN, with a sane dev default."""
    return os.environ.get("PARENT_PIN", "1234")


def session_secret() -> str:
    """Return the secret used to sign the session cookie.

    Raises ValueError in production if using the insecure default,
    since that would allow session tampering.
    """
    secret = os.environ.get("SESSION_SECRET", _INSECURE_SECRET)
    if secret == _INSECURE_SECRET:
        env = os.environ.get("ENVIRONMENT", "").lower()
        if env in ("production", "prod", "live"):
            raise ValueError(
                "SESSION_SECRET is set to the insecure default. "
                "Set a long random string (32+ chars) in your .env file."
            )
        # Dev/test: loud warning
        logging.getLogger("summer").warning(
            "SESSION_SECRET is not set; using insecure default. Set it in .env."
        )
    return secret


def require_https() -> bool:
    """Whether to enforce HTTPS on session cookies.

    Set FORCE_HTTPS=true in .env when behind a reverse proxy (Traefik,
    Cloudflare Tunnel, etc.) that terminates TLS and forwards X-Forwarded-Proto.
    """
    return os.environ.get("FORCE_HTTPS", "false").lower() in ("true", "1", "yes")


def is_authenticated(request: Request) -> bool:
    return bool(request.session.get(SESSION_KEY))


def require_parent(request: Request) -> None:
    """FastAPI dependency: 401 to the login page if not authenticated as parent."""
    if not is_authenticated(request):
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"},
        )


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

# In-memory store of failed PIN attempts: key -> (count, first_failure_time).
# Keys are "login:<client ip>" for the parent PIN and "kid:<kid id>" for kid
# PINs. Module-level (not request.state, which is per request) so it really
# persists between attempts. Per-process: fine for the single uvicorn
# process this app runs as; it resets on restart, which is acceptable for a
# brute-force deterrent.
_MAX_ATTEMPTS = 5
_LOCKOUT_SECONDS = 300  # 5 minutes
_attempts: dict[str, tuple[int, float]] = {}
_attempts_lock = threading.Lock()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def lockout_remaining(key: str) -> int:
    """Seconds left on this key's lockout, or 0 if it may try again."""
    now = time.time()
    with _attempts_lock:
        count, first_failure = _attempts.get(key, (0, 0.0))
        if count and now - first_failure > _LOCKOUT_SECONDS:
            # Window expired; forget it
            _attempts.pop(key, None)
            return 0
    if count >= _MAX_ATTEMPTS:
        return max(1, int(_LOCKOUT_SECONDS - (now - first_failure)))
    return 0


def record_failed_attempt(key: str) -> None:
    """Count a wrong PIN for this key (call after a failed check)."""
    now = time.time()
    with _attempts_lock:
        # Drop expired entries so the dict can't grow without bound
        for k in [k for k, (_, t) in _attempts.items() if now - t > _LOCKOUT_SECONDS]:
            del _attempts[k]
        count, first_failure = _attempts.get(key, (0, now))
        count += 1
        _attempts[key] = (count, first_failure)
    if count == _MAX_ATTEMPTS:
        logging.getLogger("summer").warning(
            "PIN attempts locked out for %s after %d failures (%d seconds).",
            key, count, _LOCKOUT_SECONDS,
        )


def clear_failed_attempts(key: str) -> None:
    """Forget failures for this key (call after a correct PIN)."""
    with _attempts_lock:
        _attempts.pop(key, None)


def pin_matches(given: str, expected: str) -> bool:
    """Constant-time PIN comparison."""
    return hmac.compare_digest(given.strip().encode("utf-8"), expected.encode("utf-8"))


# ---------------------------------------------------------------------------
# Kid PIN (per-kid, for kid-facing submissions accountability)
# ---------------------------------------------------------------------------


def require_kid_pin() -> bool:
    """Whether kid PIN is required for chore/reward submissions.

    Set KID_PIN_REQUIRED=true in .env to enable. When enabled, each kid
    must have their own PIN set by a parent on the Manage Kids page.
    """
    return os.environ.get("KID_PIN_REQUIRED", "false").lower() in ("true", "1", "yes")


# ---------------------------------------------------------------------------
# API keys (read-only JSON API, e.g. for dashboard widgets)
# ---------------------------------------------------------------------------

API_KEY_PREFIX = "smr_"


def generate_api_key() -> str:
    """Return a new random API key. Only its hash is ever stored."""
    import secrets

    return API_KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_key(key: str) -> str:
    """SHA-256 hex digest of a key.

    A plain hash (no salt / slow KDF) is fine here: keys are 256-bit
    random values, not human-chosen passwords, so they can't be guessed
    from the hash.
    """
    import hashlib

    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def api_key_from_request(request: Request) -> str | None:
    """Read the key from `X-API-Key` or `Authorization: Bearer <key>`.

    Query-string keys are deliberately not accepted: URLs end up in
    proxy and browser logs.
    """
    key = request.headers.get("x-api-key")
    if key:
        return key.strip()
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None
