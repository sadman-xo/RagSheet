"""Dimension registry: group-by and filter fields.

Each dimension has a raw expression on the `orders` table and the rollups that contain it.
Time dimensions derived from the month (year, quarter, month, season, year_month, year_quarter)
are in every rollup.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.data import vocab

ROLLUPS: dict[str, tuple[str, ...]] = {
    # rollup name: non-time dimensions (order_status is in every rollup)
    "r_geo": ("region", "country", "category", "order_status"),
    "r_product": ("category", "sub_category", "product", "order_status", "discount_band"),
    "r_customer": ("customer_segment", "customer_gender", "payment_method", "shipping_method", "order_status"),
    "r_ops": ("region", "country", "shipping_method", "order_status", "shipping_days_band"),
}
TIME_ROLLUP_COLS: tuple[str, ...] = ("year_month", "year", "quarter", "month", "year_quarter", "season")

# Raw column names for dimension ids that differ
RAW_COLUMN = {"product": "product_name"}


@dataclass(frozen=True)
class Dimension:
    id: str
    label: str
    raw_expr: str
    kind: Literal["time", "text", "int"]
    order: tuple | None = None          # fixed sort order of values (None: by value)
    pii: bool = False
    time_grain: bool = False            # can be used as the time grain
    in_rollups: bool = True             # False: raw only

    def rollup_names(self) -> list[str]:
        if not self.in_rollups:
            return []
        if self.id in TIME_ROLLUP_COLS:
            return list(ROLLUPS)
        return [r for r, dims in ROLLUPS.items() if self.id in dims]


DIMENSIONS_LIST: list[Dimension] = [
    Dimension("year", "Year", "year", "int", time_grain=True),
    Dimension("year_quarter", "Quarter", "year_quarter", "time", time_grain=True),
    Dimension("year_month", "Month", "year_month", "time", time_grain=True),
    Dimension("week", "Week", "CAST(date_trunc('week', order_date) AS DATE)", "time", time_grain=True, in_rollups=False),
    Dimension("order_date", "Day", "order_date", "time", time_grain=True, in_rollups=False),
    Dimension("quarter", "Quarter of year", "quarter", "int"),
    Dimension("month", "Month of year", "month", "int"),
    Dimension("season", "Season", "season", "text", order=vocab.SEASONS),
    Dimension("day_of_week", "Day of week", "day_of_week", "text", order=vocab.DAYS_OF_WEEK, in_rollups=False),
    Dimension("region", "Region", "region", "text"),
    Dimension("country", "Country", "country", "text"),
    Dimension("category", "Category", "category", "text"),
    Dimension("sub_category", "Sub-category", "sub_category", "text"),
    Dimension("product", "Product", "product_name", "text"),
    Dimension("customer_segment", "Segment", "customer_segment", "text", order=vocab.SEGMENTS),
    Dimension("customer_gender", "Gender", "customer_gender", "text", order=vocab.GENDERS),
    Dimension("payment_method", "Payment method", "payment_method", "text"),
    Dimension("shipping_method", "Shipping method", "shipping_method", "text", order=vocab.SHIPPING_METHODS),
    Dimension("order_status", "Status", "order_status", "text", order=vocab.STATUSES),
    Dimension("discount_band", "Discount level", "discount_band", "text", order=vocab.DISCOUNT_BANDS),
    Dimension("shipping_days_band", "Shipping days band", "shipping_days_band", "text", order=vocab.SHIPPING_DAYS_BANDS),
    Dimension("price_band", "Price band", "price_band", "text", order=vocab.PRICE_BANDS, in_rollups=False),
    Dimension("shipping_days", "Shipping days", "shipping_days", "int", in_rollups=False),
    Dimension("customer_id", "Customer", "customer_id", "text", pii=True, in_rollups=False),
]

DIMENSIONS: dict[str, Dimension] = {d.id: d for d in DIMENSIONS_LIST}
TIME_GRAINS: tuple[str, ...] = tuple(d.id for d in DIMENSIONS_LIST if d.time_grain)

# Filter field -> (dimension id, allowed values or None)
FILTERS: dict[str, tuple[str, tuple | None]] = {
    "years": ("year", None),
    "quarters": ("quarter", (1, 2, 3, 4)),
    "months": ("month", tuple(range(1, 13))),
    "year_months": ("year_month", None),
    "regions": ("region", vocab.REGIONS),
    "countries": ("country", vocab.COUNTRIES),
    "categories": ("category", vocab.CATEGORIES),
    "sub_categories": ("sub_category", vocab.SUB_CATEGORIES),
    "products": ("product", vocab.PRODUCTS),
    "segments": ("customer_segment", vocab.SEGMENTS),
    "genders": ("customer_gender", vocab.GENDERS),
    "statuses": ("order_status", vocab.STATUSES),
    "shipping_methods": ("shipping_method", vocab.SHIPPING_METHODS),
    "payment_methods": ("payment_method", vocab.PAYMENT_METHODS),
    "discount_bands": ("discount_band", vocab.DISCOUNT_BANDS),
    "price_bands": ("price_band", vocab.PRICE_BANDS),
    "shipping_days_bands": ("shipping_days_band", vocab.SHIPPING_DAYS_BANDS),
}


def describe() -> list[dict]:
    return [
        {"id": d.id, "label": d.label, "kind": d.kind, "time_grain": d.time_grain, "rollup": d.in_rollups,
         "order": list(d.order) if d.order else None}
        for d in DIMENSIONS_LIST
    ]
