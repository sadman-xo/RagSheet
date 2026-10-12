"""Chat sessions and messages (sync functions; async code calls them through db.run_sync).

The history keeps plans, not data. If the scope fingerprint changes, a new session starts.
RLS makes sure that a user reads and writes only the own chat rows.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import Text, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from app import audit
from app.db import engine as db


@dataclass
class TurnMemory:
    session_id: int
    parent_plan: dict | None
    history: list[str]
    new_session: bool


def load(user_id: int, scope_fp: str, session_id: int | None, parent_message_id: int | None, title: str) -> TurnMemory:
    def _w(c):
        sid = None
        parent_plan = None
        if parent_message_id:
            r = c.execute(text("""SELECT m.session_id, m.plan, s.scope_fp FROM app.chat_messages m
                                  JOIN app.chat_sessions s ON s.id = m.session_id WHERE m.id = :id"""), {"id": parent_message_id}).first()
            if r and r.scope_fp == scope_fp:
                sid, parent_plan = r.session_id, r.plan
        if sid is None and session_id:
            r = c.execute(text("SELECT id, scope_fp FROM app.chat_sessions WHERE id = :id"), {"id": session_id}).first()
            if r and r.scope_fp == scope_fp:
                sid = r.id
        new = False
        if sid is None:
            sid = c.execute(text("""INSERT INTO app.chat_sessions (user_id, title, scope_fp) VALUES (:u, :t, :fp) RETURNING id"""),
                            {"u": user_id, "t": title[:80], "fp": scope_fp}).scalar_one()
            new = True
        hist = [r.content for r in c.execute(text("""SELECT content FROM app.chat_messages WHERE session_id = :s AND role = 'user'
                                                    ORDER BY id DESC LIMIT 3"""), {"s": sid}).all()][::-1]
        return TurnMemory(session_id=sid, parent_plan=parent_plan, history=hist, new_session=new)

    return db.write(_w, user_id=user_id)


_INSERT_MSG = text("""
INSERT INTO app.chat_messages (session_id, user_id, role, content, plan, sources, verification, mode, timings, flags, turn_id, parent_message_id)
VALUES (:session_id, :user_id, :role, :content, :plan, :sources, :verification, :mode, :timings, :flags, :turn_id, :parent)
RETURNING id
""").bindparams(bindparam("plan", type_=JSONB), bindparam("sources", type_=JSONB), bindparam("verification", type_=JSONB),
                bindparam("timings", type_=JSONB), bindparam("flags", type_=ARRAY(Text)))


def _msg(c, **kw) -> int:
    row = {"plan": None, "sources": None, "verification": None, "mode": None, "timings": None, "flags": [], "parent": None, **kw}
    mid = c.execute(_INSERT_MSG, row).scalar_one()
    c.execute(text("UPDATE app.chat_sessions SET updated_at = now() WHERE id = :s"), {"s": row["session_id"]})
    return mid


def save_question(user_id: int, session_id: int, turn_id: str, content: str, plan: dict | None, flags: list[str],
                  parent: int | None, audit_kw: dict) -> int:
    """The question and its chat_query audit row commit together."""
    def _w(c):
        mid = _msg(c, session_id=session_id, user_id=user_id, role="user", content=content, plan=plan, flags=flags,
                   turn_id=turn_id, parent=parent)
        audit.record(c, "chat_query", **audit_kw, detail={"turn_id": turn_id, "plan": plan, "message_id": mid}, flags=flags)
        return mid

    return db.write(_w, user_id=user_id)


def save_refusal(user_id: int, session_id: int, turn_id: str, question: str, answer: str, flags: list[str],
                 parent: int | None, audit_kw: dict, detail: dict) -> tuple[int, int]:
    """Question, refusal, and the scope_violation audit row in one transaction."""
    def _w(c):
        q = _msg(c, session_id=session_id, user_id=user_id, role="user", content=question, flags=flags, turn_id=turn_id, parent=parent)
        a = _msg(c, session_id=session_id, user_id=user_id, role="assistant", content=answer, mode="refusal", flags=flags,
                 turn_id=turn_id, parent=q)
        audit.record(c, "scope_violation", **audit_kw, detail={"turn_id": turn_id, "source": "chat", **detail}, flags=flags)
        return q, a

    return db.write(_w, user_id=user_id)


def save_answer(user_id: int, session_id: int, turn_id: str, content: str, plan: dict | None, sources: list | None,
                verification: dict | None, mode: str, timings: dict, flags: list[str], parent: int | None) -> int:
    return db.write(lambda c: _msg(c, session_id=session_id, user_id=user_id, role="assistant", content=content, plan=plan,
                                   sources=sources, verification=verification, mode=mode, timings=timings, flags=flags,
                                   turn_id=turn_id, parent=parent), user_id=user_id)


def message_plan(user_id: int, message_id: int) -> dict | None:
    with db.scoped(user_id) as c:
        r = c.execute(text("SELECT plan FROM app.chat_messages WHERE id = :id"), {"id": message_id}).first()
    return r.plan if r else None


def sessions(user_id: int, limit: int = 30) -> list[dict]:
    with db.scoped(user_id) as c:
        rows = c.execute(text("""SELECT s.id, s.title, s.created_at, s.updated_at,
                                 (SELECT count(*) FROM app.chat_messages m WHERE m.session_id = s.id) AS messages
                                 FROM app.chat_sessions s ORDER BY s.updated_at DESC LIMIT :l"""), {"l": limit}).mappings().all()
    return [{**dict(r), "created_at": r["created_at"].isoformat(), "updated_at": r["updated_at"].isoformat()} for r in rows]


def session_messages(user_id: int, session_id: int, scope_fp: str) -> dict | None:
    with db.scoped(user_id) as c:
        s = c.execute(text("SELECT id, title, scope_fp FROM app.chat_sessions WHERE id = :id"), {"id": session_id}).mappings().first()
        if s is None:
            return None
        rows = c.execute(text("""SELECT m.id, m.role, m.content, m.plan, m.sources, m.verification, m.mode, m.timings, m.created_at,
                                 m.turn_id, m.parent_message_id, (SELECT f.rating FROM app.feedback f WHERE f.message_id = m.id) AS rating
                                 FROM app.chat_messages m WHERE m.session_id = :s ORDER BY m.id"""), {"s": session_id}).mappings().all()
    msgs = []
    for r in rows:
        d = dict(r)
        d["created_at"] = d["created_at"].isoformat()
        d["turn_id"] = str(d["turn_id"])
        msgs.append(d)
    return {"id": s["id"], "title": s["title"], "stale": s["scope_fp"] != scope_fp, "messages": msgs}


def feedback(user_id: int, message_id: int, rating: int, comment: str | None) -> bool:
    def _w(c):
        r = c.execute(text("SELECT id FROM app.chat_messages WHERE id = :id AND role = 'assistant'"), {"id": message_id}).first()
        if r is None:
            return False
        c.execute(text("""INSERT INTO app.feedback (message_id, user_id, rating, comment) VALUES (:m, :u, :r, :c)
                          ON CONFLICT (message_id, user_id) DO UPDATE SET rating = EXCLUDED.rating, comment = EXCLUDED.comment,
                          created_at = now()"""), {"m": message_id, "u": user_id, "r": rating, "c": comment})
        return True

    return db.write(_w, user_id=user_id)


def dumps(obj) -> str:
    return json.dumps(obj, default=str)
