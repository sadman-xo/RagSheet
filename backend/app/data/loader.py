"""Read a dataset file, check it, and load it into the PostgreSQL star schema.

Only this module and generator.py read dataset files (test_architecture checks it).
"""

from __future__ import annotations

import hashlib
import hmac
import io
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg

from app.data import vocab
from app.data.schema import CSV_COLUMNS, CSV_HEADER
from app.data.validation import DatasetError, validate_or_raise

DTYPES = {
    "Order_ID": "string", "Year": "int16", "Month": "int16", "Quarter": "string", "Season": "string",
    "Customer_ID": "string", "Customer_Gender": "string", "Customer_Segment": "string", "Region": "string",
    "Country": "string", "Category": "string", "Sub_Category": "string", "Product_Name": "string",
    "Unit_Price": "float64", "Quantity": "int32", "Discount": "float64", "Revenue": "float64", "Cost": "float64",
    "Profit": "float64", "Profit_Margin_%": "float64", "Shipping_Cost": "float64", "Shipping_Method": "string",
    "Shipping_Days": "int32", "Payment_Method": "string", "Order_Status": "string", "Order_Date": "string",
}


@dataclass(frozen=True)
class Dataset:
    path: Path
    name: str
    data_version: str
    df: pd.DataFrame

    @property
    def rows(self) -> int:
        return len(self.df)


def file_version(path: Path) -> str:
    """data_version = sha256 of the dataset file (first 12 characters)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()[:12]


def read_csv(path: Path, chunksize: int = 250_000) -> pd.DataFrame:
    """Read the CSV (the header can have a BOM) in chunks, rename the columns, and parse the dates."""
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        header = fh.readline().strip().split(",")
    if tuple(header) != CSV_HEADER:
        raise DatasetError(f"header: expected {len(CSV_HEADER)} columns {list(CSV_HEADER)}, found {header}")
    parts = []
    for chunk in pd.read_csv(path, encoding="utf-8-sig", dtype=DTYPES, chunksize=chunksize, keep_default_na=True):
        parts.append(chunk)
    df = pd.concat(parts, ignore_index=True) if len(parts) > 1 else parts[0]
    df = df.rename(columns=CSV_COLUMNS)
    try:
        df["order_date"] = pd.to_datetime(df["order_date"], format="%m/%d/%Y")
    except (ValueError, TypeError) as exc:
        raise DatasetError(f"order_date: cannot parse with %m/%d/%Y: {exc}") from exc
    return df


def read_dataset(path: Path, name: str) -> Dataset:
    t0 = time.monotonic()
    df = read_csv(path)
    validate_or_raise(df)
    ds = Dataset(path=path, name=name, data_version=file_version(path), df=df)
    print(f"loader: read {ds.rows} rows from {path.name} in {time.monotonic() - t0:.1f} s (data_version {ds.data_version})")
    return ds


# ---------------------------------------------------------------------------
# Pseudonyms
# ---------------------------------------------------------------------------
_B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"


def _b32(digest: bytes, n: int = 8) -> str:
    v = int.from_bytes(digest[:5], "big")  # 40 bits -> 8 base32 characters
    return "".join(_B32[(v >> (5 * (n - 1 - i))) & 31] for i in range(n))


def customer_keys(customer_ids: list[str], key: bytes) -> dict[str, str]:
    """HMAC pseudonyms C-XXXXXXXX. Collisions get a deterministic second hash (sorted input)."""
    out: dict[str, str] = {}
    used: set[str] = set()
    for cid in sorted(customer_ids):
        attempt = 0
        while True:
            msg = cid if attempt == 0 else f"{cid}#{attempt}"
            k = "C-" + _b32(hmac.new(key, msg.encode(), hashlib.sha256).digest())
            if k not in used:
                break
            attempt += 1
        used.add(k)
        out[cid] = k
    return out


# ---------------------------------------------------------------------------
# Load into PostgreSQL (runs in init as panorama_owner)
# ---------------------------------------------------------------------------
def current_version(conn: psycopg.Connection) -> str | None:
    row = conn.execute("SELECT data_version FROM sales.meta WHERE id = 1").fetchone()
    return row[0] if row else None


def _copy_df(cur: psycopg.Cursor, table: str, cols: list[str], df: pd.DataFrame, chunk: int = 100_000) -> None:
    with cur.copy(f"COPY {table} ({', '.join(cols)}) FROM STDIN WITH (FORMAT csv)") as cp:
        for start in range(0, len(df), chunk):
            buf = io.StringIO()
            df.iloc[start:start + chunk][cols].to_csv(buf, header=False, index=False)
            cp.write(buf.getvalue())


def load_to_postgres(conn: psycopg.Connection, ds: Dataset, pii_key: bytes) -> bool:
    """Load the dataset in one transaction if data_version changed. Returns True if it loaded."""
    if current_version(conn) == ds.data_version:
        print(f"loader: data_version {ds.data_version} is already loaded; skip")
        return False
    t0 = time.monotonic()
    df = ds.df
    # Dimensions
    dates = pd.DataFrame({"order_date": pd.to_datetime(sorted(df["order_date"].unique()))})
    dates["date_key"] = dates["order_date"].dt.strftime("%Y%m%d").astype(int)
    dates["year"] = dates["order_date"].dt.year
    dates["quarter"] = dates["order_date"].dt.quarter
    dates["month"] = dates["order_date"].dt.month
    dates["year_month"] = dates["order_date"].dt.strftime("%Y-%m")
    dates["season"] = dates["month"].map(vocab.MONTH_SEASON)
    dates["day_of_week"] = dates["order_date"].dt.dayofweek.map(lambda i: vocab.DAYS_OF_WEEK[i])
    dates["order_date"] = dates["order_date"].dt.strftime("%Y-%m-%d")

    geo = pd.DataFrame({"country": list(vocab.COUNTRIES)})
    geo["geo_id"] = np.arange(1, len(geo) + 1)
    geo["region"] = geo["country"].map(vocab.COUNTRY_REGION)

    prod = pd.DataFrame({"product_name": list(vocab.PRODUCTS)})
    prod["product_id"] = np.arange(1, len(prod) + 1)
    prod["sub_category"] = prod["product_name"].map(vocab.PRODUCT_SUB_CATEGORY)
    prod["category"] = prod["product_name"].map(vocab.PRODUCT_CATEGORY)

    cust_ids = sorted(df["customer_id"].astype(str).unique())
    keys = customer_keys(cust_ids, pii_key)
    cust = pd.DataFrame({"customer_id": cust_ids})
    cust["customer_sk"] = np.arange(1, len(cust) + 1)
    cust["customer_key"] = cust["customer_id"].map(keys)

    fact = pd.DataFrame({
        "order_id": df["order_id"].astype(str),
        "date_key": df["order_date"].dt.strftime("%Y%m%d").astype(int),
        "geo_id": df["country"].map(dict(zip(geo["country"], geo["geo_id"]))),
        "product_id": df["product_name"].map(dict(zip(prod["product_name"], prod["product_id"]))),
        "customer_sk": df["customer_id"].map(dict(zip(cust["customer_id"], cust["customer_sk"]))),
        "customer_segment": df["customer_segment"],
        "customer_gender": df["customer_gender"],
        "unit_price": df["unit_price"].map("{:.2f}".format),
        "quantity": df["quantity"],
        "discount": df["discount"].map("{:.2f}".format),
        "revenue": df["revenue"].map("{:.2f}".format),
        "cost": df["cost"].map("{:.2f}".format),
        "profit": df["profit"].map("{:.2f}".format),
        "profit_margin_pct": df["profit_margin_pct"].map("{:.2f}".format),
        "shipping_cost": df["shipping_cost"].map("{:.2f}".format),
        "shipping_method": df["shipping_method"],
        "shipping_days": df["shipping_days"],
        "payment_method": df["payment_method"],
        "order_status": df["order_status"],
    })
    # Rows load in date order (BRIN index on date_key)
    fact = fact.sort_values(["date_key", "order_id"], kind="stable")

    with conn.transaction():
        cur = conn.cursor()
        cur.execute("TRUNCATE sales.fact_orders, sales.dim_customer, sales.dim_date, sales.dim_geography, sales.dim_product")
        _copy_df(cur, "sales.dim_date", ["date_key", "order_date", "year", "quarter", "month", "year_month", "season", "day_of_week"], dates)
        _copy_df(cur, "sales.dim_geography", ["geo_id", "country", "region"], geo)
        _copy_df(cur, "sales.dim_product", ["product_id", "product_name", "sub_category", "category"], prod)
        _copy_df(cur, "sales.dim_customer", ["customer_sk", "customer_id", "customer_key"], cust)
        _copy_df(cur, "sales.fact_orders", list(fact.columns), fact)
        cur.execute(
            """
            INSERT INTO sales.meta (id, data_version, dataset, row_count, min_date, max_date, loaded_at)
            VALUES (1, %s, %s, %s, %s, %s, now())
            ON CONFLICT (id) DO UPDATE SET data_version = EXCLUDED.data_version, dataset = EXCLUDED.dataset,
              row_count = EXCLUDED.row_count, min_date = EXCLUDED.min_date, max_date = EXCLUDED.max_date,
              loaded_at = EXCLUDED.loaded_at
            """,
            (ds.data_version, ds.name, ds.rows, df["order_date"].min().date(), df["order_date"].max().date()),
        )
    conn.execute("ANALYZE sales.fact_orders")
    conn.execute("ANALYZE sales.dim_customer")
    conn.execute("ANALYZE sales.dim_date")
    print(f"loader: loaded {ds.rows} rows into the star schema in {time.monotonic() - t0:.1f} s")
    return True
