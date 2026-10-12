"""The navigator's rollup choice gives the same result as a raw query for every spec in the grid."""

from __future__ import annotations

from datetime import date

import pytest

from app.analytics import engine, navigator
from app.analytics.dimensions import ROLLUPS, TIME_ROLLUP_COLS
from app.analytics.metrics import METRICS_LIST, NON_ADDITIVE
from app.analytics.spec import Filters, QuerySpec
from tests.grid import GRID

ADDITIVE = [m.id for m in METRICS_LIST if m.additive]
CHUNKS = [ADDITIVE[i:i + 6] for i in range(0, len(ADDITIVE), 6)]


def _rows(raw) -> list[tuple]:
    return sorted(tuple(r) for r in raw.rows)


@pytest.mark.parametrize("scope_key", ["all:full", "all:nofin", "region:Europe", "category:Clothing"])
def test_rollup_equals_raw_for_every_spec(scope_key, scope_cache, data_version):
    sf = scope_cache.get(data_version, scope_key)
    used = set()
    for g in GRID:
        for metrics in CHUNKS:
            if scope_key == "all:nofin":
                metrics = [m for m in metrics if not m.startswith(("cost", "gross_profit", "net_profit", "margin", "net_margin", "loss", "profit"))]
                if not metrics:
                    continue
            spec = QuerySpec(metrics=metrics, limit=500, **g)
            # the best rollup, without the "raw table is smaller" rule
            table = navigator.choose(spec, sf.rollup_rows, sf.data_min, sf.data_max)
            raw = engine.execute(sf, spec, table_override=navigator.RAW)
            if table == navigator.RAW:
                continue
            used.add(table)
            rolled = engine.execute(sf, spec, table_override=table)
            assert rolled.columns == raw.columns
            assert _rows(rolled) == _rows(raw), f"{scope_key} {table} {g} {metrics}"
            # every other rollup that covers the spec gives the same result too
            for other in ROLLUPS:
                if other != table and navigator.needed_dims(spec) <= set(ROLLUPS[other]) | set(TIME_ROLLUP_COLS):
                    used.add(other)
                    r2 = engine.execute(sf, spec, table_override=other)
                    assert _rows(r2) == _rows(raw), f"{scope_key} {other} {g}"
    assert used == set(ROLLUPS), f"not all rollups were used: {used}"


def test_non_additive_metrics_use_raw(scope_cache, data_version):
    sf = scope_cache.get(data_version, "all:full")
    for m in NON_ADDITIVE:
        spec = QuerySpec(metrics=[m], group_by=["region"])
        assert navigator.choose(spec, sf.rollup_rows, sf.data_min, sf.data_max) == navigator.RAW


def test_day_level_ranges_use_raw_and_month_ranges_use_rollups(scope_cache, data_version):
    sf = scope_cache.get(data_version, "all:full")
    day = QuerySpec(metrics=["gross_revenue"], filters=Filters(date_from=date(2023, 3, 5), date_to=date(2023, 6, 30)))
    assert navigator.choose(day, sf.rollup_rows, sf.data_min, sf.data_max) == navigator.RAW
    month = QuerySpec(metrics=["gross_revenue"], filters=Filters(date_from=date(2023, 3, 1), date_to=date(2023, 6, 30)))
    assert navigator.choose(month, sf.rollup_rows, sf.data_min, sf.data_max) != navigator.RAW
    # to the last data date (2024-12-24) is month aligned on this data
    tail = QuerySpec(metrics=["gross_revenue"], filters=Filters(date_from=date(2024, 1, 1), date_to=date(2024, 12, 24)))
    assert navigator.choose(tail, sf.rollup_rows, sf.data_min, sf.data_max) != navigator.RAW
    grain = QuerySpec(metrics=["gross_revenue"], time_grain="order_date")
    assert navigator.choose(grain, sf.rollup_rows, sf.data_min, sf.data_max) == navigator.RAW


def test_smallest_covering_rollup(scope_cache, data_version):
    sf = scope_cache.get(data_version, "all:full")
    spec = QuerySpec(metrics=["gross_revenue"], group_by=["sub_category"])
    assert navigator.choose(spec, sf.rollup_rows, sf.data_min, sf.data_max) == "r_product"
    spec = QuerySpec(metrics=["orders"], group_by=["payment_method"])
    assert navigator.choose(spec, sf.rollup_rows, sf.data_min, sf.data_max) == "r_customer"
    spec = QuerySpec(metrics=["orders"], group_by=["shipping_days_band"])
    assert navigator.choose(spec, sf.rollup_rows, sf.data_min, sf.data_max) == "r_ops"
    spec = QuerySpec(metrics=["orders"], group_by=["region"], filters=Filters(categories=["Clothing"]))
    assert navigator.choose(spec, sf.rollup_rows, sf.data_min, sf.data_max) == "r_geo"
    # the raw table wins when it is smaller than the best rollup
    assert navigator.choose(spec, sf.rollup_rows, sf.data_min, sf.data_max, raw_rows=10) == navigator.RAW
