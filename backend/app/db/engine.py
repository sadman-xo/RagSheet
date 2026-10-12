"""Database access for the api.

Rules:
- Each scoped transaction starts with set_config('app.user_id', :uid, true). The setting ends with
  the transaction, so a pooled connection never carries a user ID to the next request.
- All writes go through write(): one short transaction, one retry on deadlock or lock timeout, then 503.
- Async code never calls the database directly; it uses run_sync() (a thread with its own limiter).
- Nothing inside a transaction does network, LLM, DuckDB, bcrypt, or file I/O.
"""

from __future__ import annotations

import random
import threading
import time
from collections import deque
from contextlib import contextmanager
from typing import Callable, Iterator, TypeVar
from urllib.parse import quote

import anyio
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeout

from app.config import app_secret, get_settings, read_secret

T = TypeVar("T")

_engine: Engine | None = None
_engine_lock = threading.Lock()
_db_limiter: anyio.CapacityLimiter | None = None

RETRY_SQLSTATES = {"40P01", "55P03"}  # deadlock, lock timeout
TIMEOUT_SQLSTATE = "57014"            # statement timeout


class DatabaseUnavailable(Exception):
    """The database cannot serve the request now (503)."""


def app_url(dbname: str | None = None) -> str:
    s = get_settings()
    pw = quote(app_secret("app_db_password"), safe="")
    return f"postgresql+psycopg://{s.db_app_user}:{pw}@{s.db_host}:{s.db_port}/{dbname or s.db_name}"


def superuser_url(dbname: str | None = None) -> str:
    s = get_settings()
    pw = quote(read_secret(s.secrets_db_dir, "postgres_password"), safe="")
    return f"postgresql+psycopg://postgres:{pw}@{s.db_host}:{s.db_port}/{dbname or s.db_name}"


def make_engine(url: str, pool_size: int | None = None, max_overflow: int | None = None) -> Engine:
    s = get_settings()
    return create_engine(
        url,
        pool_size=pool_size if pool_size is not None else s.db_pool_size,
        max_overflow=max_overflow if max_overflow is not None else s.db_max_overflow,
        pool_timeout=s.db_pool_timeout,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={"connect_timeout": 3, "application_name": f"panorama-api:{s.replica}"},
    )


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = make_engine(app_url())
    return _engine


def set_engine(engine: Engine | None) -> None:
    """Tests use this to point the app at a test database."""
    global _engine
    _engine = engine


def dispose() -> None:
    if _engine is not None:
        _engine.dispose()


def _sqlstate(exc: BaseException) -> str | None:
    orig = getattr(exc, "orig", None)
    return getattr(orig, "sqlstate", None)


@contextmanager
def _translate() -> Iterator[None]:
    try:
        yield
    except PoolTimeout as exc:
        raise DatabaseUnavailable("database pool timeout") from exc
    except OperationalError as exc:
        if _sqlstate(exc) in RETRY_SQLSTATES or _sqlstate(exc) == TIMEOUT_SQLSTATE:
            raise
        raise DatabaseUnavailable(str(exc.orig) if exc.orig else str(exc)) from exc


@contextmanager
def scoped(user_id: int) -> Iterator[Connection]:
    """A transaction with the database scope of one user (transaction-local setting)."""
    with _translate(), get_engine().begin() as conn:
        conn.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(int(user_id))})
        yield conn


@contextmanager
def autocommit() -> Iterator[Connection]:
    """Autocommit: each statement is its own transaction. Only for one-statement reads such as
    app.load_principal(), which sets the transaction-local app.user_id inside that statement."""
    with _translate(), get_engine().connect() as conn:
        conn.execution_options(isolation_level="AUTOCOMMIT")
        yield conn


@contextmanager
def unscoped() -> Iterator[Connection]:
    """A transaction without a user scope (login, audit flush, health)."""
    with _translate(), get_engine().begin() as conn:
        yield conn


# ---------------------------------------------------------------------------
# Writes with retry
# ---------------------------------------------------------------------------
_write_times: deque[float] = deque(maxlen=2000)
_write_lock = threading.Lock()


def write(fn: Callable[[Connection], T], user_id: int | None = None) -> T:
    """Run fn in one short write transaction. One retry on deadlock/lock timeout, then 503."""
    for attempt in (1, 2):
        t0 = time.perf_counter()
        try:
            ctx = scoped(user_id) if user_id is not None else unscoped()
            with ctx as conn:
                result = fn(conn)
            with _write_lock:
                _write_times.append((time.perf_counter() - t0) * 1000)
            return result
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state in RETRY_SQLSTATES and attempt == 1:
                time.sleep(random.uniform(0.05, 0.25))
                continue
            if state in RETRY_SQLSTATES or state == TIMEOUT_SQLSTATE:
                raise DatabaseUnavailable(f"database busy ({state})") from exc
            raise
    raise DatabaseUnavailable("database busy")  # pragma: no cover


def write_p95_ms() -> float | None:
    with _write_lock:
        if not _write_times:
            return None
        xs = sorted(_write_times)
    return xs[min(len(xs) - 1, int(len(xs) * 0.95))]


# ---------------------------------------------------------------------------
# Async bridge
# ---------------------------------------------------------------------------
def _limiter() -> anyio.CapacityLimiter:
    global _db_limiter
    if _db_limiter is None:
        _db_limiter = anyio.CapacityLimiter(8)
    return _db_limiter


async def run_sync(fn: Callable[[], T], abandon_on_cancel: bool = False) -> T:
    """Run a blocking database function in a worker thread (async code must use this)."""
    return await anyio.to_thread.run_sync(fn, abandon_on_cancel=abandon_on_cancel, limiter=_limiter())
