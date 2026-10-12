"""Password hashing with bcrypt (directly, not passlib).

bcrypt runs in the request thread with a limit of 4 at a time, and never inside a database transaction.
"""

from __future__ import annotations

import threading

import bcrypt

ROUNDS = 12
_limit = threading.BoundedSemaphore(4)
_calls = 0
_calls_lock = threading.Lock()

# A real hash of a random password. Unknown usernames are checked against it, so the response
# time does not show whether a username exists.
_DUMMY_HASH = bcrypt.hashpw(b"panorama-dummy-password", bcrypt.gensalt(ROUNDS)).decode()


def _count() -> None:
    global _calls
    with _calls_lock:
        _calls += 1


def bcrypt_calls() -> int:
    return _calls


def hash_password(password: str) -> str:
    with _limit:
        return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt(ROUNDS)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    _count()
    with _limit:
        try:
            return bcrypt.checkpw(password.encode("utf-8")[:72], password_hash.encode())
        except ValueError:
            return False


def dummy_verify(password: str) -> None:
    verify_password(password, _DUMMY_HASH)


def password_problems(password: str) -> list[str]:
    problems = []
    if len(password) < 8:
        problems.append("at least 8 characters")
    if len(password) > 72:
        problems.append("at most 72 characters")
    if password.lower() == password or password.upper() == password:
        problems.append("upper-case and lower-case letters")
    if not any(ch.isdigit() for ch in password):
        problems.append("a digit")
    return problems
