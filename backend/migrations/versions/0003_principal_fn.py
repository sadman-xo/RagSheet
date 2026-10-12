"""Principal read in one statement: app.load_principal(uid) sets the transaction-local app.user_id and reads the
user row, app.current_scope_key(), and the data version.

The api calls it in autocommit mode, so the statement is the transaction: the setting ends with the statement.
This replaces BEGIN + set_config + SELECT + COMMIT (four round trips) on every request. SECURITY INVOKER: the
function has the privileges of panorama_app (SELECT on app.users and sales.meta), no more.

Revision ID: 0003_principal_fn
Revises: 0002_rag_policy_insights
Create Date: 2026-10-08
"""

from __future__ import annotations

from alembic import op

revision = "0003_principal_fn"
down_revision = "0002_rag_policy_insights"
branch_labels = None
depends_on = None

APP_ROLE = "panorama_app"


def upgrade() -> None:
    op.execute("""
CREATE FUNCTION app.load_principal(p_uid bigint)
RETURNS TABLE (id bigint, username text, display_name text, role text, region text, category text,
               is_active boolean, token_version integer, is_synthetic boolean, db_scope_key text,
               data_version text, dataset text, row_count bigint, min_date date, max_date date)
LANGUAGE plpgsql VOLATILE SECURITY INVOKER
SET search_path = pg_catalog, pg_temp
AS $fn$
BEGIN
    PERFORM pg_catalog.set_config('app.user_id', p_uid::text, true);
    RETURN QUERY
    SELECT u.id, u.username, u.display_name, u.role, u.region, u.category, u.is_active, u.token_version,
           u.is_synthetic, app.current_scope_key(), m.data_version, m.dataset, m.row_count, m.min_date, m.max_date
    FROM app.users u
    LEFT JOIN sales.meta m ON m.id = 1
    WHERE u.id = p_uid;
END
$fn$
""")
    op.execute("REVOKE ALL ON FUNCTION app.load_principal(bigint) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION app.load_principal(bigint) TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION app.load_principal(bigint)")
