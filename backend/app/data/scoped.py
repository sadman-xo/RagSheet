"""Open the read-only scope files in the api. Only this module opens scope files.

Each process keeps one connection for each scope file (LRU, 12 entries). Each query uses its own cursor.
At open, the file must agree with the manifest (row count, checksum, regions, categories, columns).
A mismatch fails closed.
"""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import duckdb

from app.data.schema import FINANCIAL_COLUMNS
from app.data.scopestore import MANIFEST, scope_params, sha256_file

DUCKDB_CONFIG = {
    "threads": 1,
    "memory_limit": "512MB",
    "enable_external_access": False,
    "lock_configuration": True,
}
EXPECTED_TABLES = {"orders", "r_geo", "r_product", "r_customer", "r_ops"}


class ScopeFileError(RuntimeError):
    """The scope file is missing or does not agree with the manifest (fail closed)."""


@dataclass
class ScopeFile:
    key: str
    data_version: str
    path: Path
    con: duckdb.DuckDBPyConnection
    rows: int
    columns: frozenset[str]
    rollup_rows: dict[str, int]
    data_min: date
    data_max: date
    monthly_orders: dict[str, int] = field(default_factory=dict)
    regions: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()

    def cursor(self) -> duckdb.DuckDBPyConnection:
        return self.con.cursor()

    @property
    def financial(self) -> bool:
        return "profit" in self.columns


def load_manifest(scopes_dir: Path, data_version: str) -> dict:
    """Read the manifest (once for each opened file; the files are opened once for each process)."""
    try:
        m = json.loads((scopes_dir / data_version / MANIFEST).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise ScopeFileError(f"no scope manifest for data version {data_version}") from exc
    if m.get("data_version") != data_version:
        raise ScopeFileError("scope manifest has a different data version")
    return m

def _open(scopes_dir: Path, data_version: str, key: str) -> ScopeFile:
    manifest = load_manifest(scopes_dir, data_version)
    entry = manifest.get("files", {}).get(key)
    if entry is None:
        raise ScopeFileError(f"scope {key} is not in the manifest")
    path = scopes_dir / data_version / entry["file"]
    if not path.exists():
        raise ScopeFileError(f"scope file for {key} is missing")
    if sha256_file(path) != entry["sha256"]:
        raise ScopeFileError(f"scope file for {key} has a wrong checksum")
    params = scope_params(key)
    con = duckdb.connect(str(path), read_only=True, config=dict(DUCKDB_CONFIG))
    try:
        tables = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
        if tables != EXPECTED_TABLES:
            raise ScopeFileError(f"scope file for {key} has unexpected tables {sorted(tables)}")
        cols = frozenset(r[0] for r in con.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'orders'").fetchall())
        if not params.financial and cols & set(FINANCIAL_COLUMNS):
            raise ScopeFileError(f"scope file for {key} contains financial columns")
        if params.financial and not set(FINANCIAL_COLUMNS) <= cols:
            raise ScopeFileError(f"scope file for {key} misses financial columns")
        rows = con.execute("SELECT count(*) FROM orders").fetchone()[0]
        if rows != entry["rows"]:
            raise ScopeFileError(f"scope file for {key}: row count {rows} != manifest {entry['rows']}")
        regions = tuple(r[0] for r in con.execute("SELECT DISTINCT region FROM orders ORDER BY 1").fetchall())
        categories = tuple(r[0] for r in con.execute("SELECT DISTINCT category FROM orders ORDER BY 1").fetchall())
        if params.region is not None and regions != (params.region,):
            raise ScopeFileError(f"scope file for {key} contains other regions")
        if params.category is not None and categories != (params.category,):
            raise ScopeFileError(f"scope file for {key} contains other categories")
        if not params.pii_raw:
            if con.execute("SELECT count(*) FROM orders WHERE customer_id LIKE 'CUST-%'").fetchone()[0]:
                raise ScopeFileError(f"scope file for {key} contains raw customer IDs")
        rollup_rows = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in sorted(EXPECTED_TABLES - {"orders"})}
        dmin, dmax = con.execute("SELECT min(order_date), max(order_date) FROM orders").fetchone()
        if manifest.get("min_date") and manifest.get("max_date"):  # periods use the range of the whole dataset
            dmin, dmax = date.fromisoformat(manifest["min_date"]), date.fromisoformat(manifest["max_date"])
        monthly = {r[0]: int(r[1]) for r in con.execute(
            "SELECT year_month, SUM(n_orders) FROM r_geo GROUP BY 1 ORDER BY 1").fetchall()}
    except Exception:
        con.close()
        raise
    return ScopeFile(key=key, data_version=data_version, path=path, con=con, rows=rows, columns=cols,
                     rollup_rows=rollup_rows, data_min=dmin, data_max=dmax, monthly_orders=monthly,
                     regions=regions, categories=categories)


class ScopeFileCache:
    """LRU of open scope files for one process."""

    def __init__(self, scopes_dir: Path, size: int = 12):
        self.scopes_dir = scopes_dir
        self.size = size
        self._items: OrderedDict[tuple[str, str], ScopeFile] = OrderedDict()
        self._lock = threading.Lock()
        self._opening: dict[tuple[str, str], threading.Lock] = {}

    def get(self, data_version: str, key: str) -> ScopeFile:
        k = (data_version, key)
        with self._lock:
            sf = self._items.get(k)
            if sf is not None:
                self._items.move_to_end(k)
                return sf
            open_lock = self._opening.setdefault(k, threading.Lock())
        with open_lock:  # one opener for each file; other threads wait for it
            with self._lock:
                sf = self._items.get(k)
                if sf is not None:
                    return sf
            sf = _open(self.scopes_dir, data_version, key)
            with self._lock:
                self._items[k] = sf
                self._items.move_to_end(k)
                while len(self._items) > self.size:
                    _old_k, old = self._items.popitem(last=False)
                    try:
                        old.con.close()
                    except Exception:  # pragma: no cover
                        pass
            return sf

    def stats(self) -> list[dict]:
        with self._lock:
            return [{"data_version": v, "scope_key": k, "rows": sf.rows} for (v, k), sf in self._items.items()]

    def clear(self) -> None:
        with self._lock:
            for sf in self._items.values():
                try:
                    sf.con.close()
                except Exception:  # pragma: no cover
                    pass
            self._items.clear()


_cache: ScopeFileCache | None = None
_cache_lock = threading.Lock()


def get_cache() -> ScopeFileCache:
    global _cache
    if _cache is None:
        with _cache_lock:
            if _cache is None:
                from app.config import get_settings

                _cache = ScopeFileCache(get_settings().scopes_dir)
    return _cache


def set_cache(cache: ScopeFileCache | None) -> None:
    """Tests point the api at temporary scope files."""
    global _cache
    if _cache is not None and _cache is not cache:
        _cache.clear()
    _cache = cache
