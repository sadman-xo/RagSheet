from __future__ import annotations

import json
import shutil
from pathlib import Path

import duckdb
import pytest

from app.data import scopestore
from app.data.schema import FINANCIAL_COLUMNS
from app.data.scoped import ScopeFileCache, ScopeFileError
from app.data.scopestore import scope_keys

DEMO_USER_FOR_SCOPE = {
    "all:full": "exec", "all:pseudo": "analyst", "all:nofin": "ops",
    "region:Asia": "rm.asia", "region:Europe": "rm.europe", "region:Middle East": "rm.mideast",
    "region:North America": "rm.namerica",
    "category:Electronics": "cm.electronics", "category:Clothing": "cm.clothing",
    "category:Home & Kitchen": "cm.home", "category:Books & Media": "cm.books", "category:Beauty & Health": "cm.beauty",
}


@pytest.mark.parametrize("key", scope_keys())
def test_file_contains_only_its_scope(key, scope_cache, data_version):
    sf = scope_cache.get(data_version, key)
    params = scopestore.scope_params(key)
    cur = sf.cursor()
    regions = {r[0] for r in cur.execute("SELECT DISTINCT region FROM orders").fetchall()}
    cats = {r[0] for r in cur.execute("SELECT DISTINCT category FROM orders").fetchall()}
    if params.region:
        assert regions == {params.region}
    if params.category:
        assert cats == {params.category}
    cols = {r[0] for r in cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='orders'").fetchall()}
    if key == "all:nofin":
        assert not cols & set(FINANCIAL_COLUMNS)
        rollup_cols = {r[0] for r in cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='r_geo'").fetchall()}
        assert not rollup_cols & {"cost", "profit", "loss_n", "profit_after_shipping"}
    else:
        assert set(FINANCIAL_COLUMNS) <= cols
    ids = cur.execute("SELECT count(*) FILTER (WHERE customer_id LIKE 'CUST-%'), count(*) FILTER (WHERE customer_id LIKE 'C-%') FROM orders").fetchone()
    if key == "all:pseudo":
        assert ids[0] == 0 and ids[1] == sf.rows
    else:
        assert ids[1] == 0 and ids[0] == sf.rows


@pytest.mark.parametrize("key", scope_keys())
def test_row_counts_equal_database_view(key, scope_cache, data_version, app_db, user_ids):
    sf = scope_cache.get(data_version, key)
    uid = user_ids[DEMO_USER_FOR_SCOPE[key]]
    with app_db.cursor() as cur:
        cur.execute("SELECT set_config('app.user_id', %s, true)", (str(uid),))
        n = cur.execute("SELECT count(*) FROM sales.orders_scoped").fetchone()[0]
        assert cur.execute("SELECT app.current_scope_key()").fetchone()[0] == key
    assert n == sf.rows


def test_same_pseudonyms_as_database(scope_cache, data_version, app_db, user_ids):
    sf = scope_cache.get(data_version, "all:pseudo")
    file_ids = dict(sf.cursor().execute("SELECT order_id, customer_id FROM orders ORDER BY order_id LIMIT 50").fetchall())
    with app_db.cursor() as cur:
        cur.execute("SELECT set_config('app.user_id', %s, true)", (str(user_ids["analyst"]),))
        db_ids = dict(cur.execute("SELECT order_id, customer_id FROM sales.orders_scoped WHERE order_id = ANY(%s)",
                                  (list(file_ids),)).fetchall())
    assert file_ids == db_ids


def _copy_scopes(template_db, tmp_path) -> Path:
    src = Path(template_db["scopes_dir"])
    dst = tmp_path / "scopes"
    shutil.copytree(src, dst)
    return dst


def test_changed_file_fails_closed(template_db, tmp_path, data_version):
    dst = _copy_scopes(template_db, tmp_path)
    f = dst / data_version / scopestore.file_name("region:Asia")
    with open(f, "r+b") as fh:
        fh.seek(5000)
        b = fh.read(1)
        fh.seek(5000)
        fh.write(bytes([(b[0] + 1) % 256]))
    with pytest.raises(ScopeFileError):
        ScopeFileCache(dst).get(data_version, "region:Asia")


def test_missing_file_or_manifest_entry_fails_closed(template_db, tmp_path, data_version):
    dst = _copy_scopes(template_db, tmp_path)
    (dst / data_version / scopestore.file_name("region:Europe")).unlink()
    with pytest.raises(ScopeFileError):
        ScopeFileCache(dst).get(data_version, "region:Europe")
    m = json.loads((dst / data_version / "manifest.json").read_text())
    del m["files"]["category:Clothing"]
    (dst / data_version / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(ScopeFileError):
        ScopeFileCache(dst).get(data_version, "category:Clothing")
    with pytest.raises(ScopeFileError):
        ScopeFileCache(dst).get("000000000000", "all:full")


def test_file_swap_fails_closed(template_db, tmp_path, data_version):
    """A file of another scope under this scope's name fails (checksum and regions)."""
    dst = _copy_scopes(template_db, tmp_path)
    v = dst / data_version
    shutil.copy(v / scopestore.file_name("region:Europe"), v / scopestore.file_name("region:Asia"))
    with pytest.raises(ScopeFileError):
        ScopeFileCache(dst).get(data_version, "region:Asia")


def test_manifest_is_written_last(owner_db, tmp_path, data_version, monkeypatch):
    calls = {"n": 0}
    real = scopestore.build_one

    def failing(conn, key, vdir, threads):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("simulated failure")
        return real(conn, key, vdir, threads)

    monkeypatch.setattr(scopestore, "build_one", failing)
    with pytest.raises(RuntimeError):
        scopestore.build_all(owner_db, data_version, tmp_path, threads=2)
    assert not (tmp_path / data_version / "manifest.json").exists()
    assert not scopestore.manifest_is_current(tmp_path / data_version, data_version)


def test_build_is_skipped_when_current(owner_db, template_db, data_version, capsys):
    scopestore.build_all(owner_db, data_version, Path(template_db["scopes_dir"]))
    assert "is current; skip" in capsys.readouterr().out


def test_sandbox(scope_cache, data_version, tmp_path):
    sf = scope_cache.get(data_version, "all:full")
    cur = sf.cursor()
    tables = {r[0] for r in cur.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    assert tables == {"orders", "r_geo", "r_product", "r_customer", "r_ops"}
    for stmt in (
        "SELECT * FROM read_csv('/data/raw/ecommerce_sales.csv')",
        "SELECT * FROM read_parquet('/tmp/x.parquet')",
        f"ATTACH '{tmp_path}/other.duckdb' AS other",
        f"COPY orders TO '{tmp_path}/out.csv'",
        "SET enable_external_access = true",
        "SET threads = 8",
        "CREATE TABLE t (x INT)",
        "DELETE FROM orders",
        "INSERT INTO orders SELECT * FROM orders LIMIT 1",
    ):
        with pytest.raises(duckdb.Error):
            cur.execute(stmt)
