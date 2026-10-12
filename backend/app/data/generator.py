"""Make a large synthetic dataset (for example 1,000,000 orders) from the original CSV.

The output is deterministic for a seed. It keeps the vocabulary (regions, countries, categories,
products, statuses), the monthly distribution, and the product mix of the original, because it
samples template rows from the original. It samples new quantities and discounts, keeps the cost
ratio of the template row, and calculates revenue, cost, and profit again with the same formulas.
The output has the same CSV format, so the loader runs the same hard checks on it.

The 1M dataset is synthetic. It is for scale tests only.
"""

from __future__ import annotations

import calendar
import time
from pathlib import Path

import numpy as np
import pandas as pd

from app.data import vocab
from app.data.loader import read_csv
from app.data.schema import CSV_COLUMNS

SEED = 20240101


def _round2(x: np.ndarray) -> np.ndarray:
    # Half-up rounding to cents, like the original data
    return np.floor(x * 100 + 0.5 + 1e-9) / 100


def generate(source: Path, rows: int, seed: int = SEED) -> pd.DataFrame:
    src = read_csv(source)
    rng = np.random.default_rng(seed)
    n_src = len(src)

    # Template rows: a uniform sample of the original keeps the joint distributions
    # (month, product, region, status, payment, shipping) of the original.
    idx = rng.integers(0, n_src, size=rows)
    t = src.iloc[idx].reset_index(drop=True)

    # Date: same month as the template, random day inside the data range
    min_d, max_d = src["order_date"].min(), src["order_date"].max()
    years = t["order_date"].dt.year.to_numpy()
    months = t["order_date"].dt.month.to_numpy()
    days_in_month = np.array([calendar.monthrange(int(y), int(m))[1] for y, m in zip(years, months)])
    first_day = np.ones(rows, dtype=int)
    last_day = days_in_month.copy()
    first_mask = (years == min_d.year) & (months == min_d.month)
    last_mask = (years == max_d.year) & (months == max_d.month)
    first_day[first_mask] = min_d.day
    last_day[last_mask] = max_d.day
    day = first_day + np.floor(rng.random(rows) * (last_day - first_day + 1)).astype(int)
    dates = pd.to_datetime({"year": years, "month": months, "day": day})

    # Quantity and discount from the original distributions
    qty_vals, qty_counts = np.unique(src["quantity"].to_numpy(), return_counts=True)
    quantity = rng.choice(qty_vals, size=rows, p=qty_counts / qty_counts.sum())
    disc_vals, disc_counts = np.unique(src["discount"].to_numpy(), return_counts=True)
    discount = rng.choice(disc_vals, size=rows, p=disc_counts / disc_counts.sum())

    # Price: template price +/- 5 %. Cost ratio: from the template row (cost / list value).
    unit_price = _round2(t["unit_price"].to_numpy() * rng.uniform(0.95, 1.05, size=rows))
    unit_price = np.maximum(unit_price, 0.01)
    tmpl_list = t["unit_price"].to_numpy() * t["quantity"].to_numpy()
    cost_ratio = t["cost"].to_numpy() / tmpl_list
    list_value = unit_price * quantity
    revenue = _round2(list_value * (1 - discount))
    cost = _round2(list_value * cost_ratio)
    profit = _round2(revenue - cost)
    margin = _round2(np.where(revenue != 0, profit / revenue * 100, 0))
    shipping_cost = _round2(t["shipping_cost"].to_numpy() * rng.uniform(0.9, 1.1, size=rows))

    # Customers: a larger pool. With 0.70 x rows IDs, about 53 % of the IDs occur and about 55 % of them
    # have 2+ orders, like the original (5,348 customers, 54.77 % repeat).
    pool = max(10, int(rows * 0.70))
    width = max(5, len(str(pool)))
    cust = rng.integers(1, pool + 1, size=rows)
    customer_id = np.char.add("CUST-", np.char.zfill(cust.astype(str), width))

    out = pd.DataFrame({
        "order_date": dates,
        "customer_id": customer_id,
        "customer_gender": t["customer_gender"].to_numpy(),
        "customer_segment": t["customer_segment"].to_numpy(),
        "region": t["region"].to_numpy(),
        "country": t["country"].to_numpy(),
        "category": t["category"].to_numpy(),
        "sub_category": t["sub_category"].to_numpy(),
        "product_name": t["product_name"].to_numpy(),
        "unit_price": unit_price,
        "quantity": quantity,
        "discount": discount,
        "revenue": revenue,
        "cost": cost,
        "profit": profit,
        "profit_margin_pct": margin,
        "shipping_cost": shipping_cost,
        "shipping_method": t["shipping_method"].to_numpy(),
        "shipping_days": t["shipping_days"].to_numpy(),
        "payment_method": t["payment_method"].to_numpy(),
        "order_status": t["order_status"].to_numpy(),
    })
    out = out.sort_values("order_date", kind="stable").reset_index(drop=True)
    id_width = max(7, len(str(rows)))
    out.insert(0, "order_id", [f"ORD-{i:0{id_width}d}" for i in range(1, rows + 1)])
    out["year"] = out["order_date"].dt.year
    out["month"] = out["order_date"].dt.month
    out["quarter"] = "Q" + out["order_date"].dt.quarter.astype(str)
    out["season"] = out["month"].map(vocab.MONTH_SEASON)
    return out[list(CSV_COLUMNS.values())]


def write_csv(df: pd.DataFrame, path: Path) -> None:
    """Write in the original CSV format (same header names and date format)."""
    out = df.copy()
    out["order_date"] = out["order_date"].dt.month.astype(str) + "/" + out["order_date"].dt.day.astype(str) + "/" + out["order_date"].dt.year.astype(str)
    out = out.rename(columns={v: k for k, v in CSV_COLUMNS.items()})
    tmp = path.with_suffix(".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(tmp, index=False, float_format="%.2f")
    tmp.replace(path)


def ensure_dataset(source: Path, target: Path, rows: int, seed: int = SEED) -> Path:
    """Make the generated file if it does not exist (init calls this)."""
    if target.exists():
        print(f"generator: {target.name} exists; skip")
        return target
    t0 = time.monotonic()
    df = generate(source, rows, seed)
    write_csv(df, target)
    print(f"generator: wrote {rows} rows to {target} in {time.monotonic() - t0:.1f} s")
    return target
