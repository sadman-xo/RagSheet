"""Audit log.

- Security events (login, login_failed, logout, scope_violation, scope_mismatch, permission_denied, export,
  user_change, leak_scan) commit before the response, with normal durability. record() takes the caller's
  connection, so a business change and its audit row commit together.
- Dashboard `query` events go into a bounded buffer. A flusher thread writes them each second with
  executemany in chunks of 1,000 rows, with synchronous_commit off (a crash can lose <= 1 s of these rows).
- The app has INSERT only on app.audit_log: Core inserts without RETURNING.
"""

from __future__ import annotations

import ipaddress
import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Connection, Text, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from app.config import get_settings
from app.db import engine as db
from app.db.models import worker_stats

# Plain INSERT without RETURNING and without a sequence call (the app has INSERT only).
INSERT_SQL = text(
    "INSERT INTO app.audit_log (ts, user_id, username, role, action, scope_key, ip, request_id, replica, detail, flags) "
    "VALUES (:ts, :user_id, :username, :role, :action, :scope_key, CAST(:ip AS inet), CAST(:request_id AS uuid), :replica, :detail, :flags)"
).bindparams(bindparam("detail", type_=JSONB), bindparam("flags", type_=ARRAY(Text)))

BUFFER_MAX = 10_000
CHUNK = 1_000


@dataclass(frozen=True)
class RequestInfo:
    ip: str | None = None
    request_id: str | None = None


def _ip(value: str | None) -> str | None:
    try:
        return str(ipaddress.ip_address(value)) if value else None
    except ValueError:
        return None


def make_row(action: str, *, user_id: int | None = None, username: str | None = None, role: str | None = None,
             scope_key: str | None = None, req: RequestInfo | None = None, detail: dict | None = None,
             flags: list[str] | None = None) -> dict:
    return {
        "ts": datetime.now(timezone.utc),
        "user_id": user_id, "username": username, "role": role, "action": action, "scope_key": scope_key,
        "ip": _ip(req.ip) if req else None, "request_id": req.request_id if req else None,
        "replica": get_settings().replica, "detail": detail or {}, "flags": flags or [],
    }


def principal_fields(principal, scope_key: str | None = None) -> dict:
    if principal is None:
        return {}
    return {"user_id": principal.id, "username": principal.username, "role": principal.role,
            "scope_key": scope_key or principal.db_scope_key}


def record(conn: Connection, action: str, **kw) -> None:
    """Insert one audit row in the caller's transaction."""
    conn.execute(INSERT_SQL, [make_row(action, **kw)])


def record_now(action: str, **kw) -> None:
    """A security event: its own short transaction, committed before the response."""
    db.write(lambda c: record(c, action, **kw))


class AuditBuffer:
    def __init__(self) -> None:
        self._rows: deque[dict] = deque()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.dropped = 0
        self.written = 0
        self.requests = 0
        self.started_at = datetime.now(timezone.utc)
        self.process_id = f"{get_settings().replica}:{os.getpid()}"
        self._last_stats = 0.0

    def add(self, action: str, **kw) -> None:
        row = make_row(action, **kw)
        with self._lock:
            if len(self._rows) >= BUFFER_MAX:
                self.dropped += 1
                return
            self._rows.append(row)

    def flush(self) -> int:
        with self._lock:
            rows = list(self._rows)
            self._rows.clear()
        n = 0
        for i in range(0, len(rows), CHUNK):
            chunk = rows[i:i + CHUNK]

            def _w(c: Connection, chunk=chunk) -> None:
                c.execute(text("SET LOCAL synchronous_commit = off"))
                c.execute(INSERT_SQL, chunk)

            try:
                db.write(_w)
                n += len(chunk)
            except Exception:
                with self._lock:
                    self.dropped += len(chunk)
        self.written += n
        return n

    def write_stats(self, extra: dict | None = None) -> None:
        from app.analytics.engine import cache_stats

        cs = cache_stats()
        now = datetime.now(timezone.utc)
        row = {
            "process_id": self.process_id, "replica": get_settings().replica, "started_at": self.started_at,
            "updated_at": now, "requests": self.requests, "write_p95_ms": db.write_p95_ms(),
            "audit_dropped": self.dropped, "audit_written": self.written,
            "cache_hits": cs["hits"], "cache_misses": cs["misses"], "detail": extra or {},
        }
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = pg_insert(worker_stats).values(**row)
        stmt = stmt.on_conflict_do_update(index_elements=["process_id"], set_={k: stmt.excluded[k] for k in row if k != "process_id"})
        db.write(lambda c: c.execute(stmt))

    def _loop(self) -> None:
        while not self._stop.wait(1.0):
            try:
                self.flush()
                if time.monotonic() - self._last_stats > 10:
                    self._last_stats = time.monotonic()
                    self.write_stats()
            except Exception as exc:  # never kill the thread
                print(f"audit: flusher error: {exc}", flush=True)

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="audit-flusher", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        try:
            self.flush()
            self.write_stats()
        except Exception:
            pass


buffer = AuditBuffer()


def flush() -> int:
    """Tests call this to make the buffered rows visible."""
    return buffer.flush()
