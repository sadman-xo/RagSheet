"""Insight cards for a scope. Each insight has a text template and QuerySpecs; the numbers come from the
user's own scope file. The RAG corpus stores the same insights as text + spec, never as numbers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.analytics import engine, formatting
from app.analytics.periods import resolve_preset
from app.analytics.spec import Filters, QuerySpec
from app.cache import LRUCache
from app.data.scoped import ScopeFile
from app.security.policy import Scope

_cache = LRUCache(64)


@dataclass(frozen=True)
class InsightDef:
    id: str
    title: str
    about: str            # text without numbers (RAG document)
    financial: bool
    build: Callable[[ScopeFile, Scope], dict | None]


def _q(sf: ScopeFile, scope: Scope, **kw) -> dict:
    return engine.run_query(sf, scope.scope_key, QuerySpec(**kw))


def _member_dim(scope: Scope) -> str:
    if not scope.all_regions:
        return "country"
    if not scope.all_categories:
        return "sub_category"
    return "region"


def _top_member(sf, scope):
    dim = _member_dim(scope)
    spec = dict(metrics=["gross_revenue"], group_by=[dim], limit=50)
    res = _q(sf, scope, **spec)
    if not res["rows"]:
        return None
    top = res["rows"][0]
    total = res["totals"]["gross_revenue"] or 1
    share = top["gross_revenue"] / total * 100
    label = {"region": "region", "country": "country", "sub_category": "sub-category"}[dim]
    return {"value": top["gross_revenue"], "text": f"{top[dim]} is the top {label} by gross revenue: "
            f"{formatting.money(top['gross_revenue'])} ({share:.1f}% of your total).", "spec": spec}


def _yoy(sf, scope):
    f, t, _label = resolve_preset("last_12m", sf.data_min, sf.data_max)
    spec = dict(metrics=["gross_revenue"], filters={"date_from": f.isoformat(), "date_to": t.isoformat()}, compare="prior_year_lfl")
    tot = _q(sf, scope, **spec)["totals"]
    if not tot or tot.get("gross_revenue__pct") is None:
        return None
    pct = tot["gross_revenue__pct"]
    word = "down" if pct < 0 else "up"
    return {"value": pct, "text": f"Gross revenue of the last 12 months is {word} {abs(pct):.1f}% against the same period one year "
            f"earlier ({formatting.money(tot['gross_revenue'])} vs {formatting.money(tot['gross_revenue__prior'])}). "
            "Volume decreases from 2024-Q2.", "spec": spec}


def _loss_discount(sf, scope):
    spec = dict(metrics=["loss_order_pct", "margin_pct", "orders"], group_by=["discount_band"])
    rows = {r["discount_band"]: r for r in _q(sf, scope, **spec)["rows"]}
    if "40%" not in rows:
        return None
    bands = ("0%", "5%", "10%", "15%", "20%", "25%", "30%", "40%", "50%")
    first_loss = next((b for b in bands if b in rows and (rows[b]["loss_order_pct"] or 0) > 0), None)
    first_neg = next((b for b in bands if b in rows and rows[b]["margin_pct"] is not None and rows[b]["margin_pct"] < 0), None)
    text = (f"Loss orders first appear at a {first_loss} discount. At 40%, {rows['40%']['loss_order_pct']:.1f}% of orders "
            f"lose money (weighted margin {formatting.pct(rows['40%']['margin_pct'])})")
    if "50%" in rows:
        text += f"; at 50%, {rows['50%']['loss_order_pct'] or 0:.1f}%"
    text += f". The weighted margin is negative from {first_neg}." if first_neg else "."
    return {"value": rows["40%"]["loss_order_pct"], "text": text, "spec": spec}


def _return_hotspot(sf, scope):
    dim = "country" if scope.all_categories else "sub_category"
    spec = dict(metrics=["return_rate"], group_by=[dim], sort_by="return_rate", sort_dir="desc", limit=50)
    rows = [r for r in _q(sf, scope, **spec)["rows"] if (r.get("return_rate__n") or 0) >= 30]
    tot = _q(sf, scope, metrics=["return_rate"])["totals"]
    if not rows or tot.get("return_rate") is None:
        return None
    top = rows[0]
    return {"value": top["return_rate"], "text": f"{top[dim]} has the highest return rate: {formatting.pct(top['return_rate'])} "
            f"against {formatting.pct(tot['return_rate'])} for your scope.", "spec": spec}


def _shipping(sf, scope):
    spec = dict(metrics=["avg_shipping_cost", "avg_shipping_days"], group_by=["shipping_method"])
    rows = {r["shipping_method"]: r for r in _q(sf, scope, **spec)["rows"]}
    if "Overnight" not in rows or "Economy" not in rows or not rows["Economy"]["avg_shipping_cost"]:
        return None
    o, e = rows["Overnight"], rows["Economy"]
    return {"value": o["avg_shipping_cost"] / e["avg_shipping_cost"], "text": f"Overnight shipping costs about "
            f"{o['avg_shipping_cost'] / e['avg_shipping_cost']:.0f}× Economy ({formatting.money(o['avg_shipping_cost'])} vs "
            f"{formatting.money(e['avg_shipping_cost'])} per order), but takes the same time "
            f"({formatting.days(o['avg_shipping_days'])} vs {formatting.days(e['avg_shipping_days'])}).", "spec": spec}


def _top_product(sf, scope):
    metric = "gross_profit" if scope.financial else "gross_revenue"
    spec = dict(metrics=[metric], group_by=["product"], limit=5)
    rows = _q(sf, scope, **spec)["rows"]
    if not rows:
        return None
    word = "profit" if scope.financial else "gross revenue"
    return {"value": rows[0][metric], "text": f"{rows[0]['product']} is the top product by {word} "
            f"({formatting.money(rows[0][metric])}), then {', '.join(r['product'] for r in rows[1:3])}.", "spec": spec}


def _payment_cancel(sf, scope):
    spec = dict(metrics=["cancellation_rate"], group_by=["payment_method"], sort_by="cancellation_rate", sort_dir="desc")
    rows = _q(sf, scope, **spec)["rows"]
    if len(rows) < 2:
        return None
    hi, lo = rows[0], rows[-1]
    return {"value": hi["cancellation_rate"], "text": f"{hi['payment_method']} has the highest cancellation rate "
            f"({formatting.pct(hi['cancellation_rate'])}); {lo['payment_method']} has the lowest ({formatting.pct(lo['cancellation_rate'])}).",
            "spec": spec}


def _backlog(sf, scope):
    spec = dict(metrics=["open_orders"], time_grain="year")
    rows = _q(sf, scope, **spec)["rows"]
    old = sum((r["open_orders"] or 0) for r in rows if r["year"] < sf.data_max.year - 1)
    total = sum((r["open_orders"] or 0) for r in rows)
    if not total:
        return None
    return {"value": old, "text": f"{formatting.count(total)} orders still have the status Processing; "
            f"{formatting.count(old)} of them are from {sf.data_max.year - 2} or earlier. The status is a snapshot.", "spec": spec}


def _repeat(sf, scope):
    spec = dict(metrics=["unique_customers", "repeat_customer_rate"])
    t = _q(sf, scope, **spec)["totals"]
    if not t or t.get("repeat_customer_rate") is None:
        return None
    return {"value": t["repeat_customer_rate"], "text": f"{formatting.pct(t['repeat_customer_rate'])} of "
            f"{formatting.count(t['unique_customers'])} customers ordered two or more times.", "spec": spec}


def _season(sf, scope):
    spec = dict(metrics=["orders", "gross_revenue"], group_by=["month"], filters={"years": [2023]})
    rows = _q(sf, scope, **spec)["rows"]
    if not rows:
        return None
    best = max(rows, key=lambda r: r["gross_revenue"] or 0)
    worst = min(rows, key=lambda r: r["gross_revenue"] or 0)
    import calendar

    return {"value": best["gross_revenue"], "text": f"In 2023 (the most stable year), {calendar.month_name[best['month']]} had the "
            f"highest gross revenue ({formatting.money(best['gross_revenue'])}) and {calendar.month_name[worst['month']]} the lowest "
            f"({formatting.money(worst['gross_revenue'])}).", "spec": spec}


def _aov(sf, scope):
    spec = dict(metrics=["aov"], time_grain="year")
    rows = [r for r in _q(sf, scope, **spec)["rows"] if r["aov"] is not None]
    if len(rows) < 2:
        return None
    return {"value": rows[-1]["aov"], "text": "Average order value by year: " + ", ".join(
        f"{r['year']} {formatting.money(r['aov'])}" for r in rows) + ".", "spec": spec}


def _margin(sf, scope):
    spec = dict(metrics=["margin_pct", "net_margin_pct"], group_by=["category"])
    res = _q(sf, scope, **spec)
    rows = res["rows"]
    if not rows:
        return None
    best = max(rows, key=lambda r: r["margin_pct"] or 0)
    t = res["totals"]
    return {"value": t["margin_pct"], "text": f"Your weighted margin is {formatting.pct(t['margin_pct'])} "
            f"(net {formatting.pct(t['net_margin_pct'])}). {best['category']} has the highest margin ({formatting.pct(best['margin_pct'])}).",
            "spec": spec}


INSIGHTS: list[InsightDef] = [
    InsightDef("top_member", "Top contributor", "Which region, country, or sub-category has the most gross revenue, and its share of the total.", False, _top_member),
    InsightDef("yoy", "Last 12 months vs prior year", "Gross revenue of the last 12 months compared with the same period one year earlier (like-for-like).", False, _yoy),
    InsightDef("loss_discount", "Discounts and loss orders", "The discount level where loss orders start, and the share of loss orders at high discounts.", True, _loss_discount),
    InsightDef("return_hotspot", "Return hot spot", "The country or sub-category with the highest return rate compared with the scope.", False, _return_hotspot),
    InsightDef("shipping_cost", "Shipping cost vs speed", "Overnight shipping costs much more than Economy but is not faster.", False, _shipping),
    InsightDef("top_product", "Top products", "The leading products of your scope.", False, _top_product),
    InsightDef("payment_cancel", "Cancellations by payment method", "The payment methods with the highest and lowest cancellation rates.", False, _payment_cancel),
    InsightDef("backlog", "Old Processing orders", "Orders that still have the status Processing, and how old they are.", False, _backlog),
    InsightDef("repeat_customers", "Repeat customers", "The share of customers with two or more orders.", False, _repeat),
    InsightDef("seasonality", "Seasonality", "The months with the highest and the lowest revenue in the most stable year.", False, _season),
    InsightDef("aov_trend", "Average order value trend", "Average order value for each year.", False, _aov),
    InsightDef("margin", "Margin", "The weighted margin and the category with the highest margin.", True, _margin),
]
INSIGHTS_BY_ID = {i.id: i for i in INSIGHTS}


def insights(sf: ScopeFile, scope: Scope) -> list[dict]:
    key = (sf.data_version, scope.scope_key)
    hit = _cache.get(key)
    if hit is not None:
        return hit
    out = []
    for d in INSIGHTS:
        if d.financial and not scope.financial:
            continue
        try:
            r = d.build(sf, scope)
        except Exception as exc:  # an insight must never break the page
            print(f"insight {d.id} failed: {exc}", flush=True)
            r = None
        if r:
            out.append({"id": d.id, "title": d.title, "text": r["text"], "value": r["value"], "spec": r["spec"],
                        "financial": d.financial})
    _cache.put(key, out)
    return out


def spec_of(spec: dict) -> QuerySpec:
    return QuerySpec(**spec)


__all__ = ["insights", "INSIGHTS", "INSIGHTS_BY_ID", "Filters", "spec_of"]
