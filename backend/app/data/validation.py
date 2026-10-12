"""Hard checks for a dataset. If a check fails, init stops and the api does not start."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.data import vocab
from app.data.schema import CSV_COLUMNS


class DatasetError(Exception):
    """The dataset failed a hard check."""


def _fail(errors: list[str], msg: str, bad: pd.Series | None = None, df: pd.DataFrame | None = None) -> None:
    if bad is not None and df is not None:
        n = int(bad.sum())
        if n == 0:
            return
        ids = df.loc[bad, "order_id"].head(3).tolist() if "order_id" in df else []
        errors.append(f"{msg}: {n} rows (examples: {ids})")
    else:
        errors.append(msg)


def validate(df: pd.DataFrame) -> list[str]:
    """Return a list of errors. An empty list means that the dataset passed."""
    errors: list[str] = []
    expected = list(CSV_COLUMNS.values())
    if list(df.columns[: len(expected)]) != expected or len(df.columns) < len(expected):
        return [f"columns: expected {expected}, found {list(df.columns)}"]
    if len(df) == 0:
        return ["dataset is empty"]

    nulls = df[expected].isna().sum()
    for col, n in nulls.items():
        if n:
            errors.append(f"nulls in {col}: {int(n)} rows")
    if errors:
        return errors

    dup = df["order_id"].duplicated()
    _fail(errors, "duplicate order_id", dup, df)
    _fail(errors, "bad order_id format", ~df["order_id"].str.fullmatch(r"ORD-\d{6,7}"), df)
    _fail(errors, "bad customer_id format", ~df["customer_id"].str.fullmatch(r"CUST-\d{5,7}"), df)

    enums = {
        "region": vocab.REGIONS, "country": vocab.COUNTRIES, "category": vocab.CATEGORIES,
        "sub_category": vocab.SUB_CATEGORIES, "product_name": vocab.PRODUCTS,
        "customer_segment": vocab.SEGMENTS, "customer_gender": vocab.GENDERS,
        "shipping_method": vocab.SHIPPING_METHODS, "payment_method": vocab.PAYMENT_METHODS,
        "order_status": vocab.STATUSES, "season": vocab.SEASONS,
    }
    for col, allowed in enums.items():
        _fail(errors, f"unknown {col} value", ~df[col].isin(allowed), df)

    # Hierarchies
    _fail(errors, "country is not in its region", df["country"].map(vocab.COUNTRY_REGION) != df["region"], df)
    _fail(errors, "product is not in its sub-category", df["product_name"].map(vocab.PRODUCT_SUB_CATEGORY) != df["sub_category"], df)
    _fail(errors, "sub-category is not in its category", df["sub_category"].map(vocab.SUB_CATEGORY_CATEGORY) != df["category"], df)

    # Dates
    d = df["order_date"]
    _fail(errors, "year does not match the date", d.dt.year != df["year"], df)
    _fail(errors, "month does not match the date", d.dt.month != df["month"], df)
    _fail(errors, "quarter does not match the date", ("Q" + d.dt.quarter.astype(str)) != df["quarter"], df)
    _fail(errors, "season does not match the month", d.dt.month.map(vocab.MONTH_SEASON) != df["season"], df)

    # Ranges
    _fail(errors, "quantity outside 1-100", ~df["quantity"].between(1, 100), df)
    _fail(errors, "discount outside 0-0.9", ~df["discount"].between(0, 0.9), df)
    _fail(errors, "unit_price <= 0", df["unit_price"] <= 0, df)
    _fail(errors, "cost < 0", df["cost"] < 0, df)
    _fail(errors, "shipping_cost < 0", df["shipping_cost"] < 0, df)
    _fail(errors, "shipping_days outside 0-365", ~df["shipping_days"].between(0, 365), df)

    # Formulas (tolerance 0.01)
    expected_rev = np.round(df["unit_price"].to_numpy() * df["quantity"].to_numpy() * (1 - df["discount"].to_numpy()) + 1e-9, 2)
    _fail(errors, "revenue != round(unit_price * quantity * (1 - discount), 2)",
          pd.Series(np.abs(df["revenue"].to_numpy() - expected_rev) > 0.0101, index=df.index), df)
    _fail(errors, "profit != revenue - cost",
          pd.Series(np.abs(df["profit"].to_numpy() - (df["revenue"].to_numpy() - df["cost"].to_numpy())) > 0.0101, index=df.index), df)
    rev = df["revenue"].to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        margin = np.where(rev != 0, df["profit"].to_numpy() / rev * 100, 0)
    _fail(errors, "profit_margin_pct != profit / revenue * 100",
          pd.Series(np.abs(df["profit_margin_pct"].to_numpy() - margin) > 0.0201, index=df.index), df)
    return errors


def validate_or_raise(df: pd.DataFrame) -> None:
    errors = validate(df)
    if errors:
        raise DatasetError("dataset check failed: " + "; ".join(errors))
