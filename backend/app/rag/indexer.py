"""Build the RAG corpus in init (as panorama_owner).

corpus_hash = sha256(BUILD_ID, embedder ID, document content, data_version). If rag.manifest has the same
hash, init skips the build. Otherwise it embeds the documents and replaces all rows in one transaction
(readers see the old or the new corpus, never a mix), then runs VACUUM (ANALYZE). Above RAG_HNSW_THRESHOLD
documents, an HNSW index is created.
"""

from __future__ import annotations

import hashlib
import time

import psycopg
from psycopg.types.json import Jsonb

from app.config import Settings
from app.db.models import HNSW_INDEX_NAME
from app.rag.documents import Doc, build_documents, content_hash
from app.rag.embedder import Embedder, to_pg

COLUMNS = ("doc_key", "kind", "title", "body", "embed_text", "coverage_region", "coverage_category", "is_financial",
           "spec", "deep_link", "meta", "embedding")


def corpus_hash(build_id: str, embedder_id: str, data_version: str) -> str:
    h = hashlib.sha256()
    for part in (build_id, embedder_id, content_hash(), data_version):
        h.update(part.encode())
        h.update(b"|")
    return h.hexdigest()


def current_hash(conn: psycopg.Connection) -> str | None:
    row = conn.execute("SELECT corpus_hash FROM rag.manifest WHERE id = 1").fetchone()
    return row[0] if row else None


def write_corpus(conn: psycopg.Connection, docs: list[Doc], vectors, chash: str, threshold: int) -> int:
    with conn.transaction():
        conn.execute("DELETE FROM rag.documents")
        with conn.cursor() as cur, cur.copy(f"COPY rag.documents ({', '.join(COLUMNS)}) FROM STDIN") as cp:
            for d, v in zip(docs, vectors):
                cp.write_row((d.doc_key, d.kind, d.title, d.body, d.embed_text, d.coverage_region, d.coverage_category,
                              d.is_financial, Jsonb(d.spec) if d.spec is not None else None, d.deep_link, Jsonb(d.meta), to_pg(v)))
        conn.execute(
            """INSERT INTO rag.manifest (id, corpus_hash, version, doc_count, built_at) VALUES (1, %s, 1, %s, now())
               ON CONFLICT (id) DO UPDATE SET corpus_hash = EXCLUDED.corpus_hash, version = rag.manifest.version + 1,
               doc_count = EXCLUDED.doc_count, built_at = EXCLUDED.built_at""",
            (chash, len(docs)),
        )
    conn.execute("VACUUM (ANALYZE) rag.documents")
    ensure_hnsw(conn, len(docs), threshold)
    return len(docs)


def ensure_hnsw(conn: psycopg.Connection, count: int, threshold: int) -> bool:
    if count > threshold:
        conn.execute(f"CREATE INDEX IF NOT EXISTS {HNSW_INDEX_NAME} ON rag.documents USING hnsw (embedding vector_cosine_ops)")
        return True
    conn.execute(f"DROP INDEX IF EXISTS rag.{HNSW_INDEX_NAME}")
    return False


def build_if_needed(conn: psycopg.Connection, s: Settings, data_version: str, embedder: Embedder | None = None) -> bool:
    if embedder is None:
        from app.rag.embedder import FastEmbedder

        embedder = FastEmbedder(threads=None)
    chash = corpus_hash(s.build_id, embedder.model_id, data_version)
    if current_hash(conn) == chash:
        print(f"rag: corpus_hash is the same; skip ({chash[:12]})", flush=True)
        return False
    t0 = time.monotonic()
    docs = build_documents()
    vectors = embedder.embed_passages([d.embed_text for d in docs])
    n = write_corpus(conn, docs, vectors, chash, s.rag_hnsw_threshold)
    print(f"rag: built {n} documents in {time.monotonic() - t0:.1f} s ({chash[:12]})", flush=True)
    return True
