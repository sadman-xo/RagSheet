"""Hybrid retrieval in one SQL query (target < 100 ms), filtered by RLS for the user's scope.

Dense list (pgvector cosine) and keyword list (full-text), each with the metadata filters inside, merged with
Reciprocal Rank Fusion: score = 1/(60 + r_dense) + 1/(60 + r_kw).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text

from app.db import engine as db
from app.rag.embedder import query_vector, to_pg

RRF_K = 60
LIST_SIZE = 40

SQL = text(f"""
WITH q AS (SELECT CAST(:qv AS vector) AS v, websearch_to_tsquery('english', :qt) AS ts),
dense AS (
    SELECT d.id, row_number() OVER (ORDER BY d.embedding <=> q.v) AS r
    FROM rag.documents d, q
    WHERE (CAST(:kinds AS text[]) IS NULL OR d.kind = ANY(CAST(:kinds AS text[])))
    ORDER BY d.embedding <=> q.v
    LIMIT {LIST_SIZE}
),
kw AS (
    SELECT d.id, row_number() OVER (ORDER BY ts_rank_cd(d.tsv, q.ts) DESC) AS r
    FROM rag.documents d, q
    WHERE (CAST(:kinds AS text[]) IS NULL OR d.kind = ANY(CAST(:kinds AS text[])))
      AND d.tsv @@ q.ts
    ORDER BY ts_rank_cd(d.tsv, q.ts) DESC
    LIMIT {LIST_SIZE}
)
SELECT d.id, d.doc_key, d.kind, d.title, d.body, d.spec, d.deep_link, d.coverage_region, d.coverage_category,
       d.is_financial, d.meta,
       coalesce(1.0 / ({RRF_K} + dense.r), 0) + coalesce(1.0 / ({RRF_K} + kw.r), 0) AS score,
       dense.r AS dense_rank, kw.r AS kw_rank
FROM dense FULL OUTER JOIN kw ON dense.id = kw.id
JOIN rag.documents d ON d.id = coalesce(dense.id, kw.id)
ORDER BY score DESC, d.id
LIMIT :k
""")


@dataclass
class Hit:
    id: int
    doc_key: str
    kind: str
    title: str
    body: str
    spec: dict | None
    deep_link: str | None
    coverage_region: str | None
    coverage_category: str | None
    is_financial: bool
    meta: dict
    score: float
    dense_rank: int | None
    kw_rank: int | None


def retrieve(user_id: int, question: str, k: int = 6, kinds: list[str] | None = None) -> list[Hit]:
    qv = to_pg(query_vector(question))
    with db.scoped(user_id) as c:
        c.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
        rows = c.execute(SQL, {"qv": qv, "qt": question[:300], "kinds": kinds, "k": k}).mappings().all()
    return [Hit(**{key: r[key] for key in Hit.__dataclass_fields__}) for r in rows]
