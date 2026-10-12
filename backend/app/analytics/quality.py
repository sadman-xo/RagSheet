"""Data Notes: the data quality problems of the dataset, with evidence from the user's own scope."""

from __future__ import annotations

from app.analytics import engine, formatting
from app.analytics.spec import Filters, QuerySpec
from app.cache import LRUCache
from app.data.scoped import ScopeFile

_cache = LRUCache(64)


def _one(sf: ScopeFile, sql: str) -> tuple:
    cur = sf.cursor()
    try:
        return cur.execute(sql).fetchone()
    finally:
        cur.close()


def _all(sf: ScopeFile, sql: str) -> list[tuple]:
    cur = sf.cursor()
    try:
        return cur.execute(sql).fetchall()
    finally:
        cur.close()


def data_notes(sf: ScopeFile, scope_key: str) -> list[dict]:
    key = (sf.data_version, scope_key)
    hit = _cache.get(key)
    if hit is not None:
        return hit
    notes: list[dict] = []
    multi = _one(sf, """
        SELECT count(*) AS customers,
               count(*) FILTER (WHERE seg > 1), count(*) FILTER (WHERE gen > 1), count(*) FILTER (WHERE ctry > 1)
        FROM (SELECT customer_id, count(DISTINCT customer_segment) seg, count(DISTINCT customer_gender) gen,
                     count(DISTINCT country) ctry FROM orders GROUP BY customer_id)""")
    notes.append({
        "id": "customer_attributes",
        "title": "Customer attributes change between orders",
        "text": ("One customer ID can have a different segment, gender, and country on different orders. "
                 "Panorama uses these attributes as \"at the time of the order\" values and never as fixed customer facts."),
        "evidence": [
            f"{formatting.count(multi[1])} of {formatting.count(multi[0])} customers in your scope have more than one segment.",
            f"{formatting.count(multi[2])} customers have more than one gender.",
            f"{formatting.count(multi[3])} customers have orders from more than one country.",
        ],
        "financial": False,
    })
    by_method = _all(sf, """
        SELECT shipping_method, avg(shipping_days) FILTER (WHERE is_fulfilled), avg(shipping_cost), count(*)
        FROM orders GROUP BY 1""")
    m = {r[0]: r for r in by_method}
    ev = [f"{name}: {formatting.days(m[name][1])}, average shipping cost {formatting.money(m[name][2])}"
          for name in ("Economy", "Standard", "Express", "Overnight") if name in m]
    if "Overnight" in m and "Economy" in m and m["Economy"][2]:
        ev.append(f"Overnight costs about {m['Overnight'][2] / m['Economy'][2]:.0f} times more than Economy.")
    by_region = _all(sf, "SELECT region, avg(shipping_days) FILTER (WHERE is_fulfilled) FROM orders GROUP BY 1 ORDER BY 2")
    ev.append("By region: " + "; ".join(f"{r[0]} {formatting.days(r[1])}" for r in by_region) + ".")
    notes.append({
        "id": "shipping_days",
        "title": "Shipping days do not depend on the shipping method",
        "text": "In this data, the region controls the delivery time, not the shipping method. A faster method costs more but is not faster.",
        "evidence": ev,
        "financial": False,
    })
    if sf.financial:
        t = engine.run_query(sf, scope_key, QuerySpec(metrics=["gross_profit", "profit_after_shipping", "shipping_cost_total", "margin_pct"]))["totals"]
        notes.append({
            "id": "profit_excludes_shipping",
            "title": "Profit does not include the shipping cost",
            "text": "Profit = revenue − cost. The shipping cost is not in the profit. \"Profit after shipping\" is an estimate, because the data does not say who pays the shipping.",
            "evidence": [f"Gross profit {formatting.money(t['gross_profit'])}; shipping cost {formatting.money(t['shipping_cost_total'])}; "
                         f"profit after shipping (estimate) {formatting.money(t['profit_after_shipping'])}."],
            "financial": True,
        })
        mean_col = _one(sf, "SELECT avg(profit_margin_pct) FROM orders")[0]
        notes.append({
            "id": "weighted_margin",
            "title": "The average of the margin column is not the margin",
            "text": "The mean of the Profit_Margin_% column gives each order the same weight. Panorama always uses the weighted margin: sum of profit / sum of revenue.",
            "evidence": [f"Mean of the column: {formatting.pct(float(mean_col))}. Weighted margin: {formatting.pct(t['margin_pct'])}."],
            "financial": True,
        })
    proc = _all(sf, "SELECT year, count(*) FROM orders WHERE order_status = 'Processing' GROUP BY 1 ORDER BY 1")
    notes.append({
        "id": "status_snapshot",
        "title": "The order status is a snapshot",
        "text": "Old orders still have the status \"Processing\". The status shows the state at the time of the data export, not the final state.",
        "evidence": ["Processing orders by order year: " + ", ".join(f"{y}: {formatting.count(n)}" for y, n in proc) + "."],
        "financial": False,
    })
    notes.append({
        "id": "revenue_statuses",
        "title": "Revenue includes cancelled and returned orders",
        "text": "The Revenue column has a value for every order. Panorama shows three revenue metrics: Gross (all statuses), Net (without Cancelled and Returned), and Realized (Delivered only).",
        "evidence": [],
        "financial": False,
    })
    t2 = engine.run_query(sf, scope_key, QuerySpec(metrics=["gross_revenue", "net_revenue", "delivered_revenue"]))["totals"]
    notes[-1]["evidence"].append(f"Gross {formatting.money(t2['gross_revenue'])}; net {formatting.money(t2['net_revenue'])}; "
                                 f"realized {formatting.money(t2['delivered_revenue'])}.")
    first = sorted(sf.monthly_orders.items())
    if first:
        low = [ym for ym, n in first if n < 0.6 * sorted(sf.monthly_orders.values())[len(first) // 2]]
        notes.append({
            "id": "volume_changes",
            "title": "Order volume changes a lot over time",
            "text": "Volume grows during 2021, is stable in 2023, and decreases from 2024-Q2. Comparisons that use these months can mislead.",
            "evidence": [f"Data from {sf.data_min:%d %b %Y} to {sf.data_max:%d %b %Y}. Months with low volume: "
                         + (", ".join(low[:6]) + (f" and {len(low) - 6} more" if len(low) > 6 else "") if low else "none") + "."],
            "financial": False,
        })
    _cache.put(key, notes)
    return notes
