"""Compile a QuerySpec to DuckDB SQL for one table (raw `orders` or a rollup).

Identifiers come only from the registries. Every value is a bound parameter ($name).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.analytics.dimensions import DIMENSIONS, FILTERS
from app.analytics.metrics import METRICS, Agg
from app.analytics.navigator import RAW, month_bounds
from app.analytics.spec import QuerySpec


@dataclass
class Compiled:
    sql: str
    params: dict = field(default_factory=dict)
    dims: list[str] = field(default_factory=list)
    table: str = RAW


def _dim_sql(dim_id: str, raw: bool) -> str:
    d = DIMENSIONS[dim_id]
    return d.raw_expr if raw else dim_id


def _where(spec: QuerySpec, raw: bool, data_min: date, data_max: date, params: dict) -> list[str]:
    conds: list[str] = []
    f = spec.filters
    for name, (dim_id, _allowed) in FILTERS.items():
        values = getattr(f, name)
        if values is None:
            continue
        col = _dim_sql(dim_id, raw)
        names = []
        for i, v in enumerate(values):
            p = f"f_{name}_{i}"
            params[p] = v
            names.append(f"${p}")
        conds.append(f"{col} IN ({', '.join(names)})")
    if f.date_from or f.date_to:
        if raw:
            if f.date_from:
                params["date_from"] = f.date_from
                conds.append("order_date >= $date_from")
            if f.date_to:
                params["date_to"] = f.date_to
                conds.append("order_date <= $date_to")
        else:
            mb = month_bounds(f.date_from, f.date_to, data_min, data_max)
            if mb is None:  # the navigator never sends a misaligned range to a rollup
                raise ValueError("date range is not month aligned")
            if mb.ym_from:
                params["ym_from"] = mb.ym_from
                conds.append("year_month >= $ym_from")
            if mb.ym_to:
                params["ym_to"] = mb.ym_to
                conds.append("year_month <= $ym_to")
    return conds


def raw_where(filters, data_min: date, data_max: date) -> tuple[str, dict]:
    """WHERE clause for the raw orders table (order search, exports, distributions)."""
    params: dict = {}
    spec = QuerySpec(metrics=["orders"], filters=filters)
    conds = _where(spec, True, data_min, data_max, params)
    return (f"WHERE {' AND '.join(conds)}" if conds else ""), params


def _metric_selects(spec: QuerySpec, raw: bool) -> list[str]:
    agg = Agg(rollup=not raw)
    out: list[str] = []
    for mid in spec.metrics:
        m = METRICS[mid]
        if mid == "unique_customers":
            out.append("CAST(COUNT(DISTINCT customer_id) AS DOUBLE) AS unique_customers")
        elif mid == "repeat_customer_rate":
            continue  # separate CTE
        else:
            out.append(f"{m.expr(agg)} AS {mid}")
            if m.n_expr is not None:
                out.append(f"{m.n_expr(agg)} AS {mid}__n")
    return out


def _order_by(spec: QuerySpec, dims: list[str]) -> str:
    parts: list[str] = []
    if spec.sort_by:
        direction = (spec.sort_dir or ("asc" if spec.sort_by in dims else "desc")).upper()
        parts.append(f"{spec.sort_by} {direction} NULLS LAST")
    elif spec.time_grain:
        parts.append(f"{spec.time_grain} ASC")
    elif spec.metrics and dims:
        parts.append(f"{spec.metrics[0]} DESC NULLS LAST")
    for d in dims:
        if not parts or not parts[0].startswith(f"{d} "):
            parts.append(f"{d} ASC")
    return ", ".join(parts)


def compile_spec(spec: QuerySpec, table: str, data_min: date, data_max: date, with_dims: bool = True) -> Compiled:
    raw = table == RAW
    params: dict = {}
    dims = spec.dims() if with_dims else []
    where = _where(spec, raw, data_min, data_max, params)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    dim_selects = [f"{_dim_sql(d, raw)} AS {d}" for d in dims]
    metric_selects = _metric_selects(spec, raw)
    wants_repeat = "repeat_customer_rate" in spec.metrics
    group_sql = f"GROUP BY {', '.join(str(i + 1) for i in range(len(dims)))}" if dims else ""
    limit = spec.limit if dims else 1

    if not wants_repeat:
        select = ", ".join(dim_selects + metric_selects) or "COUNT(*) AS orders"
        order = _order_by(spec, dims) if dims else ""
        sql = f"SELECT {select} FROM {table} {where_sql} {group_sql}"
        if order:
            sql += f" ORDER BY {order}"
        sql += f" LIMIT {int(limit)}"
        return Compiled(sql=sql, params=params, dims=dims, table=table)

    # Repeat customer rate needs one row for each customer first (raw table only).
    if not raw:
        raise ValueError("repeat_customer_rate needs the raw table")
    dim_list = ", ".join(dims)
    base_select = ", ".join([f"{_dim_sql(d, True)} AS {d}" for d in dims] + ["customer_id", "COUNT(*) AS c"])
    base_group = ", ".join(str(i + 1) for i in range(len(dims) + 1))
    rep_select = ", ".join(
        (dims and [dim_list] or [])
        + ["CAST(COUNT(*) FILTER (WHERE c >= 2) AS DOUBLE) / NULLIF(COUNT(*), 0) * 100.0 AS repeat_customer_rate",
           "CAST(COUNT(*) AS DOUBLE) AS repeat_customer_rate__n"]
    )
    rep_group = f"GROUP BY {dim_list}" if dims else ""
    ctes = [
        f"base AS (SELECT {base_select} FROM {table} {where_sql} GROUP BY {base_group})",
        f"rep AS (SELECT {rep_select} FROM base {rep_group})",
    ]
    if metric_selects:
        main_select = ", ".join(dim_selects + metric_selects)
        ctes.append(f"m AS (SELECT {main_select} FROM {table} {where_sql} {group_sql})")
        if dims:
            body = f"SELECT m.*, rep.repeat_customer_rate, rep.repeat_customer_rate__n FROM m LEFT JOIN rep USING ({dim_list})"
        else:
            body = "SELECT m.*, rep.repeat_customer_rate, rep.repeat_customer_rate__n FROM m CROSS JOIN rep"
    else:
        body = "SELECT * FROM rep"
    sql = f"WITH {', '.join(ctes)} SELECT * FROM ({body}) q"
    if dims:
        sql += f" ORDER BY {_order_by(spec, dims)}"
    sql += f" LIMIT {int(limit)}"
    return Compiled(sql=sql, params=params, dims=dims, table=table)
