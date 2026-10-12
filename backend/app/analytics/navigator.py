"""Aggregate navigator: select the smallest rollup that can answer a QuerySpec, or the raw table.

A rollup can answer a spec when all metrics are additive, the time filter aligns to months,
and the rollup contains every group-by and filter dimension. Otherwise the raw `orders` table answers.
A test proves that both choices give the same result for every spec in the test grid.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date

from app.analytics.dimensions import DIMENSIONS, ROLLUPS
from app.analytics.metrics import METRICS
from app.analytics.spec import QuerySpec

RAW = "orders"


@dataclass(frozen=True)
class MonthBounds:
    """Month-aligned bounds of a date range (None means no bound)."""
    ym_from: str | None
    ym_to: str | None


def _last_day(d: date) -> int:
    return calendar.monthrange(d.year, d.month)[1]


def month_bounds(date_from: date | None, date_to: date | None, data_min: date, data_max: date) -> MonthBounds | None:
    """Return month bounds if the date range is equal to a month range on this data; else None."""
    ym_from = ym_to = None
    if date_from is not None:
        if date_from <= data_min:
            ym_from = None
        elif date_from.day == 1:
            ym_from = f"{date_from.year:04d}-{date_from.month:02d}"
        else:
            return None
    if date_to is not None:
        if date_to >= data_max:
            ym_to = None
        elif date_to.day == _last_day(date_to):
            ym_to = f"{date_to.year:04d}-{date_to.month:02d}"
        else:
            return None
    return MonthBounds(ym_from, ym_to)


def needed_dims(spec: QuerySpec) -> set[str]:
    return set(spec.dims()) | spec.filters.dims()


def choose(spec: QuerySpec, rollup_rows: dict[str, int], data_min: date, data_max: date, force_raw: bool = False,
           raw_rows: int | None = None) -> str:
    """Return the table name. With raw_rows, the raw table wins when it is not larger than the best rollup
    (small scopes); the result is the same either way (navigator equality test)."""
    best = _best_rollup(spec, rollup_rows, data_min, data_max) if not force_raw else RAW
    if best != RAW and raw_rows is not None and raw_rows <= rollup_rows[best]:
        return RAW
    return best


def _best_rollup(spec: QuerySpec, rollup_rows: dict[str, int], data_min: date, data_max: date) -> str:
    if any(not METRICS[m].additive for m in spec.metrics):
        return RAW
    f = spec.filters
    if (f.date_from or f.date_to) and month_bounds(f.date_from, f.date_to, data_min, data_max) is None:
        return RAW
    dims = needed_dims(spec)
    if any(not DIMENSIONS[d].in_rollups for d in dims):
        return RAW
    candidates = [r for r in ROLLUPS if r in rollup_rows and all(r in DIMENSIONS[d].rollup_names() for d in dims)]
    if not candidates:
        return RAW
    return min(candidates, key=lambda r: (rollup_rows[r], r))
