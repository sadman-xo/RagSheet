"""DuckDB analytics engine: run a QuerySpec on one scope file (rollup or raw), with compare and caching.

The engine calculates all deltas, shares, and ranks. The LLM never calculates numbers.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from app.analytics import navigator, periods
from app.analytics.compiler import compile_spec
from app.analytics.dimensions import DIMENSIONS
from app.analytics.metrics import METRICS
from app.analytics.spec import Filters, QuerySpec
from app.cache import LRUCache
from app.data.scoped import ScopeFile

LOW_N = 30
CPU_LIMIT = threading.BoundedSemaphore(4)
_result_cache = LRUCache(4096)  # 13 scopes x periods x page specs: ~2,500 keys in the load tests


@dataclass
class RawResult:
    columns: list[str]
    rows: list[tuple]
    source: str
    sql: str


def _clean(v: Any) -> Any:
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return round(v, 6)
    if isinstance(v, date):
        return v.isoformat()
    return v


def execute(sf: ScopeFile, spec: QuerySpec, force_raw: bool = False, with_dims: bool = True,
            table_override: str | None = None) -> RawResult:
    """Run one spec on the scope file. Returns plain rows. table_override is for the navigator tests."""
    choose_spec = spec if with_dims else spec.model_copy(update={"group_by": [], "time_grain": None, "sort_by": None})
    if table_override is not None:
        table = table_override
    else:
        table = navigator.choose(choose_spec, sf.rollup_rows, sf.data_min, sf.data_max, force_raw, raw_rows=sf.rows)
    compiled = compile_spec(spec, table, sf.data_min, sf.data_max, with_dims=with_dims)
    with CPU_LIMIT:
        cur = sf.cursor()
        try:
            cur.execute(compiled.sql, compiled.params)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
        finally:
            cur.close()
    return RawResult(columns=cols, rows=rows, source=table, sql=compiled.sql)


def _to_dicts(raw: RawResult) -> list[dict]:
    return [dict(zip(raw.columns, r)) for r in raw.rows]


def _fixed_order_sort(spec: QuerySpec, rows: list[dict]) -> list[dict]:
    if spec.sort_by or spec.time_grain or not spec.group_by:
        return rows
    d = DIMENSIONS[spec.group_by[0]]
    if not d.order:
        return rows
    pos = {v: i for i, v in enumerate(d.order)}
    return sorted(rows, key=lambda r: pos.get(r.get(d.id), len(pos)))


def columns_meta(spec: QuerySpec) -> list[dict]:
    cols = [{"key": d, "label": DIMENSIONS[d].label, "role": "dim", "kind": DIMENSIONS[d].kind} for d in spec.dims()]
    for m in spec.metrics:
        md = METRICS[m]
        cols.append({"key": m, "label": md.label, "role": "metric", "kind": md.kind, "financial": md.financial,
                     "higher_is_better": md.higher_is_better, "rate": md.is_rate or m == "repeat_customer_rate"})
    return cols


def _month_offset(cur: periods.Window, prior: periods.Window) -> int:
    return (cur.start.year - prior.start.year) * 12 + (cur.start.month - prior.start.month)


def _shift_key(dim: str, value: Any, months: int, days: int) -> Any:
    if value is None:
        return None
    if dim == "year":
        return int(value) + months // 12 if months % 12 == 0 else value
    if dim == "year_month":
        y, m = int(value[:4]), int(value[5:7])
        idx = y * 12 + (m - 1) + months
        return f"{idx // 12:04d}-{idx % 12 + 1:02d}"
    if dim == "year_quarter":
        y, q = int(value[:4]), int(value[-1])
        idx = y * 4 + (q - 1) + months // 3
        return f"{idx // 4:04d}-Q{idx % 4 + 1}"
    if dim in ("order_date", "week"):
        d = value if isinstance(value, date) else date.fromisoformat(str(value))
        if months and months % 12 == 0:
            return periods.shift_year(d, months // 12)
        return d + timedelta(days=days)
    return value


def run_query(sf: ScopeFile, scope_key: str, spec: QuerySpec, force_raw: bool = False) -> dict:
    """Run a spec (with totals and compare). Cached for each (data version, scope key, spec)."""
    cache_key = (sf.data_version, scope_key, spec.canonical(), force_raw)
    hit = _result_cache.get(cache_key)
    if hit is not None:
        return {**hit, "cache": True}
    t0 = time.perf_counter()
    notes: list[str] = []
    main = execute(sf, spec, force_raw)
    rows = _fixed_order_sort(spec, _to_dicts(main))
    totals = None
    totals_source = None
    if spec.include_totals and spec.dims():
        tot = execute(sf, spec, force_raw, with_dims=False)
        totals = _to_dicts(tot)[0] if tot.rows else None
        totals_source = tot.source
    elif not spec.dims():
        totals = rows[0] if rows else None
        totals_source = main.source

    compare_info = None
    if spec.compare != "none":
        prior_f, label = periods.prior_filters(spec.filters, spec.compare, sf.data_min, sf.data_max)
        prior_spec = spec.model_copy(update={"filters": prior_f, "compare": "none", "limit": 500})
        cur_w = periods.time_window(spec.filters, sf.data_min, sf.data_max)
        pri_w = periods.time_window(prior_f, date(1900, 1, 1), date(2999, 12, 31))
        months = 12 if spec.compare == "prior_year_lfl" else (_month_offset(cur_w, pri_w) if cur_w and pri_w else 0)
        days = (cur_w.start - pri_w.start).days if cur_w and pri_w else 0
        prior_main = execute(sf, prior_spec, force_raw)
        dims = spec.dims()
        prior_map: dict[tuple, dict] = {}
        for r in _to_dicts(prior_main):
            key = tuple(_shift_key(d, r[d], months, days) if DIMENSIONS[d].time_grain else r[d] for d in dims)
            prior_map[tuple(_clean(k) for k in key)] = r
        for r in rows:
            key = tuple(_clean(r[d]) for d in dims)
            _merge_prior(r, prior_map.get(key), spec.metrics)
        if totals is not None:
            pt = execute(sf, prior_spec, force_raw, with_dims=False)
            _merge_prior(totals, _to_dicts(pt)[0] if pt.rows else None, spec.metrics)
        compare_info = {"mode": spec.compare, "label": label, "prior_filters": prior_f.active(), "source": prior_main.source}
        notes += periods.caveats(prior_f, sf.data_min, sf.data_max, sf.monthly_orders)

    notes = periods.caveats(spec.filters, sf.data_min, sf.data_max, sf.monthly_orders) + notes
    low_n = any(
        (r.get(f"{m}__n") is not None and r.get(f"{m}__n") < LOW_N)
        for r in rows for m in spec.metrics
    )
    if low_n:
        notes.append(f"Grey values come from fewer than {LOW_N} orders.")

    result = {
        "spec": spec.model_dump(mode="json", exclude_none=True),
        "columns": columns_meta(spec),
        "rows": [{k: _clean(v) for k, v in r.items()} for r in rows],
        "totals": {k: _clean(v) for k, v in totals.items()} if totals else None,
        "source": main.source,
        "totals_source": totals_source,
        "compare": compare_info,
        "notes": list(dict.fromkeys(notes)),
        "data_version": sf.data_version,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
    }
    _result_cache.put(cache_key, result)
    return {**result, "cache": False}


def _merge_prior(row: dict, prior: dict | None, metrics: list[str]) -> None:
    for m in metrics:
        cur = row.get(m)
        p = prior.get(m) if prior else None
        row[f"{m}__prior"] = p
        if cur is None or p is None:
            row[f"{m}__delta"] = None
            row[f"{m}__pct"] = None
            continue
        row[f"{m}__delta"] = cur - p
        if METRICS[m].kind == "pct":
            row[f"{m}__pct"] = None
        else:
            row[f"{m}__pct"] = ((cur - p) / abs(p) * 100) if p else None


def scalar(sf: ScopeFile, scope_key: str, metric: str, filters: Filters | None = None) -> float | None:
    spec = QuerySpec(metrics=[metric], filters=filters or Filters())
    res = run_query(sf, scope_key, spec)
    return (res["totals"] or {}).get(metric)


def cache_stats() -> dict:
    return _result_cache.stats()
