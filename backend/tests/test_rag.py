"""RAG corpus build and scoped retrieval (fake deterministic embedder)."""

from __future__ import annotations

import re
import time

import psycopg
import pytest
from sqlalchemy import text

from app import init as initmod
from app.config import get_settings
from app.data.scoped import ScopeFileCache
from app.db import engine as db
from app.rag import indexer
from app.rag.documents import build_documents
from app.rag.embedder import HashEmbedder, set_embedder, to_pg
from app.rag.render import render
from app.rag.retriever import SQL, retrieve
from app.security.deps import Principal, ScopedDataset
from app.security.policy import build_scope


@pytest.fixture(autouse=True, scope="module")
def fake_embedder():
    set_embedder(HashEmbedder())
    yield
    set_embedder(None)


def test_corpus_size_does_not_depend_on_orders(owner_db, dataset_100k):
    docs = build_documents()
    assert 400 <= len(docs) <= 650
    kinds = {k: sum(1 for d in docs if d.kind == k) for k in ("knowledge", "insight", "entity", "summary")}
    assert kinds["knowledge"] >= 50 and kinds["insight"] == 12 and kinds["entity"] == 111 and kinds["summary"] >= 250
    assert owner_db.execute("SELECT count(*) FROM rag.documents").fetchone()[0] == len(docs)
    with initmod.owner_connection(get_settings(), "panorama_test_100k") as c:
        indexer.build_if_needed(c, get_settings(), dataset_100k["data_version"], embedder=HashEmbedder())
        assert c.execute("SELECT count(*) FROM rag.documents").fetchone()[0] == len(docs)


def test_corpus_has_no_customer_ids_or_amounts():
    for d in build_documents():
        blob = f"{d.title} {d.body} {d.embed_text}"
        assert "CUST-" not in blob, d.doc_key
        assert not re.search(r"\d+\.\d{2}\b", blob), d.doc_key
        assert not re.search(r"\b\d{1,3}(,\d{3})+\b", blob), d.doc_key


def test_build_is_skipped_and_replaced_in_one_transaction(owner_db, data_version, test_db):
    s = get_settings()
    emb = HashEmbedder()
    v0 = owner_db.execute("SELECT version FROM rag.manifest").fetchone()[0]
    # a reader with a snapshot before the rebuild sees the old corpus
    reader = psycopg.connect(**initmod.superuser_conninfo(s, test_db))
    reader.execute("BEGIN ISOLATION LEVEL REPEATABLE READ")
    before = reader.execute("SELECT count(*), max(id) FROM rag.documents").fetchone()
    assert indexer.build_if_needed(owner_db, s, data_version, embedder=emb) is True
    assert indexer.build_if_needed(owner_db, s, data_version, embedder=emb) is False  # same hash
    v1 = owner_db.execute("SELECT version FROM rag.manifest").fetchone()[0]
    assert v1 == v0 + 1
    assert reader.execute("SELECT count(*), max(id) FROM rag.documents").fetchone() == before
    reader.rollback()
    reader.close()
    after = owner_db.execute("SELECT count(*), min(id) FROM rag.documents").fetchone()
    assert after[0] == before[0] and after[1] > before[1]


def _ds(username: str, user_ids, scope_cache, data_version) -> ScopedDataset:
    roles = {"rm.asia": ("regional_manager", "Asia", None), "cm.electronics": ("category_manager", None, "Electronics"),
             "ops": ("operations", None, None), "exec": ("executive", None, None), "analyst": ("analyst", None, None)}
    role, region, cat = roles[username]
    sc = build_scope(role, region, cat)
    p = Principal(id=user_ids[username], username=username, display_name=username, role=role, region=region, category=cat,
                  token_version=1, is_synthetic=False, db_scope_key=sc.scope_key, data_version=data_version, dataset="sample",
                  row_count=None, data_min=None, data_max=None)
    return ScopedDataset(principal=p, scope=sc, file=scope_cache.get(data_version, sc.scope_key))


def test_rls_filters_documents_by_scope(test_db, user_ids):
    hits = retrieve(user_ids["rm.asia"], "Europe sales in 2023 summary", k=20, kinds=["summary"])
    assert hits and all(h.coverage_region == "Asia" for h in hits)
    hits = retrieve(user_ids["cm.electronics"], "Clothing revenue in 2022", k=20, kinds=["summary"])
    assert hits and all(h.coverage_category == "Electronics" for h in hits)
    hits = retrieve(user_ids["ops"], "discount margin loss orders", k=40)
    assert hits and not any(h.is_financial for h in hits)
    hits = retrieve(user_ids["exec"], "discount margin loss orders", k=40)
    assert any(h.is_financial for h in hits)


def test_filtered_search_still_returns_k(test_db, user_ids):
    for user in ("rm.asia", "cm.electronics", "ops"):
        assert len(retrieve(user_ids[user], "revenue by year", k=6, kinds=["summary"])) == 6


def test_render_uses_the_users_scope_file(test_db, user_ids, scope_cache, data_version):
    ds = _ds("rm.asia", user_ids, scope_cache, data_version)
    hits = retrieve(user_ids["rm.asia"], "Asia in 2023", k=10, kinds=["summary"])
    rendered = render(hits, ds)
    asia = [r for r in rendered if r["title"] == "Asia in 2023"]
    assert asia and "585,921.31" in asia[0]["text"]
    ds_ops = _ds("ops", user_ids, scope_cache, data_version)
    for r in render(retrieve(user_ids["ops"], "margin by category", k=10), ds_ops):
        assert "margin" not in r["text"].lower() or not r["numbers"]


def test_explain_has_initplans_and_latency(test_db, user_ids):
    qv = to_pg(HashEmbedder().embed_query("revenue in Asia"))
    with db.scoped(user_ids["rm.asia"]) as c:
        plan = "\n".join(r[0] for r in c.execute(text("EXPLAIN " + SQL.text), {"qv": qv, "qt": "revenue Asia", "kinds": None, "k": 6}).all())
    assert "InitPlan" in plan
    assert "SubPlan" not in plan
    times = []
    for i in range(25):
        t0 = time.perf_counter()
        retrieve(user_ids["rm.asia"], f"revenue of category {i} in Asia", k=6)
        times.append(time.perf_counter() - t0)
    times.sort()
    assert times[int(len(times) * 0.95) - 1] < 0.1


def test_hnsw_above_threshold(owner_db, test_db, user_ids, data_version):
    s = get_settings()
    docs = build_documents()
    import numpy as np

    rng = np.random.default_rng(1)
    vecs = rng.normal(size=(len(docs), 384)).astype("float32")
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    indexer.write_corpus(owner_db, docs, vecs, "random", threshold=10)
    assert owner_db.execute("SELECT to_regclass('rag.ix_documents_embedding_hnsw')").fetchone()[0] is not None
    assert len(retrieve(user_ids["rm.asia"], "anything at all", k=6, kinds=["summary"])) == 6
    indexer.write_corpus(owner_db, docs, HashEmbedder().embed_passages([d.embed_text for d in docs]), "fixture-again", threshold=s.rag_hnsw_threshold)
    assert owner_db.execute("SELECT to_regclass('rag.ix_documents_embedding_hnsw')").fetchone()[0] is None
