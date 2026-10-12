"""The spec grid for the oracle and navigator tests."""

from __future__ import annotations

from app.analytics.metrics import METRICS_LIST

GRID: list[dict] = [
    {},
    {"group_by": ["region"]},
    {"group_by": ["category", "sub_category"]},
    {"time_grain": "year"},
    {"time_grain": "year_quarter", "group_by": ["category"]},
    {"group_by": ["order_status"]},
    {"group_by": ["customer_segment"], "filters": {"years": [2023]}},
    {"group_by": ["discount_band"], "filters": {"categories": ["Electronics"]}},
    {"group_by": ["shipping_method"], "filters": {"date_from": "2022-01-01", "date_to": "2022-12-31"}},
    {"group_by": ["shipping_method"], "filters": {"date_from": "2022-01-10", "date_to": "2022-11-20"}},
    {"group_by": ["payment_method"], "filters": {"statuses": ["Delivered", "Returned"]}},
    {"group_by": ["price_band"]},
    {"group_by": ["country"], "filters": {"regions": ["Asia"]}},
    {"time_grain": "year_month", "filters": {"years": [2022]}},
    {"group_by": ["region", "shipping_days_band"], "filters": {"quarters": [2, 3]}},
    {"group_by": ["product"], "filters": {"sub_categories": ["Laptops", "Tablets"], "year_months": ["2023-07", "2023-08"]}},
    {"group_by": ["customer_gender", "payment_method"], "filters": {"segments": ["VIP"]}},
    {"time_grain": "year", "group_by": ["season"]},
]

SMALL_GRID: list[dict] = [GRID[i] for i in (0, 1, 2, 4, 7, 9, 12, 15)]


def metric_chunks(financial: bool, size: int = 6) -> list[list[str]]:
    ids = [m.id for m in METRICS_LIST if financial or not m.financial]
    return [ids[i:i + size] for i in range(0, len(ids), size)]
