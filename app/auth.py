"""Parent PIN authentication.

The app uses a single shared PIN stored in the PARENT_PIN env var. After the
parent enters the PIN on /login, we set a session flag that the
`require_parent` dependency checks on every admin route.
"""
from __future__ import annotations

import logging
import os
from datetime import timedelta

from fastapi import HTTPException, Request, status

SESSION_KEY = "parent_authenticated"
SESSION_MAX_AGE_SECONDS = int(timedelta(days=7).total_seconds())

_INSECURE_SECRET = "dev-only-insecure-secret"
_RATE_LIMIT_KEY = "login_attempts"


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

# In-memory store for failed login attempts. Key = IP address, value =
# (count, first_failure_timestamp). This is per-process; in a multi-worker
# deployment you'd want Redis, but for a home/server app on a single process
# this is sufficient. Wipes on restart but that's fine for a brute-force
# deterrent.
_MAX_ATTEMPTS = 5
_LOCKOUT_SECONDS = 300  # 5 minutes


def _get_login_attempts(request: Request) -> tuple[int, float]:
    """Return (count, first_failure_timestamp) for the current IP."""
    raw = request.state.__dict__.get(_RATE_LIMIT_KEY)
    if raw is None:
        return 0, 0.0
    return raw  # type: ignore


def _set_login_attempts(request: Request, count: int, first_failure: float) -> None:
    request.state.__dict__[_RATE_LIMIT_KEY] = (count, first_failure)


def check_login_rate_limit(request: Request) -> None:
    """Raise 429 if this IP has too many failed attempts.

    Call at the start of the login POST handler.
    """
    import time

    count, first_failure = _get_login_attempts(request)
    if count == 0:
        return  # No history, no problem

    elapsed = time.time() - first_failure
    if elapsed > _LOCKOUT_SECONDS:
        # Lockout expired; reset
        _set_login_attempts(request, 0, 0.0)
        return

    if count >= _MAX_ATTEMPTS:
        remaining = int(_LOCKOUT_SECONDS - elapsed)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed attempts. Try again in {remaining} seconds.",
        )


def record_failed_login(request: Request) -> None:
    """Record a failed PIN attempt for rate limiting.

    Call after an incorrect PIN is submitted.
    """
    import time

    count, first_failure = _get_login_attempts(request)
    if count == 0:
        first_failure = time.time()
    count += 1
    _set_login_attempts(request, count, first_failure)

    if count >= _MAX_ATTEMPTS:
        remaining = _LOCKOUT_SECONDS - int(time.time() - first_failure)
        logging.getLogger("summer").warning(
            "Parent login rate limited (IP: %s). Attempts: %d. "
            "Locked out for %d seconds.",
            request.client.host if request.client else "unknown",
            count,
            max(0, remaining),
        )


def clear_login_attempts(request: Request) -> None:
    """Clear rate limit state on successful login."""
    _set_login_attempts(request, 0, 0.0)


# ---------------------------------------------------------------------------
# Kid PIN (global, for kid-facing submissions accountability)
# ---------------------------------------------------------------------------


def require_kid_pin() -> bool:
    """Whether kid PIN is required for chore/reward submissions.

    Set KID_PIN_REQUIRED=true in .env to enable.
    """
    return os.environ.get("KID_PIN_REQUIRED", "false").lower() in ("true", "1", "yes")


def kid_pin() -> str | None:
    """Return the configured kid PIN, or None if not required."""
    if not require_kid_pin():
        return None
    return os.environ.get("KID_PIN", "")
