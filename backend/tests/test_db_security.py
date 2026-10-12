"""The database layer, tested as panorama_app (the api role)."""

from __future__ import annotations

import uuid

import psycopg
import pytest

from app.data.schema import classification
from tests.conftest import app_connect


def _as(conn: psycopg.Connection, uid: int | None):
    cur = conn.cursor()
    if uid is not None:
        cur.execute("SELECT set_config('app.user_id', %s, true)", (str(uid),))
    return cur


def _expect_error(conn, sql, params=None):
    with pytest.raises(psycopg.Error):
        conn.execute(sql, params)
    conn.rollback()


def test_no_user_sees_nothing_on_new_and_reused_connections(test_db, user_ids):
    c = app_connect(test_db)
    try:
        assert c.execute("SELECT count(*) FROM sales.orders_scoped").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM rag.documents").fetchone()[0] == 0
        c.rollback()
        # Reused connection: after a set_config with is_local, the value is '' (not NULL)
        c.execute("SELECT set_config('app.user_id', %s, true)", (str(user_ids["exec"]),))
        assert c.execute("SELECT count(*) FROM sales.orders_scoped").fetchone()[0] == 10_000
        c.commit()
        assert c.execute("SELECT coalesce(current_setting('app.user_id', true), '')").fetchone()[0] == ""
        assert c.execute("SELECT count(*) FROM sales.orders_scoped").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM rag.documents").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM app.current_scope()").fetchone()[0] == 0
    finally:
        c.close()


def test_load_principal_setting_ends_with_the_statement(test_db, user_ids):
    c = app_connect(test_db)
    c.autocommit = True
    try:
        r = c.execute("SELECT username, db_scope_key FROM app.load_principal(%s)", (user_ids["rm.asia"],)).fetchone()
        assert r == ("rm.asia", "region:Asia")
        assert c.execute("SELECT coalesce(current_setting('app.user_id', true), '')").fetchone()[0] == ""
        assert c.execute("SELECT count(*) FROM sales.orders_scoped").fetchone()[0] == 0
        # The scope key comes from the user row in the database, for the user in the argument only.
        assert c.execute("SELECT db_scope_key FROM app.load_principal(%s)", (user_ids["ops"],)).fetchone()[0] == "all:nofin"
    finally:
        c.close()


def test_scoped_rows_and_columns(app_db, user_ids):
    cur = _as(app_db, user_ids["rm.asia"])
    assert cur.execute("SELECT array_agg(DISTINCT region) FROM sales.orders_scoped").fetchone()[0] == ["Asia"]
    app_db.rollback()
    cur = _as(app_db, user_ids["cm.electronics"])
    assert cur.execute("SELECT array_agg(DISTINCT category) FROM sales.orders_scoped").fetchone()[0] == ["Electronics"]
    app_db.rollback()
    cur = _as(app_db, user_ids["ops"])
    r = cur.execute("""SELECT count(*) FILTER (WHERE cost IS NOT NULL OR profit IS NOT NULL OR profit_margin_pct IS NOT NULL
                       OR is_loss IS NOT NULL OR profit_after_shipping IS NOT NULL), count(*) FROM sales.orders_scoped""").fetchone()
    assert r == (0, 10_000)
    app_db.rollback()
    cur = _as(app_db, user_ids["analyst"])
    r = cur.execute("SELECT count(*) FILTER (WHERE customer_id LIKE 'C-%%'), count(*) FILTER (WHERE customer_id LIKE 'CUST-%%') FROM sales.orders_scoped").fetchone()
    assert r == (10_000, 0)
    app_db.rollback()


def test_bad_users_see_nothing(owner_db, test_db):
    tag = uuid.uuid4().hex[:6]
    owner_db.execute("INSERT INTO app.users (username, display_name, password_hash, role, is_active) VALUES (%s, 'x', 'x', 'executive', false)",
                     (f"inactive_{tag}",))
    inactive = owner_db.execute("SELECT id FROM app.users WHERE username = %s", (f"inactive_{tag}",)).fetchone()[0]
    # A manager without a region/category cannot exist (CHECK), so test the function with a disabled CHECK copy:
    owner_db.execute("ALTER TABLE app.users DROP CONSTRAINT ck_users_region_iff_rm")
    owner_db.execute("ALTER TABLE app.users DROP CONSTRAINT ck_users_category_iff_cm")
    try:
        owner_db.execute("INSERT INTO app.users (username, display_name, password_hash, role) VALUES (%s, 'x', 'x', 'regional_manager')", (f"rm_noreg_{tag}",))
        owner_db.execute("INSERT INTO app.users (username, display_name, password_hash, role) VALUES (%s, 'x', 'x', 'category_manager')", (f"cm_nocat_{tag}",))
        ids = [owner_db.execute("SELECT id FROM app.users WHERE username = %s", (u,)).fetchone()[0] for u in (f"rm_noreg_{tag}", f"cm_nocat_{tag}")]
        c = app_connect(test_db)
        try:
            for uid in [inactive] + ids:
                cur = _as(c, uid)
                assert cur.execute("SELECT count(*) FROM sales.orders_scoped").fetchone()[0] == 0
                assert cur.execute("SELECT count(*) FROM rag.documents").fetchone()[0] == 0
                assert cur.execute("SELECT app.current_scope_key()").fetchone()[0] is None
                c.rollback()
        finally:
            c.close()
    finally:
        owner_db.execute("DELETE FROM app.users WHERE username IN (%s, %s)", (f"rm_noreg_{tag}", f"cm_nocat_{tag}"))
        owner_db.execute("ALTER TABLE app.users ADD CONSTRAINT ck_users_region_iff_rm CHECK ((role = 'regional_manager') = (region IS NOT NULL))")
        owner_db.execute("ALTER TABLE app.users ADD CONSTRAINT ck_users_category_iff_cm CHECK ((role = 'category_manager') = (category IS NOT NULL))")


def test_every_flat_column_is_classified(owner_db):
    cols = [r[0] for r in owner_db.execute(
        "SELECT attname FROM pg_attribute WHERE attrelid = 'sales.orders_flat'::regclass AND attnum > 0 AND NOT attisdropped").fetchall()]
    assert cols
    missing = [c for c in cols if classification(c) is None]
    assert missing == []


def test_star_schema_rejects_bad_rows(owner_db):
    base = owner_db.execute("SELECT * FROM sales.fact_orders LIMIT 1").fetchone()
    cols = [d.name for d in owner_db.execute("SELECT * FROM sales.fact_orders LIMIT 0").description]
    row = dict(zip(cols, base))
    bad_cases = [
        {"order_status": "Lost"}, {"customer_segment": "Gold"}, {"quantity": 0}, {"discount": 0.95},
        {"revenue": float(row["revenue"]) + 1}, {"profit": float(row["profit"]) + 1}, {"geo_id": 999},
        {"shipping_method": "Drone"}, {"payment_method": "Gold"},
    ]
    for i, case in enumerate(bad_cases):
        r = {**row, **case, "order_id": f"ORD-9{i:06d}"}
        with pytest.raises(psycopg.Error):
            with owner_db.transaction():
                owner_db.execute(f"INSERT INTO sales.fact_orders ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                                 [r[c] for c in cols])


@pytest.mark.parametrize("sql", [
    "SELECT * FROM sales.fact_orders LIMIT 1",
    "SELECT * FROM sales.dim_customer LIMIT 1",
    "SELECT * FROM sales.orders_flat LIMIT 1",
    "SELECT * FROM sales.scope_rows(true, NULL, true, NULL, true, true) LIMIT 1",
    "SELECT * FROM app.audit_log LIMIT 1",
    "UPDATE sales.meta SET dataset = 'x'",
    "DELETE FROM rag.documents",
    "UPDATE rag.documents SET title = 'x'",
    "DELETE FROM app.chat_messages",
    "DELETE FROM app.chat_sessions",
    "DELETE FROM app.feedback",
    "DELETE FROM app.users",
    "CREATE TABLE app.x (id int)",
    "CREATE TABLE public.x (id int)",
    "CREATE TEMP TABLE t (id int)",
    "DROP VIEW sales.orders_scoped",
    "ALTER TABLE app.users DISABLE ROW LEVEL SECURITY",
    "SET ROLE panorama_owner",
])
def test_app_role_cannot(app_db, sql, user_ids):
    _as(app_db, user_ids["admin"])
    _expect_error(app_db, sql)


def test_chat_rows_are_private(app_db, test_db, user_ids):
    a, b = user_ids["rm.asia"], user_ids["rm.europe"]
    cur = _as(app_db, a)
    sid = cur.execute("INSERT INTO app.chat_sessions (user_id, title, scope_fp) VALUES (%s, 't', 'fp') RETURNING id", (a,)).fetchone()[0]
    cur.execute("INSERT INTO app.chat_messages (session_id, user_id, role, content, turn_id) VALUES (%s, %s, 'user', 'secret', %s)",
                (sid, a, str(uuid.uuid4())))
    app_db.commit()
    c2 = app_connect(test_db)
    try:
        cur2 = _as(c2, b)
        assert cur2.execute("SELECT count(*) FROM app.chat_sessions WHERE id = %s", (sid,)).fetchone()[0] == 0
        assert cur2.execute("SELECT count(*) FROM app.chat_messages WHERE session_id = %s", (sid,)).fetchone()[0] == 0
        # B cannot write into A's session (as itself or as A)
        for uid in (b, a):
            with pytest.raises(psycopg.Error):
                cur2.execute("INSERT INTO app.chat_messages (session_id, user_id, role, content, turn_id) VALUES (%s, %s, 'user', 'x', %s)",
                             (sid, uid, str(uuid.uuid4())))
            c2.rollback()
            cur2 = _as(c2, b)
        assert cur2.execute("UPDATE app.chat_sessions SET title = 'hacked' WHERE id = %s", (sid,)).rowcount == 0
        c2.rollback()
    finally:
        c2.close()


def test_audit_insert_only(app_db, user_ids):
    from app import audit
    audit.record_now("test_event", username="pytest")
    audit.buffer.add("query", username="pytest")
    assert audit.flush() >= 1
    _as(app_db, user_ids["admin"])
    _expect_error(app_db, "SELECT count(*) FROM app.audit_log")


def test_role_facts(superuser_db):
    c = superuser_db
    r = c.execute("SELECT rolbypassrls, rolsuper, rolcreaterole, rolcreatedb, rolcanlogin FROM pg_roles WHERE rolname = 'panorama_app'").fetchone()
    assert r == (False, False, False, False, True)
    assert c.execute("SELECT rolcanlogin FROM pg_roles WHERE rolname = 'panorama_owner'").fetchone()[0] is False
    owned = c.execute("SELECT count(*) FROM pg_class WHERE relowner = 'panorama_app'::regrole").fetchone()[0]
    assert owned == 0
    rls = dict(c.execute("""SELECT n.nspname || '.' || c.relname, c.relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                            WHERE (n.nspname, c.relname) IN (('rag','documents'), ('app','chat_sessions'), ('app','chat_messages'), ('app','feedback'))""").fetchall())
    assert rls == {"rag.documents": True, "app.chat_sessions": True, "app.chat_messages": True, "app.feedback": True}


EXPECTED_TABLE_GRANTS = {
    ("app", "users"): {"SELECT", "INSERT", "UPDATE"},
    ("app", "chat_sessions"): {"SELECT", "INSERT", "UPDATE"},
    ("app", "chat_messages"): {"SELECT", "INSERT", "UPDATE"},
    ("app", "feedback"): {"SELECT", "INSERT", "UPDATE"},
    ("app", "worker_stats"): {"SELECT", "INSERT", "UPDATE"},
    ("app", "audit_log"): {"INSERT"},
    ("sales", "orders_scoped"): {"SELECT"},
    ("sales", "meta"): {"SELECT"},
    ("rag", "documents"): {"SELECT"},
    ("rag", "manifest"): {"SELECT"},
}
EXPECTED_FUNCTIONS = {
    "app.current_scope", "app.current_scope_key", "sales.current_scope_rows", "app.admin_audit",
    "app.admin_audit_summary", "app.admin_ai_quality", "app.admin_feedback", "app.load_principal",
}


def test_grants_equal_allowlist(superuser_db):
    c = superuser_db
    rows = c.execute("""SELECT table_schema, table_name, privilege_type FROM information_schema.role_table_grants
                        WHERE grantee = 'panorama_app'""").fetchall()
    got: dict = {}
    for s, t, p in rows:
        got.setdefault((s, t), set()).add(p)
    assert got == EXPECTED_TABLE_GRANTS
    funcs = {f"{s}.{n}" for s, n in c.execute("""
        SELECT n.nspname, p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname IN ('app', 'sales', 'rag') AND has_function_privilege('panorama_app', p.oid, 'EXECUTE')""").fetchall()}
    assert funcs == EXPECTED_FUNCTIONS
    assert not c.execute("SELECT has_function_privilege('panorama_app', 'sales.scope_rows(boolean,text,boolean,text,boolean,boolean)', 'EXECUTE')").fetchone()[0]
    assert not c.execute("SELECT has_database_privilege('panorama_app', current_database(), 'TEMPORARY')").fetchone()[0]


def test_rls_policies_use_initplans(app_db, user_ids):
    cur = _as(app_db, user_ids["rm.asia"])
    plan = "\n".join(r[0] for r in cur.execute("EXPLAIN SELECT id FROM rag.documents WHERE kind = 'summary'").fetchall())
    assert "InitPlan" in plan
    assert "SubPlan" not in plan
    app_db.rollback()


def test_admin_functions_need_admin(app_db, user_ids):
    cur = _as(app_db, user_ids["exec"])
    assert cur.execute("SELECT count(*) FROM app.admin_audit(NULL, 10, NULL, NULL, NULL, NULL)").fetchone()[0] == 0
    app_db.rollback()
    cur = _as(app_db, user_ids["admin"])
    cur.execute("SELECT count(*) FROM app.admin_audit(NULL, 10, NULL, NULL, NULL, NULL)").fetchone()
    app_db.rollback()
