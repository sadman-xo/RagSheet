"""Independent pandas oracle for Panorama numbers.

It reads the dataset CSV and calculates the expected values for each role scope.
It does not import application code, so a bug in the app engine cannot hide here.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

NET_EXCLUDED = ("Cancelled", "Returned")
FULFILLED = ("Delivered", "Returned")
FINANCIAL = ("cost", "profit", "profit_margin_pct", "is_loss", "profit_after_shipping")
MONTH_SEASON = {12: "Winter", 1: "Winter", 2: "Winter", 3: "Spring", 4: "Spring", 5: "Spring",
                6: "Summer", 7: "Summer", 8: "Summer", 9: "Fall", 10: "Fall", 11: "Fall"}

DIM_COLUMN = {
    "year": "year", "year_quarter": "year_quarter", "year_month": "year_month", "quarter": "quarter_n",
    "month": "month", "season": "season", "region": "region", "country": "country", "category": "category",
    "sub_category": "sub_category", "product": "product_name", "customer_segment": "customer_segment",
    "customer_gender": "customer_gender", "payment_method": "payment_method", "shipping_method": "shipping_method",
    "order_status": "order_status", "discount_band": "discount_band", "shipping_days_band": "shipping_days_band",
    "price_band": "price_band", "order_date": "order_date_str", "day_of_week": "day_of_week",
    "shipping_days": "shipping_days", "customer_id": "customer_id",
}
FILTER_COLUMN = {
    "years": "year", "quarters": "quarter_n", "months": "month", "year_months": "year_month", "regions": "region",
    "countries": "country", "categories": "category", "sub_categories": "sub_category", "products": "product_name",
    "segments": "customer_segment", "genders": "customer_gender", "statuses": "order_status",
    "shipping_methods": "shipping_method", "payment_methods": "payment_method", "discount_bands": "discount_band",
    "price_bands": "price_band", "shipping_days_bands": "shipping_days_band",
}


def _price_band(p: float) -> str:
    for edge, label in ((25, "<25"), (100, "25-100"), (250, "100-250"), (500, "250-500"), (1000, "500-1000")):
        if p < edge:
            return label
    return "1000+"


def _days_band(d: int) -> str:
    for edge, label in ((5, "<=5"), (9, "6-9"), (14, "10-14"), (19, "15-19")):
        if d <= edge:
            return label
    return "20+"


@lru_cache(maxsize=4)
def load(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")
    df.columns = [c.lower().replace("_%", "_pct") for c in df.columns]
    df = df.rename(columns={"profit_margin_pct": "profit_margin_pct"})
    df["order_date"] = pd.to_datetime(df["order_date"], format="%m/%d/%Y")
    df["order_date_str"] = df["order_date"].dt.strftime("%Y-%m-%d")
    df["year"] = df["order_date"].dt.year
    df["month"] = df["order_date"].dt.month
    df["quarter_n"] = df["order_date"].dt.quarter
    df["year_month"] = df["order_date"].dt.strftime("%Y-%m")
    df["year_quarter"] = df["year"].astype(str) + "-Q" + df["quarter_n"].astype(str)
    df["season"] = df["month"].map(MONTH_SEASON)
    df["day_of_week"] = df["order_date"].dt.strftime("%a")
    # Cent arithmetic: list value is rounded to cents like the database (numeric).
    cents = np.round(df["unit_price"].to_numpy() * 100).astype(np.int64) * df["quantity"].to_numpy()
    df["list_value"] = cents / 100.0
    df["discount_amount"] = (cents - np.round(df["revenue"].to_numpy() * 100).astype(np.int64)) / 100.0
    df["discount_band"] = (df["discount"] * 100).round().astype(int).astype(str) + "%"
    df["price_band"] = df["unit_price"].map(_price_band)
    df["shipping_days_band"] = df["shipping_days"].map(_days_band)
    df["is_net"] = ~df["order_status"].isin(NET_EXCLUDED)
    df["is_fulfilled"] = df["order_status"].isin(FULFILLED)
    df["is_loss"] = df["profit"] < 0
    df["profit_after_shipping"] = df["profit"] - df["shipping_cost"]
    return df


def scope(df: pd.DataFrame, scope_key: str) -> pd.DataFrame:
    kind, _, value = scope_key.partition(":")
    if kind == "region":
        out = df[df["region"] == value]
    elif kind == "category":
        out = df[df["category"] == value]
    elif scope_key in ("all:full", "all:pseudo", "all:nofin"):
        out = df
    else:
        raise ValueError(scope_key)
    if scope_key == "all:nofin":
        out = out.drop(columns=list(FINANCIAL))
    return out


def apply_filters(df: pd.DataFrame, filters: dict | None) -> pd.DataFrame:
    if not filters:
        return df
    mask = pd.Series(True, index=df.index)
    for name, values in filters.items():
        if values is None:
            continue
        if name == "date_from":
            mask &= df["order_date"] >= pd.Timestamp(values)
        elif name == "date_to":
            mask &= df["order_date"] <= pd.Timestamp(values)
        else:
            mask &= df[FILTER_COLUMN[name]].isin(values)
    return df[mask]


def _sum(d: pd.DataFrame, col: str) -> float:
    return float(np.round(d[col].sum(), 6)) if len(d) else 0.0


def _ratio(a: float, b: float, scale: float = 1.0) -> float | None:
    return None if b == 0 else a / b * scale


def metric(d: pd.DataFrame, m: str) -> float | None:
    st = d["order_status"]
    n = float(len(d))
    if m == "gross_revenue":
        return _sum(d, "revenue")
    if m == "net_revenue":
        return _sum(d[~st.isin(NET_EXCLUDED)], "revenue")
    if m == "delivered_revenue":
        return _sum(d[st == "Delivered"], "revenue")
    if m == "orders":
        return n
    if m == "units":
        return float(d["quantity"].sum())
    if m == "aov":
        return _ratio(_sum(d, "revenue"), n)
    if m == "return_rate":
        return _ratio(float((st == "Returned").sum()), float(st.isin(FULFILLED).sum()), 100.0)
    if m == "cancellation_rate":
        return _ratio(float((st == "Cancelled").sum()), n, 100.0)
    if m == "delivered_rate":
        return _ratio(float((st == "Delivered").sum()), n, 100.0)
    if m == "open_orders":
        return float((st == "Processing").sum())
    if m == "returned_orders":
        return float((st == "Returned").sum())
    if m == "cancelled_orders":
        return float((st == "Cancelled").sum())
    if m == "list_value":
        return _sum(d, "list_value")
    if m == "discount_amount":
        return _sum(d, "discount_amount")
    if m == "effective_discount_pct":
        return _ratio(_sum(d, "discount_amount"), _sum(d, "list_value"), 100.0)
    if m == "avg_shipping_days":
        f = d[st.isin(FULFILLED)]
        return _ratio(float(f["shipping_days"].sum()), float(len(f)))
    if m == "avg_shipping_cost":
        return _ratio(_sum(d, "shipping_cost"), n)
    if m == "shipping_cost_total":
        return _sum(d, "shipping_cost")
    if m == "unique_customers":
        return float(d["customer_id"].nunique())
    if m == "repeat_customer_rate":
        vc = d["customer_id"].value_counts()
        return _ratio(float((vc >= 2).sum()), float(len(vc)), 100.0)
    if m == "cost":
        return _sum(d, "cost")
    if m == "gross_profit":
        return _sum(d, "profit")
    if m == "net_profit":
        return _sum(d[~st.isin(NET_EXCLUDED)], "profit")
    if m == "margin_pct":
        return _ratio(_sum(d, "profit"), _sum(d, "revenue"), 100.0)
    if m == "net_margin_pct":
        nd = d[~st.isin(NET_EXCLUDED)]
        return _ratio(_sum(nd, "profit"), _sum(nd, "revenue"), 100.0)
    if m == "loss_orders":
        return float(d["is_loss"].sum())
    if m == "loss_order_pct":
        return _ratio(float(d["is_loss"].sum()), n, 100.0)
    if m == "profit_after_shipping":
        return _sum(d, "profit_after_shipping")
    raise ValueError(f"unknown metric {m}")


def query(df: pd.DataFrame, metrics: list[str], group_by: list[str] | None = None,
          filters: dict | None = None) -> dict:
    """Return {group key tuple: {metric: value}} (an empty tuple key without group_by)."""
    d = apply_filters(df, filters)
    if not group_by:
        return {(): {m: metric(d, m) for m in metrics}}
    cols = [DIM_COLUMN[g] for g in group_by]
    out = {}
    for key, g in d.groupby(cols, sort=True):
        key = key if isinstance(key, tuple) else (key,)
        out[tuple(k.item() if hasattr(k, "item") else k for k in key)] = {m: metric(g, m) for m in metrics}
    return out


# Reference values for the original 10k dataset (the plan's table)
REFERENCE = {
    "gross_revenue": 5284387.70, "net_revenue": 3845611.08, "delivered_revenue": 3308169.75,
    "gross_profit": 1437638.31, "margin_pct": 27.21, "return_rate": 22.84, "cancellation_rate": 9.08,
    "aov": 528.44, "electronics_q3_2023": (405503.83, 233), "asia_electronics_q3_2023": (108012.34, 67),
    "top_region": ("Middle East", 1348593.22), "h1_2024": 906686.06, "h1_2023": 1060864.07, "h1_change_pct": -14.53,
    "unique_customers": 5348, "repeat_customers": 2929, "repeat_rate": 54.77,
    "asia_top_country": ("China", 295780.41), "spain_return_rate": 26.70,
    "electronics_top_profit_product": ("Lenovo ThinkPad X1", 100584.09), "debit_card_cancellation": 10.77,
}


def default_csv() -> Path:
    for p in (Path("/data/raw/ecommerce_sales.csv"), Path(__file__).resolve().parents[2] / "data/raw/ecommerce_sales.csv"):
        if p.exists():
            return p
    raise FileNotFoundError("ecommerce_sales.csv")
