"""Initial schema: app, sales (star schema + scope functions), rag; grants, RLS, admin functions.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-07

The tables come from app.db.models (one initial migration; `alembic check` proves no drift).
Every later schema change needs its own migration with explicit operations.
"""

from __future__ import annotations

from alembic import op

from app.data import vocab
from app.data.schema import FLAT_COLUMNS, scope_rows_return_list, scope_rows_select_list
from app.db import models

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

APP_ROLE = "panorama_app"


def _role_case(mapping: dict[str, str]) -> str:
    whens = " ".join(f"WHEN '{role}' THEN {value}" for role, value in mapping.items())
    return f"CASE u.role {whens} END"


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS app")
    op.execute("CREATE SCHEMA IF NOT EXISTS sales")
    op.execute("CREATE SCHEMA IF NOT EXISTS rag")
    bind = op.get_bind()
    for table in models.CREATE_ORDER:
        table.create(bind)

    # ------------------------------------------------------------------
    # Owner-only wide view of the star schema, with derived columns
    # ------------------------------------------------------------------
    op.execute(f"""
CREATE VIEW sales.orders_flat AS
SELECT
    f.order_id,
    d.order_date,
    d.year,
    d.quarter,
    d.month,
    d.year_month::text AS year_month,
    (d.year::text || '-Q' || d.quarter::text) AS year_quarter,
    d.season,
    d.day_of_week,
    c.customer_id::text AS customer_id,
    c.customer_key::text AS customer_key,
    f.customer_gender,
    f.customer_segment,
    g.region,
    g.country,
    p.category,
    p.sub_category,
    p.product_name,
    f.unit_price,
    f.quantity,
    f.discount,
    f.revenue,
    f.cost,
    f.profit,
    f.profit_margin_pct,
    f.shipping_cost,
    f.shipping_method,
    f.shipping_days,
    f.payment_method,
    f.order_status,
    round(f.unit_price * f.quantity, 2)::numeric(12,2) AS list_value,
    (round(f.unit_price * f.quantity, 2) - f.revenue)::numeric(12,2) AS discount_amount,
    (round(f.discount * 100)::int)::text || '%' AS discount_band,
    {vocab.price_band_sql('f.unit_price')} AS price_band,
    {vocab.shipping_days_band_sql('f.shipping_days')} AS shipping_days_band,
    f.order_status NOT IN ({vocab.sql_in_list(vocab.NET_EXCLUDED_STATUSES)}) AS is_net,
    f.order_status IN ({vocab.sql_in_list(vocab.FULFILLED_STATUSES)}) AS is_fulfilled,
    f.profit < 0 AS is_loss,
    (f.profit - f.shipping_cost)::numeric(12,2) AS profit_after_shipping
FROM sales.fact_orders f
JOIN sales.dim_date d ON d.date_key = f.date_key
JOIN sales.dim_geography g ON g.geo_id = f.geo_id
JOIN sales.dim_product p ON p.product_id = f.product_id
JOIN sales.dim_customer c ON c.customer_sk = f.customer_sk
""")

    # ------------------------------------------------------------------
    # The only copy of the row predicate and the column masks.
    # Never an IS NULL test: an empty value can never mean "all".
    # ------------------------------------------------------------------
    op.execute(f"""
CREATE FUNCTION sales.scope_rows(
    p_all_regions boolean, p_region text, p_all_categories boolean, p_category text,
    p_financial boolean, p_pii_raw boolean)
RETURNS TABLE ({scope_rows_return_list()})
LANGUAGE sql STABLE
SET search_path = pg_catalog, pg_temp
AS $fn$
SELECT
    {scope_rows_select_list()}
FROM sales.orders_flat o
WHERE (p_all_regions OR o.region = p_region)
  AND (p_all_categories OR o.category = p_category)
$fn$
""")

    # ------------------------------------------------------------------
    # The database scope: calculated from the users row, independently of the api.
    # No row if the setting is missing, the user is inactive, the role is unknown,
    # or a manager has no region / category.
    # ------------------------------------------------------------------
    all_regions = _role_case({"admin": "true", "executive": "true", "regional_manager": "false",
                              "category_manager": "true", "analyst": "true", "operations": "true"})
    all_categories = _role_case({"admin": "true", "executive": "true", "regional_manager": "true",
                                 "category_manager": "false", "analyst": "true", "operations": "true"})
    financial = _role_case({"admin": "true", "executive": "true", "regional_manager": "true",
                            "category_manager": "true", "analyst": "true", "operations": "false"})
    pii_raw = _role_case({"admin": "true", "executive": "true", "regional_manager": "true",
                          "category_manager": "true", "analyst": "false", "operations": "true"})
    scope_key = _role_case({"admin": "'all:full'", "executive": "'all:full'", "analyst": "'all:pseudo'",
                            "operations": "'all:nofin'", "regional_manager": "'region:' || u.region",
                            "category_manager": "'category:' || u.category"})
    op.execute(f"""
CREATE FUNCTION app.current_scope()
RETURNS TABLE (user_id bigint, role text, all_regions boolean, region text, all_categories boolean,
               category text, financial boolean, pii_raw boolean, scope_key text)
LANGUAGE sql STABLE SECURITY DEFINER ROWS 1
SET search_path = pg_catalog, pg_temp
AS $fn$
SELECT u.id,
       u.role,
       {all_regions},
       CASE WHEN u.role = 'regional_manager' THEN u.region END,
       {all_categories},
       CASE WHEN u.role = 'category_manager' THEN u.category END,
       {financial},
       {pii_raw},
       {scope_key}
FROM app.users u
WHERE u.id = NULLIF(pg_catalog.current_setting('app.user_id', true), '')::bigint
  AND u.is_active
  AND u.role IN ({vocab.sql_in_list(vocab.ROLES)})
  AND (u.role <> 'regional_manager' OR u.region IS NOT NULL)
  AND (u.role <> 'category_manager' OR u.category IS NOT NULL)
$fn$
""")
    op.execute("""
CREATE FUNCTION app.current_scope_key()
RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $fn$ SELECT s.scope_key FROM app.current_scope() s $fn$
""")

    # PostgreSQL checks EXECUTE on functions in a view as the caller. Thus the view calls one
    # no-argument SECURITY DEFINER wrapper: the app can run it, but it returns only the caller's own scope.
    # The app has no EXECUTE privilege on sales.scope_rows.
    op.execute(f"""
CREATE FUNCTION sales.current_scope_rows()
RETURNS TABLE ({scope_rows_return_list()})
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $fn$
SELECT r.*
FROM app.current_scope() s
CROSS JOIN LATERAL sales.scope_rows(s.all_regions, s.region, s.all_categories, s.category, s.financial, s.pii_raw) r
$fn$
""")
    cols = ", ".join(c.name for c in FLAT_COLUMNS)
    op.execute(f"""
CREATE VIEW sales.orders_scoped WITH (security_barrier = true) AS
SELECT {cols} FROM sales.current_scope_rows()
""")

    # ------------------------------------------------------------------
    # Row-level security. Only uncorrelated scalar subqueries (InitPlans), never per-row calls.
    # ENABLE (not FORCE): panorama_app owns nothing and is NOBYPASSRLS, so the policies always apply to it.
    # ------------------------------------------------------------------
    op.execute("ALTER TABLE rag.documents ENABLE ROW LEVEL SECURITY")
    op.execute(f"""
CREATE POLICY documents_scope ON rag.documents FOR SELECT TO {APP_ROLE}
USING (
    (SELECT s.user_id FROM app.current_scope() s) IS NOT NULL
    AND (NOT is_financial OR coalesce((SELECT s.financial FROM app.current_scope() s), false))
    AND (
        kind IN ('knowledge', 'entity')
        OR (
            (coalesce((SELECT s.all_regions FROM app.current_scope() s), false)
                OR coverage_region = (SELECT s.region FROM app.current_scope() s))
            AND (coalesce((SELECT s.all_categories FROM app.current_scope() s), false)
                OR coverage_category = (SELECT s.category FROM app.current_scope() s))
        )
    )
)
""")
    for table in ("chat_sessions", "chat_messages", "feedback"):
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""
CREATE POLICY {table}_owner ON app.{table} FOR ALL TO {APP_ROLE}
USING (user_id = (SELECT s.user_id FROM app.current_scope() s))
WITH CHECK (user_id = (SELECT s.user_id FROM app.current_scope() s))
""")

    # ------------------------------------------------------------------
    # Admin read functions (check role = 'admin' in the database scope)
    # ------------------------------------------------------------------
    op.execute("""
CREATE FUNCTION app.admin_audit(
    p_before_id bigint, p_limit integer, p_action text, p_username text,
    p_from timestamptz, p_to timestamptz)
RETURNS SETOF app.audit_log
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $fn$
SELECT a.*
FROM app.audit_log a
WHERE (SELECT s.role FROM app.current_scope() s) = 'admin'
  AND (p_before_id IS NULL OR a.id < p_before_id)
  AND (p_action IS NULL OR a.action = p_action)
  AND (p_username IS NULL OR a.username = p_username)
  AND (p_from IS NULL OR a.ts >= p_from)
  AND (p_to IS NULL OR a.ts < p_to)
ORDER BY a.id DESC
LIMIT least(greatest(coalesce(p_limit, 100), 1), 1000)
$fn$
""")
    op.execute("""
CREATE FUNCTION app.admin_audit_summary(p_hours integer)
RETURNS TABLE (action text, n bigint)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $fn$
SELECT a.action, count(*)
FROM app.audit_log a
WHERE (SELECT s.role FROM app.current_scope() s) = 'admin'
  AND a.ts >= now() - make_interval(hours => least(greatest(coalesce(p_hours, 24), 1), 24 * 90))
GROUP BY a.action
ORDER BY 2 DESC
$fn$
""")
    op.execute("""
CREATE FUNCTION app.admin_ai_quality(p_days integer)
RETURNS TABLE (mode text, answers bigint, thumbs_up bigint, thumbs_down bigint, avg_total_ms double precision)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $fn$
SELECT coalesce(m.mode, 'unknown'),
       count(*),
       count(*) FILTER (WHERE f.rating = 1),
       count(*) FILTER (WHERE f.rating = -1),
       avg((m.timings ->> 'total_ms')::double precision)
FROM app.chat_messages m
LEFT JOIN app.feedback f ON f.message_id = m.id
WHERE (SELECT s.role FROM app.current_scope() s) = 'admin'
  AND m.role = 'assistant'
  AND m.created_at >= now() - make_interval(days => least(greatest(coalesce(p_days, 30), 1), 365))
GROUP BY 1
ORDER BY 2 DESC
$fn$
""")
    op.execute("""
CREATE FUNCTION app.admin_feedback(p_limit integer)
RETURNS TABLE (message_id bigint, username text, role text, rating smallint, comment text,
               question text, answer text, mode text, created_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $fn$
SELECT m.id, u.username, u.role, f.rating, f.comment,
       (SELECT q.content FROM app.chat_messages q
         WHERE q.session_id = m.session_id AND q.role = 'user' AND q.turn_id = m.turn_id LIMIT 1),
       m.content, m.mode, f.created_at
FROM app.feedback f
JOIN app.chat_messages m ON m.id = f.message_id
JOIN app.users u ON u.id = f.user_id
WHERE (SELECT s.role FROM app.current_scope() s) = 'admin'
ORDER BY f.created_at DESC
LIMIT least(greatest(coalesce(p_limit, 50), 1), 500)
$fn$
""")

    # ------------------------------------------------------------------
    # Grants: an allowlist (test_db_security compares it)
    # ------------------------------------------------------------------
    functions = [
        "sales.scope_rows(boolean, text, boolean, text, boolean, boolean)",
        "app.current_scope()",
        "app.current_scope_key()",
        "sales.current_scope_rows()",
        "app.admin_audit(bigint, integer, text, text, timestamptz, timestamptz)",
        "app.admin_audit_summary(integer)",
        "app.admin_ai_quality(integer)",
        "app.admin_feedback(integer)",
    ]
    for fn in functions:
        op.execute(f"REVOKE ALL ON FUNCTION {fn} FROM PUBLIC")
    for fn in functions[1:]:
        op.execute(f"GRANT EXECUTE ON FUNCTION {fn} TO {APP_ROLE}")

    op.execute(f"GRANT USAGE ON SCHEMA app, sales, rag TO {APP_ROLE}")
    op.execute(f"GRANT SELECT ON sales.orders_scoped, sales.meta, rag.documents, rag.manifest TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON app.users, app.chat_sessions, app.chat_messages, app.feedback, app.worker_stats TO {APP_ROLE}")
    op.execute(f"GRANT INSERT ON app.audit_log TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS rag CASCADE")
    op.execute("DROP SCHEMA IF EXISTS sales CASCADE")
    op.execute("DROP SCHEMA IF EXISTS app CASCADE")
