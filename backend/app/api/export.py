"""CSV exports (max 10,000 rows, formula-injection safe, audited before the stream starts)."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app import audit
from app.analytics import engine
from app.analytics.spec import QuerySpec
from app.api.analytics import _authorized
from app.api.errors import ApiError
from app.api.orders import SearchBody, _clean, search_sql, table_columns
from app.config import get_settings
from app.data.schema import COLUMNS
from app.ratelimit import export_limiter
from app.security.deps import ScopedDataset, get_scoped_dataset, request_info, require, scope_violation
from app.security.masking import mask_value
from app.security.policy import PolicyError, authorize_filters

router = APIRouter(prefix="/api/export", tags=["export"])

DANGEROUS = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(v) -> str:
    if v is None:
        return ""
    s = str(v)
    if s and s[0] in DANGEROUS and not _is_number(s):
        return "'" + s
    return s


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def _rate_limit(ds: ScopedDataset) -> None:
    wait = export_limiter.take(f"u{ds.principal.id}")
    if wait > 0:
        raise ApiError(429, "TOO_MANY_EXPORTS", "Too many exports. Wait and try again.", headers={"Retry-After": str(int(wait) + 1)})


def _csv_stream(header: list[str], rows_iter):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    yield buf.getvalue()
    for chunk in rows_iter:
        buf.seek(0)
        buf.truncate()
        for r in chunk:
            w.writerow([safe_cell(x) for x in r])
        yield buf.getvalue()


def _filename(kind: str) -> str:
    return f"panorama_{kind}_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.csv"


@router.post("/orders", dependencies=[Depends(require("export"))])
def export_orders(body: SearchBody, request: Request, ds: ScopedDataset = Depends(get_scoped_dataset)):
    try:
        authorize_filters(body.filters, ds.scope)
    except PolicyError as exc:
        scope_violation(request, ds, ds.scope, exc)
        raise
    _rate_limit(ds)
    max_rows = get_settings().export_max_rows
    cols = table_columns(ds)
    body = body.model_copy(update={"cursor": None})
    sql, _base, params = search_sql(ds, body, cols, max_rows)
    cur = ds.file.cursor()
    cur.execute(sql, params)
    # The audit row commits before the response starts.
    audit.record_now("export", **audit.principal_fields(ds.principal, ds.scope.scope_key), req=request_info(request),
                     detail={"kind": "orders", "filters": body.filters.active(), "max_rows": max_rows, "columns": cols})
    pii_raw = ds.scope.pii_raw

    def rows():
        try:
            while True:
                batch = cur.fetchmany(1000)
                if not batch:
                    break
                yield [[mask_value(_clean(v), pii_raw) for v in r] for r in batch]
        finally:
            cur.close()

    return StreamingResponse(_csv_stream([COLUMNS[c].label for c in cols], rows()), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{_filename("orders")}"'})


@router.post("/query", dependencies=[Depends(require("export"))])
def export_query(spec: QuerySpec, request: Request, ds: ScopedDataset = Depends(get_scoped_dataset)):
    _authorized(request, ds, spec)
    _rate_limit(ds)
    try:
        res = engine.run_query(ds.file, ds.scope.scope_key, spec)
    except ValueError as exc:
        raise ApiError(422, "INVALID_QUERY", str(exc))
    keys = [c["key"] for c in res["columns"]]
    extra = [k for k in (res["rows"][0].keys() if res["rows"] else []) if k not in keys and not k.endswith("__n")]
    header_keys = keys + extra
    labels = {c["key"]: c["label"] for c in res["columns"]}
    audit.record_now("export", **audit.principal_fields(ds.principal, ds.scope.scope_key), req=request_info(request),
                     detail={"kind": "query", "spec": spec.model_dump(mode="json", exclude_none=True)})
    rows = [[r.get(k) for k in header_keys] for r in res["rows"]]
    return StreamingResponse(_csv_stream([labels.get(k, k) for k in header_keys], [rows]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{_filename("query")}"'})
