"""Session tokens: PyJWT HS256, 8 hours, in the httpOnly SameSite=Strict cookie pa_session.

The API also accepts a Bearer token (tests and the load test). All replicas share JWT_SECRET.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import jwt

from app.config import app_secret, get_settings

COOKIE = "pa_session"
ALGORITHM = "HS256"


def now() -> datetime:
    """Injectable clock (tests move it)."""
    return datetime.now(timezone.utc)


def issue(user_id: int, token_version: int) -> tuple[str, int]:
    s = get_settings()
    iat = datetime.now(timezone.utc)
    ttl = int(timedelta(hours=s.jwt_ttl_hours).total_seconds())
    payload = {"sub": str(user_id), "ver": int(token_version), "iat": iat, "exp": iat + timedelta(seconds=ttl),
               "jti": uuid.uuid4().hex, "iss": "panorama"}
    return jwt.encode(payload, app_secret("jwt_secret"), algorithm=ALGORITHM), ttl


class TokenError(Exception):
    pass


def decode(token: str) -> tuple[int, int]:
    try:
        payload = jwt.decode(
            token, app_secret("jwt_secret"), algorithms=[ALGORITHM], issuer="panorama",
            options={"require": ["sub", "ver", "exp", "iat", "iss"]},
        )
        return int(payload["sub"]), int(payload["ver"])
    except (jwt.PyJWTError, ValueError, TypeError) as exc:
        raise TokenError(str(exc)) from exc
