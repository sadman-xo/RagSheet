"""Template answers: exact numbers from the tool results, without the LLM.

They are used for simple intents (a KPI, an order lookup, a definition, access, data quality, a short top-N),
in basic mode (AI busy or not available), and when the grounding check replaces an AI answer.
"""

from __future__ import annotations

from app.analytics import formatting
from app.analytics.metrics import METRICS
from app.chat.plan import QueryPlan

DIM_LABEL = {"region": "region", "country": "country", "category": "category", "sub_category": "sub-category",
             "product": "product", "customer_segment": "segment", "customer_gender": "gender", "payment_method": "payment method",
             "shipping_method": "shipping method", "order_status": "status", "discount_band": "discount level",
             "customer_id": "customer", "year": "year", "year_quarter": "quarter", "year_month": "month", "month": "month",
             "quarter": "quarter", "season": "season", "price_band": "price band", "shipping_days_band": "shipping days band",
             "day_of_week": "weekday", "week": "week", "order_date": "day", "shipping_days": "shipping days"}


def _v(mid: str, v) -> str:
    return formatting.metric_value(mid, v)


def _filters_text(spec: dict | None) -> str:
    if not spec:
        return ""
    f = spec.get("filters") or {}
    parts = []
    for k in ("regions", "countries", "categories", "sub_categories", "products", "segments", "statuses",
              "shipping_methods", "payment_methods", "discount_bands"):
        if f.get(k):
            parts.append(", ".join(f[k]))
    if f.get("quarters") and f.get("years"):
        parts.append(" and ".join(f"Q{q}" for q in f["quarters"]) + " " + ", ".join(map(str, f["years"])))
    elif f.get("months") and f.get("years"):
        names = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        ms = f["months"]
        label = f"{names[ms[0]]}–{names[ms[-1]]}" if len(ms) > 1 and ms == list(range(ms[0], ms[-1] + 1)) else ", ".join(names[m] for m in ms)
        parts.append(f"{label} {', '.join(map(str, f['years']))}")
    elif f.get("years"):
        parts.append(", ".join(map(str, f["years"])))
    if f.get("date_from") or f.get("date_to"):
        parts.append(f"{f.get('date_from', 'start')} to {f.get('date_to', 'end')}")
    return " for " + ", ".join(parts) if parts else ""


def _metric_sentence(r: dict) -> str:
    t = r.get("totals") or {}
    metrics = [c["key"] for c in r["columns"] if c["role"] == "metric"]
    if not metrics:
        return ""
    first = metrics[0]
    s = f"{METRICS[first].label}{_filters_text(r.get('spec'))} is {_v(first, t.get(first))}"
    if t.get(f"{first}__prior") is not None:
        s += f" ({formatting.delta_text(first, t.get(first), t.get(first + '__prior'))} vs {_v(first, t.get(first + '__prior'))} in the comparison period)"
    rest = [f"{METRICS[m].label.lower()} {_v(m, t.get(m))}" for m in metrics[1:]]
    if rest:
        s += "; " + "; ".join(rest)
    return s + f" [{r['ref']}]."


def _rows_sentence(r: dict, n: int = 5) -> str:
    dims = [c["key"] for c in r["columns"] if c["role"] == "dim"]
    metrics = [c["key"] for c in r["columns"] if c["role"] == "metric"]
    if not dims or not metrics or not r["rows"]:
        return "No rows match." if not r["rows"] else ""
    m = metrics[0]
    d = dims[-1] if len(dims) > 1 else dims[0]
    items = []
    for row in r["rows"][:n]:
        label = " / ".join(str(row[x]) for x in dims)
        item = f"{label} {_v(m, row.get(m))}"
        if row.get(f"{m}__pct") is not None or row.get(f"{m}__delta") is not None:
            item += f" ({formatting.delta_text(m, row.get(m), row.get(m + '__prior'))})"
        items.append(item)
    more = f" ({r['row_count'] - n} more in the table)" if r.get("row_count", 0) > n else ""
    head = f"{METRICS[m].label} by {DIM_LABEL.get(d, d)}{_filters_text(r.get('spec'))}: "
    return head + "; ".join(items) + f"{more} [{r['ref']}]."


def answer(plan: QueryPlan, results: list[dict], scope_label: str = "") -> str:
    intent = plan.intent
    if intent == "clarify":
        return plan.clarify or "Can you say which metric, period, and group you mean?"
    if not results:
        if intent == "lookup_order":
            return f"I did not find order {plan.order_id} in your data."
        return "I did not find data for this question in your scope."
    r0 = results[0]
    if intent == "lookup_order":
        row = r0["rows"][0]
        parts = [f"Order {row.get('order_id')} from {row.get('order_date')}: {row.get('product_name')} × {row.get('quantity')}",
                 f"revenue {formatting.money(row.get('revenue'))}", f"status {row.get('order_status')}",
                 f"{row.get('shipping_method')} shipping, {row.get('shipping_days')} days", f"to {row.get('country')}"]
        if "profit" in row:
            parts.append(f"profit {formatting.money(row.get('profit'))}")
        return ", ".join(parts) + " [R1]."
    if intent == "list_orders":
        return f"{formatting.count(r0['row_count'])} orders match. The table shows the newest {len(r0['rows'])} [R1]."
    if intent == "definition":
        d = r0["definition"]
        return f"{d['label']}: {d['description']} Formula: {d['formula']}."
    if intent == "data_quality":
        lines = [f"{i + 1}. {n['title']}: {n['text']}" for i, n in enumerate(r0["notes_list"][:6])]
        return "Known data quality notes for your data:\n" + "\n".join(lines)
    if intent == "access":
        a = r0["access"]
        fin = "you can see cost, profit, and margin" if a["financial"] else "you cannot see cost, profit, or margin"
        pii = "real customer IDs" if a["pii"] == "raw" else "customer pseudonyms (C-…)"
        tot = "company totals" if a["company_totals"] else "no company totals"
        return f"Your data scope: {a['label']}. In it, {fin}; you see {pii} and {tot}."
    sentences = []
    for r in results:
        if r["kind"] != "table":
            continue
        dims = [c for c in r["columns"] if c["role"] == "dim"]
        sentences.append(_rows_sentence(r) if dims else _metric_sentence(r))
    text = " ".join(s for s in sentences if s)
    return text or "I did not find data for this question in your scope."


def basic_answer(plan: QueryPlan, results: list[dict], reason: str) -> tuple[str, str]:
    notice = ("The AI is busy. This is the direct result." if reason in ("busy", "rate_limited")
              else "The AI is not available. This is the direct result.")
    return answer(plan, results), notice
