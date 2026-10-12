"""Analytics routes. Every spec goes through authorize() before it runs on the user's scope file."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from app import audit
from app.analytics import engine, insights
from app.analytics.compiler import raw_where
from app.analytics.dimensions import DIMENSIONS
from app.analytics.engine import CPU_LIMIT
from app.analytics.metrics import METRICS
from app.analytics.spec import CompareMode, Filters, QuerySpec
from app.api.errors import ApiError
from app.security.deps import ScopedDataset, get_scoped_dataset, request_info, scope_violation
from app.security.policy import PolicyError, authorize, authorize_filters

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

DEFAULT_KPIS_FIN = ["gross_revenue", "net_revenue", "orders", "aov", "margin_pct", "return_rate", "cancellation_rate", "avg_shipping_days"]
DEFAULT_KPIS_OPS = ["gross_revenue", "net_revenue", "orders", "aov", "delivered_rate", "return_rate", "cancellation_rate", "avg_shipping_days"]


def _authorized(request: Request, ds: ScopedDataset, spec: QuerySpec) -> None:
    try:
        authorize(spec, ds.scope)
    except PolicyError as exc:
        scope_violation(request, ds, ds.scope, exc, {"spec": spec.model_dump(mode="json", exclude_none=True)})
        raise


def _audit_query(request: Request, ds: ScopedDataset, specs: list[QuerySpec], kind: str) -> None:
    audit.buffer.add("query", **audit.principal_fields(ds.principal, ds.scope.scope_key), req=request_info(request),
                     detail={"kind": kind, "specs": [s.digest() for s in specs]})


def run(ds: ScopedDataset, spec: QuerySpec) -> dict:
    try:
        return engine.run_query(ds.file, ds.scope.scope_key, spec)
    except ValueError as exc:  # for example a compare without a period
        raise ApiError(422, "INVALID_QUERY", str(exc))


@router.post("/query")
def query(spec: QuerySpec, request: Request, ds: ScopedDataset = Depends(get_scoped_dataset)) -> dict:
    _authorized(request, ds, spec)
    res = run(ds, spec)
    _audit_query(request, ds, [spec], "query")
    return res


class BatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    queries: dict[str, QuerySpec] = Field(max_length=24)


@router.post("/batch")
def batch(body: BatchBody, request: Request, ds: ScopedDataset = Depends(get_scoped_dataset)) -> dict:
    # Authorize all specs first: one out-of-scope spec stops the whole batch.
    for spec in body.queries.values():
        _authorized(request, ds, spec)
    results: dict[str, dict] = {}
    for qid, spec in body.queries.items():
        try:
            results[qid] = engine.run_query(ds.file, ds.scope.scope_key, spec)
        except ValueError as exc:
            results[qid] = {"error": {"code": "INVALID_QUERY", "message": str(exc)}}
    _audit_query(request, ds, list(body.queries.values()), "batch")
    return {"results": results}


class KpiBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filters: Filters = Field(default_factory=Filters)
    compare: CompareMode = "prior_year_lfl"
    metrics: list[str] | None = Field(default=None, max_length=8)
    spark_grain: Literal["year_month", "year_quarter", "year"] = "year_month"


@router.post("/kpis")
def kpis(body: KpiBody, request: Request, ds: ScopedDataset = Depends(get_scoped_dataset)) -> dict:
    metrics = body.metrics or (DEFAULT_KPIS_FIN if ds.scope.financial else DEFAULT_KPIS_OPS)
    out_metrics = [metrics[i:i + 6] for i in range(0, len(metrics), 6)]
    compare_label = None
    totals: dict = {}
    notes: list[str] = []
    for chunk in out_metrics:
        spec = QuerySpec(metrics=chunk, filters=body.filters, compare=body.compare)
        _authorized(request, ds, spec)
        try:
            res = engine.run_query(ds.file, ds.scope.scope_key, spec)
            compare_label = res["compare"]["label"] if res["compare"] else None
        except ValueError:
            res = engine.run_query(ds.file, ds.scope.scope_key, spec.model_copy(update={"compare": "none"}))
        totals.update(res["totals"] or {})
        notes += res["notes"]
    spark: dict[str, list] = {}
    for chunk in out_metrics:
        sspec = QuerySpec(metrics=chunk, filters=body.filters, time_grain=body.spark_grain, limit=500, include_totals=False)
        res = engine.run_query(ds.file, ds.scope.scope_key, sspec)
        for m in chunk:
            spark[m] = [{"x": r[body.spark_grain], "y": r[m]} for r in res["rows"]]
    items = []
    for m in metrics:
        md = METRICS[m]
        items.append({
            "id": m, "label": md.label, "kind": md.kind, "description": md.description, "financial": md.financial,
            "higher_is_better": md.higher_is_better, "value": totals.get(m), "n": totals.get(f"{m}__n"),
            "prior": totals.get(f"{m}__prior"), "delta": totals.get(f"{m}__delta"), "pct": totals.get(f"{m}__pct"),
            "spark": spark.get(m, []),
        })
    _audit_query(request, ds, [], "kpis")
    return {"kpis": items, "compare": compare_label, "notes": list(dict.fromkeys(notes))}


class Side(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(max_length=80)
    filters: Filters = Field(default_factory=Filters)


class CompareBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a: Side
    b: Side
    metrics: list[str] = Field(min_length=1, max_length=6)
    group_by: str | None = None
    time_grain: Literal["year_month", "year_quarter", "year"] | None = None


@router.post("/compare")
def compare(body: CompareBody, request: Request, ds: ScopedDataset = Depends(get_scoped_dataset)) -> dict:
    sides = {}
    for name, side in (("a", body.a), ("b", body.b)):
        spec = QuerySpec(metrics=body.metrics, filters=side.filters)
        _authorized(request, ds, spec)
        sides[name] = run(ds, spec)["totals"] or {}
    kpi_rows = []
    for m in body.metrics:
        a, b = sides["a"].get(m), sides["b"].get(m)
        delta = (b - a) if a is not None and b is not None else None
        pct = (delta / abs(a) * 100) if delta is not None and a and METRICS[m].kind != "pct" else None
        kpi_rows.append({"metric": m, "label": METRICS[m].label, "kind": METRICS[m].kind, "a": a, "b": b,
                         "delta": delta, "pct": pct, "higher_is_better": METRICS[m].higher_is_better,
                         "a_n": sides["a"].get(f"{m}__n"), "b_n": sides["b"].get(f"{m}__n")})
    breakdown = None
    if body.group_by:
        if body.group_by not in DIMENSIONS:
            raise ApiError(422, "UNKNOWN_DIMENSION", "Unknown dimension.")
        merged: dict = {}
        for name, side in (("a", body.a), ("b", body.b)):
            spec = QuerySpec(metrics=body.metrics, filters=side.filters, group_by=[body.group_by], limit=100)
            _authorized(request, ds, spec)
            for r in run(ds, spec)["rows"]:
                row = merged.setdefault(r[body.group_by], {body.group_by: r[body.group_by]})
                for m in body.metrics:
                    row[f"{m}__{name}"] = r.get(m)
        breakdown = list(merged.values())
    trends = None
    if body.time_grain:
        trends = {}
        for name, side in (("a", body.a), ("b", body.b)):
            spec = QuerySpec(metrics=body.metrics, filters=side.filters, time_grain=body.time_grain, limit=500, include_totals=False)
            _authorized(request, ds, spec)
            rows = run(ds, spec)["rows"]
            trends[name] = [{"i": i, "x": r[body.time_grain], **{m: r.get(m) for m in body.metrics}} for i, r in enumerate(rows)]
    _audit_query(request, ds, [], "compare")
    return {"a": {"label": body.a.label, "filters": body.a.filters.active()}, "b": {"label": body.b.label, "filters": body.b.filters.active()},
            "kpis": kpi_rows, "breakdown": breakdown, "trends": trends}


DIST_FIELDS = {
    "shipping_days": False, "unit_price": False, "revenue": False, "quantity": False, "discount": False,
    "shipping_cost": False, "profit": True, "profit_margin_pct": True,
}


class DistributionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    group_by: str | None = None
    filters: Filters = Field(default_factory=Filters)
    bins: int = Field(default=20, ge=5, le=60)


@router.post("/distribution")
def distribution(body: DistributionBody, request: Request, ds: ScopedDataset = Depends(get_scoped_dataset)) -> dict:
    if body.field not in DIST_FIELDS:
        raise ApiError(422, "UNKNOWN_FIELD", "Unknown field.")
    if DIST_FIELDS[body.field] and not ds.scope.financial:
        exc = PolicyError(403, "FORBIDDEN_METRIC", "Your role cannot see financial fields.", {"field": body.field})
        scope_violation(request, ds, ds.scope, exc)
        raise exc
    if body.group_by and (body.group_by not in DIMENSIONS or DIMENSIONS[body.group_by].pii):
        raise ApiError(422, "UNKNOWN_DIMENSION", "Unknown dimension.")
    try:
        authorize_filters(body.filters, ds.scope)
    except PolicyError as exc:
        scope_violation(request, ds, ds.scope, exc)
        raise
    sf = ds.file
    where, params = raw_where(body.filters, sf.data_min, sf.data_max)
    f = body.field
    gsel = f"{DIMENSIONS[body.group_by].raw_expr} AS g, " if body.group_by else "'All' AS g, "
    sql = (f"SELECT {gsel} count(*) n, min({f}) mn, quantile_cont({f}, 0.25) q1, median({f}) med, "
           f"quantile_cont({f}, 0.75) q3, max({f}) mx, avg({f}) mean FROM orders {where} GROUP BY 1 ORDER BY 1")
    with CPU_LIMIT:
        cur = sf.cursor()
        try:
            stats = cur.execute(sql, params).fetchall()
            lo, hi = cur.execute(f"SELECT min({f}), max({f}) FROM orders {where}", params).fetchone()
            hist = []
            if lo is not None and hi is not None:
                lo, hi = float(lo), float(hi)
                width = (hi - lo) / body.bins if hi > lo else 1.0
                p2 = {**params, "lo": lo, "w": width, "nb": body.bins - 1}
                rows = cur.execute(f"SELECT least(CAST(floor((CAST({f} AS DOUBLE) - $lo) / $w) AS INTEGER), $nb) b, count(*) "
                                   f"FROM orders {where} GROUP BY 1 ORDER BY 1", p2).fetchall()
                hist = [{"from": lo + b * width, "to": lo + (b + 1) * width, "n": n} for b, n in rows]
        finally:
            cur.close()
    groups = [{"group": g if not hasattr(g, "isoformat") else g.isoformat(), "n": n, "min": float(mn), "q1": float(q1),
               "median": float(med), "q3": float(q3), "max": float(mx), "mean": float(mean)}
              for g, n, mn, q1, med, q3, mx, mean in stats]
    _audit_query(request, ds, [], "distribution")
    return {"field": f, "group_by": body.group_by, "groups": groups, "histogram": hist}


@router.get("/insights")
def get_insights(request: Request, ds: ScopedDataset = Depends(get_scoped_dataset)) -> dict:
    items = insights.insights(ds.file, ds.scope)
    _audit_query(request, ds, [], "insights")
    return {"insights": items}
