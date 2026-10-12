"""Metric registry: the single source of truth for dashboards, exports, chat, and the glossary.

Each metric is an SQL expression over *base measures*. The same expression runs on the raw
`orders` table and on the rollup tables, because a rollup stores the sums of the base measures
grouped by order status. A metric is *additive* when all its base measures are sums.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

from app.data import vocab

Kind = Literal["money", "count", "pct", "number", "days"]

NET = tuple(s for s in vocab.STATUSES if s not in vocab.NET_EXCLUDED_STATUSES)
FULFILLED = vocab.FULFILLED_STATUSES

# Base measures: raw expression (on orders) and rollup column
MEASURES: dict[str, tuple[str, str, bool]] = {
    # name: (raw expression, rollup column, financial)
    "n": ("1", "n_orders", False),
    "units": ("quantity", "units", False),
    "revenue": ("revenue", "revenue", False),
    "list_value": ("list_value", "list_value", False),
    "discount_amount": ("discount_amount", "discount_amount", False),
    "shipping_cost": ("shipping_cost", "shipping_cost", False),
    "ship_days": ("CASE WHEN is_fulfilled THEN shipping_days END", "ship_days_sum", False),
    "ship_n": ("CASE WHEN is_fulfilled THEN 1 ELSE 0 END", "ship_days_n", False),
    "cost": ("cost", "cost", True),
    "profit": ("profit", "profit", True),
    "loss_n": ("CASE WHEN is_loss THEN 1 ELSE 0 END", "loss_n", True),
    "pas": ("profit_after_shipping", "profit_after_shipping", True),
}


class Agg:
    """Builds SUM(...) FILTER (...) expressions for the raw table or a rollup."""

    def __init__(self, rollup: bool):
        self.rollup = rollup

    def s(self, measure: str, statuses: tuple[str, ...] | None = None) -> str:
        raw, col, _ = MEASURES[measure]
        expr = col if self.rollup else raw
        f = f" FILTER (WHERE order_status IN ({vocab.sql_in_list(statuses)}))" if statuses else ""
        return f"CAST(COALESCE(SUM({expr}){f}, 0) AS DOUBLE)"

    @staticmethod
    def ratio(num: str, den: str, scale: float = 1.0) -> str:
        s = f" * {scale}" if scale != 1.0 else ""
        return f"({num}) / NULLIF({den}, 0){s}"


@dataclass(frozen=True)
class Metric:
    id: str
    label: str
    description: str
    kind: Kind
    financial: bool
    additive: bool
    expr: Callable[[Agg], str] | None
    n_expr: Callable[[Agg], str] | None = None
    higher_is_better: bool | None = True
    synonyms: tuple[str, ...] = ()
    measures: tuple[str, ...] = ()
    formula: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def is_rate(self) -> bool:
        return self.n_expr is not None


def _m(id, label, description, kind, financial, expr, measures, n_expr=None, additive=True, hib=True, synonyms=(), formula=""):
    return Metric(id=id, label=label, description=description, kind=kind, financial=financial, additive=additive,
                  expr=expr, n_expr=n_expr, higher_is_better=hib, synonyms=tuple(synonyms), measures=tuple(measures),
                  formula=formula)


METRICS_LIST: list[Metric] = [
    _m("gross_revenue", "Gross revenue",
       "Sum of revenue of all orders, all statuses. \"Revenue\" and \"sales\" mean this metric.",
       "money", False, lambda a: a.s("revenue"), ["revenue"],
       synonyms=("revenue", "sales", "gross sales", "turnover", "total sales", "gross revenue"),
       formula="SUM(revenue)"),
    _m("net_revenue", "Net revenue",
       "Sum of revenue without Cancelled and Returned orders.",
       "money", False, lambda a: a.s("revenue", NET), ["revenue"],
       synonyms=("net sales", "net revenue"), formula="SUM(revenue) where status is not Cancelled and not Returned"),
    _m("delivered_revenue", "Realized revenue",
       "Sum of revenue of Delivered orders only.",
       "money", False, lambda a: a.s("revenue", ("Delivered",)), ["revenue"],
       synonyms=("realized revenue", "delivered revenue", "realised revenue"), formula="SUM(revenue) where status is Delivered"),
    _m("orders", "Orders", "Number of orders (all statuses).", "count", False,
       lambda a: a.s("n"), ["n"], synonyms=("orders", "order count", "number of orders", "transactions"), formula="COUNT(orders)"),
    _m("units", "Units", "Number of units sold (sum of quantity).", "count", False,
       lambda a: a.s("units"), ["units"], synonyms=("units", "quantity", "items sold", "volume"), formula="SUM(quantity)"),
    _m("aov", "Average order value", "Gross revenue / orders.", "money", False,
       lambda a: Agg.ratio(a.s("revenue"), a.s("n")), ["revenue", "n"], n_expr=lambda a: a.s("n"),
       synonyms=("aov", "average order value", "average order size", "basket size"), formula="gross revenue / orders"),
    _m("return_rate", "Return rate", "Returned / (Delivered + Returned) orders × 100.", "pct", False,
       lambda a: Agg.ratio(a.s("n", ("Returned",)), a.s("n", FULFILLED), 100.0), ["n"],
       n_expr=lambda a: a.s("n", FULFILLED), hib=False, synonyms=("return rate", "returns rate", "returns"),
       formula="Returned / (Delivered + Returned)"),
    _m("cancellation_rate", "Cancellation rate", "Cancelled orders / all orders × 100.", "pct", False,
       lambda a: Agg.ratio(a.s("n", ("Cancelled",)), a.s("n"), 100.0), ["n"], n_expr=lambda a: a.s("n"), hib=False,
       synonyms=("cancellation rate", "cancel rate", "cancellations"), formula="Cancelled / orders"),
    _m("delivered_rate", "Delivered rate", "Delivered orders / all orders × 100.", "pct", False,
       lambda a: Agg.ratio(a.s("n", ("Delivered",)), a.s("n"), 100.0), ["n"], n_expr=lambda a: a.s("n"),
       synonyms=("delivered rate", "delivery rate", "fulfilment rate"), formula="Delivered / orders"),
    _m("open_orders", "Open orders", "Orders with the status Processing (a snapshot).", "count", False,
       lambda a: a.s("n", vocab.OPEN_STATUSES), ["n"], hib=None,
       synonyms=("open orders", "processing orders", "backlog", "pending orders"), formula="COUNT(status = Processing)"),
    _m("returned_orders", "Returned orders", "Number of orders with the status Returned.", "count", False,
       lambda a: a.s("n", ("Returned",)), ["n"], hib=False, synonyms=("returned orders",), formula="COUNT(status = Returned)"),
    _m("cancelled_orders", "Cancelled orders", "Number of orders with the status Cancelled.", "count", False,
       lambda a: a.s("n", ("Cancelled",)), ["n"], hib=False, synonyms=("cancelled orders",), formula="COUNT(status = Cancelled)"),
    _m("list_value", "List value", "Unit price × quantity before the discount.", "money", False,
       lambda a: a.s("list_value"), ["list_value"], hib=None, synonyms=("list value", "gross list value"), formula="SUM(unit_price × quantity)"),
    _m("discount_amount", "Discount amount", "List value − revenue.", "money", False,
       lambda a: a.s("discount_amount"), ["discount_amount"], hib=False, synonyms=("discount amount", "discounts given"),
       formula="SUM(list value − revenue)"),
    _m("effective_discount_pct", "Effective discount", "Discount amount / list value × 100.", "pct", False,
       lambda a: Agg.ratio(a.s("discount_amount"), a.s("list_value"), 100.0), ["discount_amount", "list_value"],
       n_expr=lambda a: a.s("n"), hib=None, synonyms=("effective discount", "average discount", "discount rate", "discount"),
       formula="discount amount / list value"),
    _m("avg_shipping_days", "Average shipping days", "Average shipping days of Delivered and Returned orders.", "days", False,
       lambda a: Agg.ratio(a.s("ship_days"), a.s("ship_n")), ["ship_days", "ship_n"], n_expr=lambda a: a.s("ship_n"), hib=False,
       synonyms=("shipping days", "delivery time", "average shipping days", "delivery days", "shipping time", "lead time"),
       formula="AVG(shipping_days) for Delivered + Returned"),
    _m("avg_shipping_cost", "Average shipping cost", "Shipping cost / orders.", "money", False,
       lambda a: Agg.ratio(a.s("shipping_cost"), a.s("n")), ["shipping_cost", "n"], n_expr=lambda a: a.s("n"), hib=False,
       synonyms=("average shipping cost", "shipping cost per order"), formula="SUM(shipping_cost) / orders"),
    _m("shipping_cost_total", "Shipping cost", "Sum of shipping cost.", "money", False,
       lambda a: a.s("shipping_cost"), ["shipping_cost"], hib=False, synonyms=("shipping cost", "total shipping cost", "freight"),
       formula="SUM(shipping_cost)"),
    _m("unique_customers", "Unique customers", "Number of distinct customer IDs.", "count", False,
       None, [], additive=False, synonyms=("customers", "unique customers", "customer count", "number of customers"),
       formula="COUNT(DISTINCT customer_id)"),
    _m("repeat_customer_rate", "Repeat customer rate", "Share of customers with 2 or more orders × 100.", "pct", False,
       None, [], additive=False, synonyms=("repeat rate", "repeat customers", "returning customers", "repeat customer rate", "loyalty"),
       formula="customers with 2+ orders / customers"),
    _m("cost", "Cost", "Sum of the cost of goods.", "money", True,
       lambda a: a.s("cost"), ["cost"], hib=False, synonyms=("cost", "costs", "cogs", "cost of goods"), formula="SUM(cost)"),
    _m("gross_profit", "Gross profit", "Revenue − cost, all statuses. Shipping cost is not included.", "money", True,
       lambda a: a.s("profit"), ["profit"], synonyms=("profit", "gross profit", "earnings", "profits"), formula="SUM(profit)"),
    _m("net_profit", "Net profit", "Profit without Cancelled and Returned orders.", "money", True,
       lambda a: a.s("profit", NET), ["profit"], synonyms=("net profit",), formula="SUM(profit) where status is not Cancelled/Returned"),
    _m("margin_pct", "Margin", "Weighted margin: sum of profit / sum of revenue × 100. Never the average of the margin column.",
       "pct", True, lambda a: Agg.ratio(a.s("profit"), a.s("revenue"), 100.0), ["profit", "revenue"], n_expr=lambda a: a.s("n"),
       synonyms=("margin", "profit margin", "gross margin", "margin %", "profitability"), formula="SUM(profit) / SUM(revenue)"),
    _m("net_margin_pct", "Net margin", "Net profit / net revenue × 100.", "pct", True,
       lambda a: Agg.ratio(a.s("profit", NET), a.s("revenue", NET), 100.0), ["profit", "revenue"], n_expr=lambda a: a.s("n", NET),
       synonyms=("net margin",), formula="net profit / net revenue"),
    _m("loss_orders", "Loss orders", "Number of orders with profit below zero.", "count", True,
       lambda a: a.s("loss_n"), ["loss_n"], hib=False, synonyms=("loss orders", "loss-making orders", "unprofitable orders"),
       formula="COUNT(profit < 0)"),
    _m("loss_order_pct", "Loss order share", "Orders with profit below zero / orders × 100.", "pct", True,
       lambda a: Agg.ratio(a.s("loss_n"), a.s("n"), 100.0), ["loss_n", "n"], n_expr=lambda a: a.s("n"), hib=False,
       synonyms=("loss share", "loss rate", "share of loss orders", "loss order share"), formula="COUNT(profit < 0) / orders"),
    _m("profit_after_shipping", "Profit after shipping (estimate)", "Profit − shipping cost. An estimate.", "money", True,
       lambda a: a.s("pas"), ["pas"], synonyms=("profit after shipping",), formula="SUM(profit − shipping_cost)"),
]

METRICS: dict[str, Metric] = {m.id: m for m in METRICS_LIST}
FINANCIAL_METRICS: frozenset[str] = frozenset(m.id for m in METRICS_LIST if m.financial)
NON_ADDITIVE: frozenset[str] = frozenset(m.id for m in METRICS_LIST if not m.additive)

# Words that point to a financial (hidden for operations) metric
FINANCIAL_WORDS: tuple[str, ...] = (
    "profit", "profits", "profitable", "profitability", "margin", "margins", "cost", "costs", "cogs", "loss", "losses",
    "earnings", "markup", "unprofitable",
)


def _financial_text_re():
    import re

    terms = {"profit_margin_pct", "profit_after_shipping", "is_loss", "gross_profit", "net_profit", "margin_pct",
             "net_margin_pct", "loss_orders", "loss_order_pct"}
    terms |= {m.label for m in METRICS_LIST if m.financial and "Cost" != m.label}
    words = (r"profits?|profitab\w*|unprofitable|margins?|loss(?:es)?|loss orders?|loss-making|cogs|markups?|earnings|"
             r"(?:lose|loses|losing|lost|make|makes|making|made) money|money[- ]losing")
    pattern = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
    # "cost" is financial, but "shipping cost" is public operational data.
    return re.compile(rf"\b({pattern}|{words})\b|(?<!shipping )(?<!shipping_)\bcosts?\b", re.I)


FINANCIAL_TEXT_RE = _financial_text_re()


def mentions_financial(text: str) -> bool:
    return bool(FINANCIAL_TEXT_RE.search(text or ""))


def metric_ids(financial: bool) -> list[str]:
    return [m.id for m in METRICS_LIST if financial or not m.financial]


def describe(financial: bool) -> list[dict]:
    return [
        {"id": m.id, "label": m.label, "description": m.description, "kind": m.kind, "financial": m.financial,
         "additive": m.additive, "rate": m.is_rate, "higher_is_better": m.higher_is_better, "formula": m.formula,
         "synonyms": list(m.synonyms)}
        for m in METRICS_LIST if financial or not m.financial
    ]
