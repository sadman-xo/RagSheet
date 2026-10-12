"""Retention. Runs only in init (as panorama_owner); the api role cannot delete."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import psycopg

from app.config import Settings


def _delete_batches(conn: psycopg.Connection, sql: str, params: tuple, batch_pause: float = 0.05) -> int:
    total = 0
    while True:
        with conn.transaction():
            n = conn.execute(sql, params).rowcount
        total += n
        if n < 1000:
            return total
        time.sleep(batch_pause)


def run_retention(conn: psycopg.Connection, s: Settings) -> dict:
    now = datetime.now(timezone.utc)
    query_cutoff = now - timedelta(days=s.audit_query_retention_days)
    audit_cutoff = now - timedelta(days=s.audit_retention_days)
    chat_cutoff = now - timedelta(days=s.chat_retention_days)
    out = {}
    out["audit_query"] = _delete_batches(
        conn,
        "DELETE FROM app.audit_log WHERE id IN (SELECT id FROM app.audit_log WHERE action = 'query' AND ts < %s ORDER BY id LIMIT 1000)",
        (query_cutoff,),
    )
    out["audit"] = _delete_batches(
        conn,
        "DELETE FROM app.audit_log WHERE id IN (SELECT id FROM app.audit_log WHERE ts < %s ORDER BY id LIMIT 1000)",
        (audit_cutoff,),
    )
    sessions = 0
    while True:
        with conn.transaction():
            ids = [r[0] for r in conn.execute(
                "SELECT id FROM app.chat_sessions WHERE updated_at < %s ORDER BY id LIMIT 200", (chat_cutoff,)).fetchall()]
            if ids:
                conn.execute("DELETE FROM app.feedback WHERE message_id IN (SELECT id FROM app.chat_messages WHERE session_id = ANY(%s))", (ids,))
                conn.execute("DELETE FROM app.chat_messages WHERE session_id = ANY(%s)", (ids,))
                conn.execute("DELETE FROM app.chat_sessions WHERE id = ANY(%s)", (ids,))
        sessions += len(ids)
        if len(ids) < 200:
            break
        time.sleep(0.05)
    out["chat_sessions"] = sessions
    return out
