"""Parent PIN authentication.

The app uses a single shared PIN stored in the PARENT_PIN env var. After the
parent enters the PIN on /login, we set a session flag that the
`require_parent` dependency checks on every admin route.
"""
from __future__ import annotations

import os
from datetime import timedelta

from fastapi import HTTPException, Request, status

SESSION_KEY = "parent_authenticated"
SESSION_MAX_AGE_SECONDS = int(timedelta(days=7).total_seconds())


def parent_pin() -> str:
    """Return the configured parent PIN, with a sane dev default."""
    return os.environ.get("PARENT_PIN", "1234")


def session_secret() -> str:
    """Return the secret used to sign the session cookie."""
    secret = os.environ.get("SESSION_SECRET", "dev-only-insecure-secret")
    if secret == "dev-only-insecure-secret":
        # Loud warning in dev so the user notices the default.
        # In prod this would be a real error.
        import logging

        logging.getLogger("summer").warning(
            "SESSION_SECRET is not set; using insecure default. Set it in .env."
        )
    return secret


def is_authenticated(request: Request) -> bool:
    return bool(request.session.get(SESSION_KEY))


def require_parent(request: Request) -> None:
    """FastAPI dependency: 401 to the login page if not authenticated as parent."""
    if not is_authenticated(request):
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"},
        )
