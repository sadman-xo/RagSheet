"""Order search (keyset pages from the scope file) and order detail (404 outside the scope)."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from app import audit
from app.analytics import periods
from app.analytics.compiler import raw_where
from app.analytics.engine import CPU_LIMIT
from app.analytics.spec import Filters
from app.api.errors import ApiError
from app.cache import LRUCache
from app.data.schema import COLUMNS, FINANCIAL_COLUMNS
from app.security.deps import ScopedDataset, get_scoped_dataset, request_info, scope_violation
from app.security.masking import mask_value
from app.security.policy import PolicyError, authorize_filters

router = APIRouter(prefix="/api/orders", tags=["orders"])

ORDER_ID_RE = re.compile(r"^ORD-\d{6,7}$")
CUSTOMER_RE = re.compile(r"^(CUST-\d{5,7}|C-[A-Z2-7]{8})$")
MAX_PAGE = 200
FIRST_WINDOW_DAYS = 16
_total_cache = LRUCache(1024)


class Cursor(BaseModel):
    order_date: date
    order_id: str = Field(max_length=12)


class SearchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filters: Filters = Field(default_factory=Filters)
    q: str | None = Field(default=None, max_length=60)
    sort: Literal["date_desc", "date_asc"] = "date_desc"
    cursor: Cursor | None = None
    limit: int = Field(default=50, ge=1, le=MAX_PAGE)
    with_total: bool = True


def table_columns(ds: ScopedDataset) -> list[str]:
    return [c for c in ds.scope.visible_columns() if c in ds.file.columns]


def search_sql(ds: ScopedDataset, body: SearchBody, columns: list[str], limit: int,
               window_edge: date | None = None) -> tuple[str, str, dict]:
    """window_edge: only rows on or after it (date_desc) or on or before it (date_asc). The scope files are
    sorted by order_date, so DuckDB skips the row groups outside the window."""
    sf = ds.file
    where, params = raw_where(body.filters, sf.data_min, sf.data_max)
    conds = [where[len("WHERE "):]] if where else []
    if body.q:
        q = body.q.strip()
        if ORDER_ID_RE.match(q.upper()):
            conds.append("order_id = $q")
            params["q"] = q.upper()
        elif CUSTOMER_RE.match(q.upper()):
            conds.append("customer_id = $q")
            params["q"] = q.upper()
        else:
            conds.append("(product_name ILIKE $q OR order_id ILIKE $q OR country ILIKE $q)")
            params["q"] = f"%{q}%"
    base_where = ("WHERE " + " AND ".join(conds)) if conds else ""
    page_conds = list(conds)
    desc = body.sort == "date_desc"
    if body.cursor:
        op = "<" if desc else ">"
        page_conds.append(f"(order_date {op} $c_date OR (order_date = $c_date AND order_id {op} $c_id))")
        params["c_date"] = body.cursor.order_date
        params["c_id"] = body.cursor.order_id
    if window_edge is not None:
        page_conds.append(f"order_date {'>=' if desc else '<='} $w_edge")
        params["w_edge"] = window_edge
    page_where = ("WHERE " + " AND ".join(page_conds)) if page_conds else ""
    direction = "DESC" if desc else "ASC"
    sql = (f"SELECT {', '.join(columns)} FROM orders {page_where} "
           f"ORDER BY order_date {direction}, order_id {direction} LIMIT {int(limit)}")
    return sql, base_where, params


def _clean(v):
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if hasattr(v, "as_integer_ratio") and not isinstance(v, (int, bool)):
        return float(v)
    return v


def _page_rows(cur, ds: ScopedDataset, body: SearchBody, cols: list[str]) -> tuple[list[tuple], str, dict]:
    """One page (limit + 1 rows). First a short date window next to the page start, then wider windows, then no
    window. The result is the same as without a window: when a window gives limit + 1 rows, every row of the
    true page is in the window (the rows are ordered by date)."""
    sf = ds.file
    desc = body.sort == "date_desc"
    w = periods.time_window(body.filters, sf.data_min, sf.data_max)
    lo, hi = (w.start, w.end) if w else (sf.data_min, sf.data_max)
    if body.cursor:
        if desc:
            hi = min(hi, body.cursor.order_date)
        else:
            lo = max(lo, body.cursor.order_date)
    days = FIRST_WINDOW_DAYS
    while True:
        edge = hi - timedelta(days=days) if desc else lo + timedelta(days=days)
        if (desc and edge <= lo) or (not desc and edge >= hi):
            edge = None  # the window covers the whole range: no window
        sql, base_where, params = search_sql(ds, body, cols, body.limit + 1, window_edge=edge)
        rows = cur.execute(sql, params).fetchall()
        if edge is None or len(rows) > body.limit:
            return rows, base_where, params
        days *= 8


@router.post("/search")
def search(body: SearchBody, request: Request, ds: ScopedDataset = Depends(get_scoped_dataset)) -> dict:
    try:
        authorize_filters(body.filters, ds.scope)
    except PolicyError as exc:
        scope_violation(request, ds, ds.scope, exc)
        raise
    cols = table_columns(ds)
    with CPU_LIMIT:
        cur = ds.file.cursor()
        try:
            rows, base_where, params = _page_rows(cur, ds, body, cols)
            total = None
            if body.with_total:
                key = (ds.file.data_version, ds.scope.scope_key, base_where,
                       json.dumps({k: v for k, v in params.items() if not k.startswith(("c_", "w_"))}, sort_keys=True, default=str))
                total = _total_cache.get(key)
                if total is None:
                    count_params = {k: v for k, v in params.items() if not k.startswith(("c_", "w_"))}
                    total = cur.execute(f"SELECT count(*) FROM orders {base_where}", count_params).fetchone()[0]
                    _total_cache.put(key, total)
        finally:
            cur.close()
    more = len(rows) > body.limit
    rows = rows[: body.limit]
    out = [{c: mask_value(_clean(v), ds.scope.pii_raw) for c, v in zip(cols, r)} for r in rows]
    nxt = {"order_date": out[-1]["order_date"], "order_id": out[-1]["order_id"]} if more and out else None
    audit.buffer.add("order_search", **audit.principal_fields(ds.principal, ds.scope.scope_key), req=request_info(request),
                     detail={"filters": body.filters.active(), "q": bool(body.q)})
    return {
        "columns": [{"key": c, "label": COLUMNS[c].label, "kind": COLUMNS[c].kind, "in_table": COLUMNS[c].in_table} for c in cols],
        "rows": out, "next_cursor": nxt, "total": total,
        "hidden_columns": [c for c in FINANCIAL_COLUMNS if c not in cols],
    }


@router.get("/{order_id}")
def detail(order_id: str, request: Request, ds: ScopedDataset = Depends(get_scoped_dataset)) -> dict:
    oid = order_id.strip().upper()
    if not ORDER_ID_RE.match(oid):
        raise ApiError(404, "NOT_FOUND", "Order not found.")
    cols = table_columns(ds)
    with CPU_LIMIT:
        cur = ds.file.cursor()
        try:
            r = cur.execute(f"SELECT {', '.join(cols)} FROM orders WHERE order_id = $id", {"id": oid}).fetchone()
        finally:
            cur.close()
    if r is None:
        # Not in this scope file: the same answer as for an order that does not exist.
        raise ApiError(404, "NOT_FOUND", "Order not found.")
    audit.buffer.add("order_view", **audit.principal_fields(ds.principal, ds.scope.scope_key), req=request_info(request),
                     detail={"order_id": oid})
    order = {c: mask_value(_clean(v), ds.scope.pii_raw) for c, v in zip(cols, r)}
    return {
        "order": order,
        "fields": [{"key": c, "label": COLUMNS[c].label, "kind": COLUMNS[c].kind, "description": COLUMNS[c].description} for c in cols],
        "hidden_fields": [{"key": c, "label": COLUMNS[c].label} for c in FINANCIAL_COLUMNS if c not in cols],
        "pseudonym": not ds.scope.pii_raw,
    }
