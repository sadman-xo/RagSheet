"""Chat tools. Every tool runs on the user's scope file (through the navigator) or reads public registries.

Tools: metric, breakdown, trend, compare, why, list_orders, lookup_order, overview, definition, data_quality,
access, semantic_search (retrieval only, at narrate time).
"""

from __future__ import annotations

from app.analytics import engine, quality
from app.analytics.compiler import raw_where
from app.analytics.engine import CPU_LIMIT
from app.analytics.metrics import METRICS
from app.analytics.spec import Filters
from app.chat.plan import QueryPlan
from app.data.schema import COLUMNS
from app.rag.documents import explorer_link
from app.security.deps import ScopedDataset
from app.security.masking import mask_value

MAX_ROWS = 50


def _link(spec) -> str:
    f = spec.filters.model_dump(exclude_none=True, mode="json")
    return explorer_link(spec.metrics[:4], spec.group_by, spec.time_grain, f)


def run_specs(plan: QueryPlan, ds: ScopedDataset) -> list[dict]:
    out = []
    for i, s in enumerate(plan.specs, start=1):
        qs = s.query_spec()
        try:
            res = engine.run_query(ds.file, ds.scope.scope_key, qs)
        except ValueError:
            qs = qs.model_copy(update={"compare": "none"})
            res = engine.run_query(ds.file, ds.scope.scope_key, qs)
        out.append({
            "ref": f"R{i}", "kind": "table", "title": s.title or f"Result {i}", "columns": res["columns"],
            "rows": res["rows"][:MAX_ROWS], "row_count": len(res["rows"]), "totals": res["totals"],
            "compare": res["compare"]["label"] if res["compare"] else None, "source": res["source"], "notes": res["notes"],
            "explorer_link": _link(qs), "spec": qs.model_dump(mode="json", exclude_none=True),
        })
    return out


def lookup_order(order_id: str, ds: ScopedDataset) -> dict | None:
    cols = [c for c in ds.scope.visible_columns() if c in ds.file.columns]
    with CPU_LIMIT:
        cur = ds.file.cursor()
        try:
            r = cur.execute(f"SELECT {', '.join(cols)} FROM orders WHERE order_id = $id", {"id": order_id.upper()}).fetchone()
        finally:
            cur.close()
    if r is None:
        return None
    row = {c: mask_value(v.isoformat() if hasattr(v, "isoformat") else (float(v) if hasattr(v, "as_integer_ratio") and not isinstance(v, (int, bool)) else v), ds.scope.pii_raw)
           for c, v in zip(cols, r)}
    return {"ref": "R1", "kind": "order", "title": f"Order {order_id.upper()}",
            "columns": [{"key": c, "label": COLUMNS[c].label, "role": "dim", "kind": COLUMNS[c].kind} for c in cols],
            "rows": [row], "row_count": 1, "totals": None, "explorer_link": f"/orders?q={order_id.upper()}"}


def list_orders(filters: Filters | None, ds: ScopedDataset, limit: int = 20) -> dict:
    cols = [c for c in ("order_id", "order_date", "country", "product_name", "quantity", "revenue", "order_status",
                        "shipping_method", "customer_id") if c in ds.file.columns]
    sf = ds.file
    where, params = raw_where(filters or Filters(), sf.data_min, sf.data_max)
    with CPU_LIMIT:
        cur = sf.cursor()
        try:
            rows = cur.execute(f"SELECT {', '.join(cols)} FROM orders {where} ORDER BY order_date DESC, order_id DESC LIMIT {int(limit)}", params).fetchall()
            total = cur.execute(f"SELECT count(*) FROM orders {where}", params).fetchone()[0]
        finally:
            cur.close()
    out_rows = []
    for r in rows:
        out_rows.append({c: mask_value(v.isoformat() if hasattr(v, "isoformat") else (float(v) if hasattr(v, "as_integer_ratio") and not isinstance(v, (int, bool)) else v), ds.scope.pii_raw)
                         for c, v in zip(cols, r)})
    return {"ref": "R1", "kind": "orders", "title": "Orders (newest first)",
            "columns": [{"key": c, "label": COLUMNS[c].label, "role": "dim", "kind": COLUMNS[c].kind} for c in cols],
            "rows": out_rows, "row_count": total, "totals": {"orders": total}, "explorer_link": "/orders"}


def definition(metric_id: str) -> dict:
    m = METRICS[metric_id]
    return {"ref": "R1", "kind": "definition", "title": m.label, "columns": [], "rows": [],
            "definition": {"id": m.id, "label": m.label, "description": m.description, "formula": m.formula},
            "explorer_link": f"/explorer?m={m.id}"}


def data_quality(ds: ScopedDataset) -> dict:
    notes = quality.data_notes(ds.file, ds.scope.scope_key)
    return {"ref": "R1", "kind": "notes", "title": "Data quality notes", "columns": [], "rows": [],
            "notes_list": [{"title": n["title"], "text": n["text"], "evidence": n["evidence"]} for n in notes],
            "explorer_link": "/data-notes"}


def access(ds: ScopedDataset) -> dict:
    sc = ds.scope
    return {"ref": "R1", "kind": "access", "title": "Your access", "columns": [], "rows": [], "access": sc.describe(),
            "explorer_link": None}


def run(plan: QueryPlan, ds: ScopedDataset) -> list[dict]:
    if plan.intent == "lookup_order" and plan.order_id:
        r = lookup_order(plan.order_id, ds)
        return [r] if r else []
    if plan.intent == "list_orders":
        return [list_orders(plan.order_filters, ds)]
    if plan.intent == "definition" and plan.metric:
        return [definition(plan.metric)]
    if plan.intent == "data_quality":
        return [data_quality(ds)]
    if plan.intent == "access":
        return [access(ds)]
    if plan.specs:
        return run_specs(plan, ds)
    return []
