"""Column registry: CSV columns, the wide (flat) order row, types, and sensitivity.

This registry is the single source for:
- the SQL function sales.scope_rows (explicit column list and masks),
- the DuckDB scope files (column types),
- the visible columns for each role (tables, order drawer, exports).
A test makes sure that every column of sales.orders_flat has a classification here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Sensitivity = Literal["public", "financial", "pii", "internal"]

# CSV header -> snake_case name
CSV_COLUMNS: dict[str, str] = {
    "Order_ID": "order_id",
    "Order_Date": "order_date",
    "Year": "year",
    "Month": "month",
    "Quarter": "quarter",
    "Season": "season",
    "Customer_ID": "customer_id",
    "Customer_Gender": "customer_gender",
    "Customer_Segment": "customer_segment",
    "Region": "region",
    "Country": "country",
    "Category": "category",
    "Sub_Category": "sub_category",
    "Product_Name": "product_name",
    "Unit_Price": "unit_price",
    "Quantity": "quantity",
    "Discount": "discount",
    "Revenue": "revenue",
    "Cost": "cost",
    "Profit": "profit",
    "Profit_Margin_%": "profit_margin_pct",
    "Shipping_Cost": "shipping_cost",
    "Shipping_Method": "shipping_method",
    "Shipping_Days": "shipping_days",
    "Payment_Method": "payment_method",
    "Order_Status": "order_status",
}
CSV_HEADER: tuple[str, ...] = tuple(CSV_COLUMNS)


@dataclass(frozen=True)
class Column:
    name: str
    label: str
    pg_type: str        # type in sales.scope_rows output
    duck_type: str      # type in the DuckDB scope file
    sensitivity: Sensitivity
    kind: Literal["id", "date", "text", "int", "money", "number", "pct", "bool"]
    description: str
    in_table: bool = True  # shown in the Orders table by default


# The wide order row, in the order of sales.orders_flat / sales.scope_rows.
FLAT_COLUMNS: tuple[Column, ...] = (
    Column("order_id", "Order ID", "varchar(12)", "VARCHAR", "public", "id", "Unique order number (ORD-…)."),
    Column("order_date", "Order date", "date", "DATE", "public", "date", "Date of the order."),
    Column("year", "Year", "smallint", "SMALLINT", "public", "int", "Calendar year of the order.", False),
    Column("quarter", "Quarter", "smallint", "SMALLINT", "public", "int", "Calendar quarter (1-4).", False),
    Column("month", "Month", "smallint", "SMALLINT", "public", "int", "Calendar month (1-12).", False),
    Column("year_month", "Year-month", "text", "VARCHAR", "public", "text", "Month of the order (YYYY-MM).", False),
    Column("year_quarter", "Year-quarter", "text", "VARCHAR", "public", "text", "Quarter of the order (YYYY-Qn).", False),
    Column("season", "Season", "text", "VARCHAR", "public", "text", "Meteorological season of the order month.", False),
    Column("day_of_week", "Day of week", "text", "VARCHAR", "public", "text", "Weekday of the order (Mon-Sun).", False),
    Column("customer_id", "Customer ID", "text", "VARCHAR", "pii", "id",
           "Customer identifier. Analysts see a pseudonym (C-…) instead of the real ID."),
    Column("customer_gender", "Gender", "text", "VARCHAR", "public", "text", "Customer gender at the time of the order."),
    Column("customer_segment", "Segment", "text", "VARCHAR", "public", "text", "Customer segment at the time of the order."),
    Column("region", "Region", "text", "VARCHAR", "public", "text", "Sales region (4 regions)."),
    Column("country", "Country", "text", "VARCHAR", "public", "text", "Country of the order (18 countries)."),
    Column("category", "Category", "text", "VARCHAR", "public", "text", "Product category (5 categories)."),
    Column("sub_category", "Sub-category", "text", "VARCHAR", "public", "text", "Product sub-category (14)."),
    Column("product_name", "Product", "text", "VARCHAR", "public", "text", "Product name (70 products)."),
    Column("unit_price", "Unit price", "numeric(10,2)", "DECIMAL(10,2)", "public", "money", "Price of one unit before the discount."),
    Column("quantity", "Quantity", "smallint", "SMALLINT", "public", "int", "Number of units."),
    Column("discount", "Discount", "numeric(3,2)", "DECIMAL(3,2)", "public", "pct", "Discount rate (0 to 0.5)."),
    Column("revenue", "Revenue", "numeric(12,2)", "DECIMAL(12,2)", "public", "money",
           "Unit price × quantity × (1 − discount), rounded to cents. Includes cancelled and returned orders."),
    Column("cost", "Cost", "numeric(12,2)", "DECIMAL(12,2)", "financial", "money", "Cost of the goods of the order."),
    Column("profit", "Profit", "numeric(12,2)", "DECIMAL(12,2)", "financial", "money", "Revenue − cost. Shipping cost is not included."),
    Column("profit_margin_pct", "Margin % (row)", "numeric(6,2)", "DECIMAL(6,2)", "financial", "pct",
           "Profit / revenue × 100 for one order. Do not average it; use the weighted margin."),
    Column("shipping_cost", "Shipping cost", "numeric(8,2)", "DECIMAL(8,2)", "public", "money", "Shipping cost of the order."),
    Column("shipping_method", "Shipping method", "text", "VARCHAR", "public", "text", "Economy, Standard, Express, or Overnight."),
    Column("shipping_days", "Shipping days", "smallint", "SMALLINT", "public", "int", "Days from order to delivery."),
    Column("payment_method", "Payment method", "text", "VARCHAR", "public", "text", "Payment method (7)."),
    Column("order_status", "Status", "text", "VARCHAR", "public", "text", "Delivered, Processing, Returned, or Cancelled (snapshot)."),
    Column("list_value", "List value", "numeric(12,2)", "DECIMAL(12,2)", "public", "money", "Unit price × quantity (before the discount).", False),
    Column("discount_amount", "Discount amount", "numeric(12,2)", "DECIMAL(12,2)", "public", "money", "List value − revenue.", False),
    Column("discount_band", "Discount level", "text", "VARCHAR", "public", "text", "Discount as a level (0%, 5%, … 50%).", False),
    Column("price_band", "Price band", "text", "VARCHAR", "public", "text", "Unit price band.", False),
    Column("shipping_days_band", "Shipping days band", "text", "VARCHAR", "public", "text", "Shipping days band.", False),
    Column("is_net", "Net order", "boolean", "BOOLEAN", "public", "bool", "Not Cancelled and not Returned.", False),
    Column("is_fulfilled", "Fulfilled", "boolean", "BOOLEAN", "public", "bool", "Delivered or Returned.", False),
    Column("is_loss", "Loss order", "boolean", "BOOLEAN", "financial", "bool", "Profit is below zero.", False),
    Column("profit_after_shipping", "Profit after shipping (estimate)", "numeric(12,2)", "DECIMAL(12,2)", "financial", "money",
           "Profit − shipping cost. An estimate: the dataset does not say who pays the shipping.", False),
)

COLUMNS: dict[str, Column] = {c.name: c for c in FLAT_COLUMNS}

# Columns of sales.orders_flat that never leave the database as their own column.
INTERNAL_FLAT_COLUMNS: dict[str, Sensitivity] = {"customer_key": "internal"}

FINANCIAL_COLUMNS: tuple[str, ...] = tuple(c.name for c in FLAT_COLUMNS if c.sensitivity == "financial")
PII_COLUMNS: tuple[str, ...] = tuple(c.name for c in FLAT_COLUMNS if c.sensitivity == "pii")


def classification(name: str) -> Sensitivity | None:
    if name in COLUMNS:
        return COLUMNS[name].sensitivity
    return INTERNAL_FLAT_COLUMNS.get(name)


def visible_columns(financial: bool) -> list[Column]:
    """Columns that a role can see. PII is visible to all roles; the analyst gets a pseudonym in the same column."""
    return [c for c in FLAT_COLUMNS if financial or c.sensitivity != "financial"]


def scope_rows_select_list(alias: str = "o", financial_param: str = "p_financial", pii_param: str = "p_pii_raw") -> str:
    """SQL select list for sales.scope_rows: the only copy of the column masks."""
    parts: list[str] = []
    for c in FLAT_COLUMNS:
        if c.sensitivity == "financial":
            parts.append(f"CASE WHEN {financial_param} THEN {alias}.{c.name} END::{c.pg_type} AS {c.name}")
        elif c.sensitivity == "pii":
            parts.append(f"(CASE WHEN {pii_param} THEN {alias}.customer_id ELSE {alias}.customer_key END)::{c.pg_type} AS {c.name}")
        else:
            parts.append(f"{alias}.{c.name}::{c.pg_type} AS {c.name}")
    return ",\n    ".join(parts)


def scope_rows_return_list() -> str:
    return ", ".join(f"{c.name} {c.pg_type}" for c in FLAT_COLUMNS)
