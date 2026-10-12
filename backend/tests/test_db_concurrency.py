from __future__ import annotations

import multiprocessing as mp
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError

from app import audit
from app import init as initmod
from app.config import get_settings
from app.db import engine as db
from tests.conftest import ORIGIN, app_connect, bearer


def _child(dbname: str, tag: str, n_threads: int, n_tx: int, q) -> None:
    from app.db import engine as cdb

    cdb.set_engine(cdb.make_engine(cdb.app_url(dbname)))
    errors = 0

    def work(t: int) -> int:
        e = 0
        for i in range(n_tx):
            try:
                cdb.write(lambda c, i=i: audit.record(c, "conc_test", username=tag, detail={"t": t, "i": i}))
            except Exception:
                e += 1
        return e

    with ThreadPoolExecutor(n_threads) as ex:
        errors = sum(ex.map(work, range(n_threads)))
    q.put(errors)


def test_parallel_write_transactions(test_db, owner_db):
    tag = f"conc_{uuid.uuid4().hex[:8]}"
    ctx = mp.get_context("fork")
    q = ctx.Queue()
    procs = [ctx.Process(target=_child, args=(test_db, tag, 8, 63, q)) for _ in range(4)]
    for p in procs:
        p.start()
    errors = sum(q.get(timeout=120) for _ in procs)
    for p in procs:
        p.join(timeout=30)
    assert errors == 0
    n = owner_db.execute("SELECT count(*) FROM app.audit_log WHERE action = 'conc_test' AND username = %s", (tag,)).fetchone()[0]
    assert n == 4 * 8 * 63


def test_pool_never_exceeds_its_limit(test_db):
    eng = db.make_engine(db.app_url(test_db), pool_size=5, max_overflow=5)
    state = {"out": 0, "max": 0}
    lock = threading.Lock()

    @event.listens_for(eng, "checkout")
    def _co(*_a):
        with lock:
            state["out"] += 1
            state["max"] = max(state["max"], state["out"])

    @event.listens_for(eng, "checkin")
    def _ci(*_a):
        with lock:
            state["out"] -= 1

    def work(_):
        with eng.begin() as c:
            c.execute(text("SELECT pg_sleep(0.02)"))

    with ThreadPoolExecutor(30) as ex:
        list(ex.map(work, range(120)))
    eng.dispose()
    assert 1 < state["max"] <= 10


def test_statement_timeout(test_db):
    c = app_connect(test_db)
    try:
        with pytest.raises(psycopg.errors.QueryCanceled):
            c.execute("SELECT pg_sleep(6)")
    finally:
        c.close()


def test_lock_timeout_gives_one_retry_then_503(test_db, owner_db, user_ids):
    holder = psycopg.connect(**initmod.superuser_conninfo(get_settings(), test_db))
    try:
        holder.execute("SELECT * FROM app.users WHERE username = 'cm.books' FOR UPDATE")
        attempts = {"n": 0}

        def fn(c):
            attempts["n"] += 1
            c.execute(text("UPDATE app.users SET display_name = display_name WHERE username = 'cm.books'"))

        t0 = time.monotonic()
        with pytest.raises(db.DatabaseUnavailable):
            db.write(fn)
        assert attempts["n"] == 2
        assert 3.5 < time.monotonic() - t0 < 10
    finally:
        holder.rollback()
        holder.close()


def test_deadlock_is_retried_once(test_db):
    calls = {"n": 0}

    def fn(c):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OperationalError("UPDATE", {}, psycopg.errors.DeadlockDetected("simulated deadlock"))
        return "ok"

    assert db.write(fn) == "ok"
    assert calls["n"] == 2
    calls["n"] = 0

    def always(c):
        calls["n"] += 1
        raise OperationalError("UPDATE", {}, psycopg.errors.DeadlockDetected("simulated deadlock"))

    with pytest.raises(db.DatabaseUnavailable):
        db.write(always)
    assert calls["n"] == 2


def test_role_change_and_audit_row_are_one_commit(client, tokens, owner_db):
    name = f"rc_{uuid.uuid4().hex[:6]}"
    r = client.post("/api/admin/users", json={"username": name, "display_name": "RC", "role": "analyst", "password": "Good#Pass1"},
                    headers={**bearer(tokens, "admin"), "Origin": ORIGIN})
    assert r.status_code == 200, r.text
    uid = r.json()["user"]["id"]
    r = client.patch(f"/api/admin/users/{uid}", json={"role": "regional_manager", "region": "Asia"},
                     headers={**bearer(tokens, "admin"), "Origin": ORIGIN})
    assert r.status_code == 200, r.text
    x_user = owner_db.execute("SELECT xmin::text FROM app.users WHERE id = %s", (uid,)).fetchone()[0]
    x_audit = owner_db.execute("""SELECT xmin::text FROM app.audit_log WHERE action = 'user_change'
                                  AND detail->>'target' = %s AND detail->>'op' = 'update'""", (name,)).fetchone()[0]
    assert x_user == x_audit


def test_audit_buffer_loses_no_rows_under_load(owner_db):
    tag = f"buf_{uuid.uuid4().hex[:8]}"
    stop = threading.Event()

    def flusher():
        while not stop.is_set():
            audit.flush()
            time.sleep(0.01)

    th = threading.Thread(target=flusher)
    th.start()
    dropped_before = audit.buffer.dropped

    def add(_):
        for _i in range(500):
            audit.buffer.add("query", username=tag)

    with ThreadPoolExecutor(10) as ex:
        list(ex.map(add, range(10)))
    stop.set()
    th.join()
    audit.flush()
    n = owner_db.execute("SELECT count(*) FROM app.audit_log WHERE username = %s", (tag,)).fetchone()[0]
    assert n + (audit.buffer.dropped - dropped_before) == 5000
    assert audit.buffer.dropped == dropped_before


def test_keyset_pagination_is_stable_during_inserts(client, tokens, owner_db):
    tag = f"ks_{uuid.uuid4().hex[:6]}"
    for i in range(30):
        audit.record_now("ks_test", username=tag, detail={"i": i})
    seen: list[int] = []
    before = None
    h = bearer(tokens, "admin")
    while True:
        params = {"limit": 7, "action": "ks_test", "username": tag}
        if before:
            params["before_id"] = before
        page = client.get("/api/admin/audit", params=params, headers=h).json()
        seen += [r["id"] for r in page["rows"]]
        audit.record_now("ks_test", username=tag, detail={"late": True})  # new rows during paging
        before = page["next_before_id"]
        if not before:
            break
    original = [r[0] for r in owner_db.execute(
        "SELECT id FROM app.audit_log WHERE action = 'ks_test' AND username = %s AND detail ? 'i' ORDER BY id DESC", (tag,)).fetchall()]
    assert len(seen) == len(set(seen))
    assert [i for i in seen if i in set(original)] == original
