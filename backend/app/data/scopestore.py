"""Build one read-only DuckDB file for each data scope (run by init as panorama_owner).

Each file contains only its scope's rows and allowed columns, read with sales.scope_rows(...):
the same SQL function that the view sales.orders_scoped uses. Only this module calls sales.scope_rows.
Files are written under a temporary name, then renamed; manifest.json is written last.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import psycopg
from psycopg import sql

from app.analytics.rollups import all_rollup_sql
from app.data import vocab
from app.data.schema import FINANCIAL_COLUMNS, FLAT_COLUMNS

LAYOUT_VERSION = 4
MANIFEST = "manifest.json"
KEEP_VERSIONS = 2


@dataclass(frozen=True)
class ScopeParams:
    all_regions: bool
    region: str | None
    all_categories: bool
    category: str | None
    financial: bool
    pii_raw: bool


def scope_keys() -> list[str]:
    return (["all:full", "all:pseudo", "all:nofin"]
            + [f"region:{r}" for r in vocab.REGIONS]
            + [f"category:{c}" for c in vocab.CATEGORIES])


def scope_params(key: str) -> ScopeParams:
    if key == "all:full":
        return ScopeParams(True, None, True, None, True, True)
    if key == "all:pseudo":
        return ScopeParams(True, None, True, None, True, False)
    if key == "all:nofin":
        return ScopeParams(True, None, True, None, False, True)
    kind, _, value = key.partition(":")
    if kind == "region" and value in vocab.REGIONS:
        return ScopeParams(False, value, True, None, True, True)
    if kind == "category" and value in vocab.CATEGORIES:
        return ScopeParams(True, None, False, value, True, True)
    raise ValueError(f"unknown scope key {key!r}")


def file_name(key: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", key.lower().replace("&", "and")).strip("_")
    return f"{slug}.duckdb"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def columns_for(params: ScopeParams) -> list:
    return [c for c in FLAT_COLUMNS if params.financial or c.name not in FINANCIAL_COLUMNS]


def _export_csv(conn: psycopg.Connection, params: ScopeParams, target: Path) -> None:
    stmt = sql.SQL(
        "COPY (SELECT * FROM sales.scope_rows({}, {}, {}, {}, {}, {}) ORDER BY order_date, order_id) "
        "TO STDOUT WITH (FORMAT csv, HEADER true)"
    ).format(*(sql.Literal(v) for v in (params.all_regions, params.region, params.all_categories,
                                          params.category, params.financial, params.pii_raw)))
    with conn.cursor() as cur, open(target, "wb") as fh:
        with cur.copy(stmt) as cp:
            for chunk in cp:
                fh.write(chunk)


def build_one(conn: psycopg.Connection, key: str, vdir: Path, threads: int) -> dict:
    t0 = time.monotonic()
    params = scope_params(key)
    name = file_name(key)
    csv_path = vdir / f".{name}.csv"
    tmp_path = vdir / f".{name}.tmp"
    final = vdir / name
    for p in (csv_path, tmp_path, Path(str(tmp_path) + ".wal")):
        p.unlink(missing_ok=True)
    _export_csv(conn, params, csv_path)

    all_cols = {c.name: c.duck_type for c in FLAT_COLUMNS}
    keep = columns_for(params)
    con = duckdb.connect(str(tmp_path), config={"threads": max(1, threads), "memory_limit": "1GB"})
    try:
        cols_struct = "{" + ", ".join(f"'{n}': '{t}'" for n, t in all_cols.items()) + "}"
        src = f"read_csv('{csv_path.as_posix()}', header=true, auto_detect=false, columns={cols_struct})"
        if not params.financial:
            # The view gives NULL financial values for this scope; check it, then drop the columns.
            leaked = con.execute(
                f"SELECT count(*) FROM {src} WHERE " + " OR ".join(f"{c} IS NOT NULL" for c in FINANCIAL_COLUMNS)
            ).fetchone()[0]
            if leaked:
                raise RuntimeError(f"scope {key}: financial values present in a non-financial scope")
        select = ", ".join(c.name for c in keep)
        con.execute(f"CREATE TABLE orders AS SELECT {select} FROM {src} ORDER BY order_date, order_id")
        rows = con.execute("SELECT count(*) FROM orders").fetchone()[0]
        if rows == 0:
            raise RuntimeError(f"scope {key}: no rows")
        regions = [r[0] for r in con.execute("SELECT DISTINCT region FROM orders ORDER BY 1").fetchall()]
        categories = [r[0] for r in con.execute("SELECT DISTINCT category FROM orders ORDER BY 1").fetchall()]
        if params.region is not None and regions != [params.region]:
            raise RuntimeError(f"scope {key}: unexpected regions {regions}")
        if params.category is not None and categories != [params.category]:
            raise RuntimeError(f"scope {key}: unexpected categories {categories}")
        if not params.pii_raw:
            raw_ids = con.execute("SELECT count(*) FROM orders WHERE customer_id LIKE 'CUST-%'").fetchone()[0]
            if raw_ids:
                raise RuntimeError(f"scope {key}: raw customer IDs in a pseudonym scope")
        for stmt in all_rollup_sql(params.financial):
            con.execute(stmt)
        rollup_rows = {r: con.execute(f"SELECT count(*) FROM {r}").fetchone()[0] for r in ("r_geo", "r_product", "r_customer", "r_ops")}
        dmin, dmax = con.execute("SELECT min(order_date), max(order_date) FROM orders").fetchone()
        con.execute("CHECKPOINT")
    finally:
        con.close()
    csv_path.unlink(missing_ok=True)
    os.replace(tmp_path, final)
    entry = {
        "key": key,
        "file": name,
        "rows": int(rows),
        "sha256": sha256_file(final),
        "bytes": final.stat().st_size,
        "regions": regions,
        "categories": categories,
        "columns": [c.name for c in keep],
        "financial": params.financial,
        "pii_raw": params.pii_raw,
        "rollup_rows": rollup_rows,
        "min_date": dmin.isoformat(),
        "max_date": dmax.isoformat(),
    }
    print(f"scopestore: {key:<26} {rows:>9,} rows {entry['bytes'] / 1e6:6.1f} MB {time.monotonic() - t0:5.1f} s")
    return entry


def read_manifest(vdir: Path) -> dict | None:
    try:
        return json.loads((vdir / MANIFEST).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def manifest_is_current(vdir: Path, data_version: str, verify_checksums: bool = True) -> bool:
    m = read_manifest(vdir)
    if not m or m.get("data_version") != data_version or m.get("layout") != LAYOUT_VERSION:
        return False
    if set(m.get("files", {})) != set(scope_keys()):
        return False
    for entry in m["files"].values():
        p = vdir / entry["file"]
        if not p.exists():
            return False
        if verify_checksums and sha256_file(p) != entry["sha256"]:
            return False
    return True


def cleanup_old_versions(scopes_dir: Path, current: str) -> None:
    versions = []
    for d in scopes_dir.iterdir():
        if d.is_dir() and d.name != current:
            m = read_manifest(d)
            versions.append((m.get("built_at", "") if m else "", d))
    versions.sort(reverse=True)
    for _built, d in versions[KEEP_VERSIONS - 1:]:
        shutil.rmtree(d, ignore_errors=True)
        print(f"scopestore: removed old version {d.name}")


def build_all(conn: psycopg.Connection, data_version: str, scopes_dir: Path, threads: int | None = None,
              keys: list[str] | None = None) -> dict:
    """Build all scope files for data_version unless the manifest is current. Returns the manifest."""
    vdir = scopes_dir / data_version
    if keys is None and manifest_is_current(vdir, data_version):
        print(f"scopestore: manifest for {data_version} is current; skip")
        return read_manifest(vdir)
    t0 = time.monotonic()
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / MANIFEST).unlink(missing_ok=True)
    threads = threads or os.cpu_count() or 2
    files = {}
    for key in keys or scope_keys():
        files[key] = build_one(conn, key, vdir, threads)
    full = files.get("all:full") or next(iter(files.values()))
    manifest = {
        "data_version": data_version,
        "layout": LAYOUT_VERSION,
        # the dataset range ("today" is the last date of the whole dataset, for every scope)
        "min_date": min(f["min_date"] for f in files.values()) if keys is None else full["min_date"],
        "max_date": max(f["max_date"] for f in files.values()) if keys is None else full["max_date"],
        "built_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
    }
    tmp = vdir / (MANIFEST + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    os.replace(tmp, vdir / MANIFEST)
    if keys is None:
        cleanup_old_versions(scopes_dir, data_version)
    print(f"scopestore: built {len(files)} scope files in {time.monotonic() - t0:.1f} s")
    return manifest
