"""Rollup tables inside each scope file: additive measures only, grouped by month, a few dimensions, and status.

The rollup size depends on the vocabulary, not on the number of orders.
"""

from __future__ import annotations

from app.analytics.dimensions import RAW_COLUMN, ROLLUPS, TIME_ROLLUP_COLS

PUBLIC_MEASURES: tuple[tuple[str, str], ...] = (
    ("n_orders", "COUNT(*)"),
    ("units", "CAST(SUM(quantity) AS BIGINT)"),
    ("revenue", "SUM(revenue)"),
    ("list_value", "SUM(list_value)"),
    ("discount_amount", "SUM(discount_amount)"),
    ("shipping_cost", "SUM(shipping_cost)"),
    ("ship_days_sum", "CAST(SUM(CASE WHEN is_fulfilled THEN shipping_days END) AS BIGINT)"),
    ("ship_days_n", "CAST(SUM(CASE WHEN is_fulfilled THEN 1 ELSE 0 END) AS BIGINT)"),
)
FINANCIAL_MEASURES: tuple[tuple[str, str], ...] = (
    ("cost", "SUM(cost)"),
    ("profit", "SUM(profit)"),
    ("loss_n", "CAST(SUM(CASE WHEN is_loss THEN 1 ELSE 0 END) AS BIGINT)"),
    ("profit_after_shipping", "SUM(profit_after_shipping)"),
)


def rollup_sql(name: str, financial: bool) -> str:
    dims = ROLLUPS[name]
    dim_cols = [f"{RAW_COLUMN.get(d, d)} AS {d}" for d in dims]
    measures = PUBLIC_MEASURES + (FINANCIAL_MEASURES if financial else ())
    measure_cols = [f"{expr} AS {col}" for col, expr in measures]
    cols = list(TIME_ROLLUP_COLS) + dim_cols + measure_cols
    group = ", ".join(str(i + 1) for i in range(len(TIME_ROLLUP_COLS) + len(dims)))
    return f"CREATE TABLE {name} AS SELECT {', '.join(cols)} FROM orders GROUP BY {group} ORDER BY year_month"


def all_rollup_sql(financial: bool) -> list[str]:
    return [rollup_sql(name, financial) for name in ROLLUPS]
