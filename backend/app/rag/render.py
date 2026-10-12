"""Render retrieved documents with numbers from the user's own scope file.

Summary and entity documents keep a QuerySpec. The spec runs on the user's scope file (through the
navigator), after authorize(). Thus every number comes from the user's own data.
"""

from __future__ import annotations

from app.analytics import engine, formatting
from app.analytics.insights import INSIGHTS_BY_ID
from app.analytics.metrics import METRICS
from app.analytics.spec import QuerySpec
from app.rag.retriever import Hit
from app.security.deps import ScopedDataset
from app.security.policy import PolicyError, authorize


def _fmt_row(row: dict, metrics: list[str]) -> str:
    return "; ".join(f"{METRICS[m].label.lower()} {formatting.metric_value(m, row.get(m))}" for m in metrics if row.get(m) is not None)


def render_spec(spec_dict: dict, ds: ScopedDataset, title: str) -> str | None:
    spec_dict = dict(spec_dict)
    metrics = [m for m in spec_dict.get("metrics", []) if ds.scope.financial or not METRICS[m].financial]
    if ds.scope.financial and "margin_pct" not in metrics and len(metrics) < 6 and spec_dict.get("group_by") != ["discount_band"]:
        metrics.append("margin_pct")
    if not metrics:
        return None
    spec_dict["metrics"] = metrics
    try:
        spec = QuerySpec(**spec_dict)
        authorize(spec, ds.scope)
    except (PolicyError, ValueError):
        return None
    res = engine.run_query(ds.file, ds.scope.scope_key, spec)
    if not res["rows"] and not res["totals"]:
        return f"{title}: no orders in your data."
    parts = []
    tot = res["totals"] or {}
    if tot and (tot.get("orders") or tot.get("gross_revenue")):
        parts.append(f"{title}: {_fmt_row(tot, metrics)}.")
    elif not spec.dims():
        return f"{title}: no orders in your data."
    dims = spec.dims()
    if dims and res["rows"]:
        d = dims[-1] if spec.time_grain and len(dims) > 1 else dims[0]
        label = "By " + d.replace("_", " ")
        lines = []
        for r in res["rows"][:5]:
            lines.append(f"{r[d]}: {_fmt_row(r, metrics[:3])}")
        parts.append(f"{label}: " + " | ".join(lines) + ".")
    return " ".join(parts) if parts else None


def render(hits: list[Hit], ds: ScopedDataset) -> list[dict]:
    out = []
    for i, h in enumerate(hits, start=1):
        text_ = h.body
        numbers = False
        if h.kind in ("summary", "entity") and h.spec:
            rendered = render_spec(h.spec, ds, h.title.split(": ", 1)[-1])
            if rendered:
                text_ = (h.body + " " + rendered) if h.kind == "entity" else rendered
                numbers = True
            elif h.kind == "summary":
                continue  # outside the scope or no data: do not show the snippet
        elif h.kind == "insight":
            d = INSIGHTS_BY_ID.get(h.meta.get("insight", ""))
            if d is None or (d.financial and not ds.scope.financial):
                continue
            try:
                r = d.build(ds.file, ds.scope)
            except Exception:
                r = None
            if not r:
                continue
            text_ = r["text"]
            numbers = True
        out.append({"ref": f"S{len(out) + 1}", "doc_key": h.doc_key, "kind": h.kind, "title": h.title, "text": text_,
                    "deep_link": h.deep_link, "score": round(float(h.score), 5), "numbers": numbers})
    return out
