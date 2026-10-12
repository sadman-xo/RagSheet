"""RAG fixture corpus for the test template database (deterministic fake embedder)."""

from __future__ import annotations

from app.rag.documents import build_documents
from app.rag.embedder import HashEmbedder
from app.rag.indexer import write_corpus


def build(conn, data_version: str) -> int:
    docs = build_documents()
    vecs = HashEmbedder().embed_passages([d.embed_text for d in docs])
    return write_corpus(conn, docs, vecs, f"fixture:{data_version}", threshold=50_000)
