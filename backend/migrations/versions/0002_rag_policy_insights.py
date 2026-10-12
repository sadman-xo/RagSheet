"""RAG policy: insight documents are visible in every scope (they have no numbers; they are rendered on the
user's own scope file at retrieval).

Revision ID: 0002_rag_policy_insights
Revises: 0001_initial
Create Date: 2026-10-08
"""

from __future__ import annotations

from alembic import op

revision = "0002_rag_policy_insights"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _policy(always: str) -> str:
    return f"""
CREATE POLICY documents_scope ON rag.documents FOR SELECT TO panorama_app
USING (
    (SELECT s.user_id FROM app.current_scope() s) IS NOT NULL
    AND (NOT is_financial OR coalesce((SELECT s.financial FROM app.current_scope() s), false))
    AND (
        kind IN ({always})
        OR (
            (coalesce((SELECT s.all_regions FROM app.current_scope() s), false)
                OR coverage_region = (SELECT s.region FROM app.current_scope() s))
            AND (coalesce((SELECT s.all_categories FROM app.current_scope() s), false)
                OR coverage_category = (SELECT s.category FROM app.current_scope() s))
        )
    )
)
"""


def upgrade() -> None:
    op.execute("DROP POLICY documents_scope ON rag.documents")
    op.execute(_policy("'knowledge', 'entity', 'insight'"))


def downgrade() -> None:
    op.execute("DROP POLICY documents_scope ON rag.documents")
    op.execute(_policy("'knowledge', 'entity'"))
