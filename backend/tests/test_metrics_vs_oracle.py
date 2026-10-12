"""Each metric x a grid of dimensions and filters x each role scope agrees with the pandas oracle."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.analytics import engine
from app.analytics.spec import QuerySpec
from app.data.scoped import ScopeFileCache
from app.data.scopestore import scope_keys
from eval import reference
from tests.grid import GRID, SMALL_GRID, metric_chunks

TOL = 0.005


def _key(row: dict, dims: list[str]) -> tuple:
    out = []
    for d in dims:
        v = row[d]
        out.append(v)
    return tuple(out)


def _compare(sf, scope_key: str, df, grid: list[dict]) -> int:
    checked = 0
    financial = scope_key != "all:nofin"
    for g in grid:
        for metrics in metric_chunks(financial):
            spec = QuerySpec(metrics=metrics, limit=500, **g)
            res = engine.run_query(sf, scope_key, spec)
            dims = spec.dims()
            exp = reference.query(df, metrics, dims, g.get("filters"))
            got = {_key(r, dims): r for r in res["rows"]} if dims else {(): res["totals"] or {}}
            assert set(got) == set(exp), f"{scope_key} {g}: groups differ"
            for k, ev in exp.items():
                for m in metrics:
                    e, v = ev[m], got[k].get(m)
                    if e is None:
                        assert v is None, f"{scope_key} {g} {k} {m}: expected None, got {v}"
                    else:
                        assert v == pytest.approx(e, abs=TOL, rel=1e-9), f"{scope_key} {g} {k} {m}: {v} != {e}"
                    checked += 1
    return checked


@pytest.mark.parametrize("scope_key", scope_keys())
def test_sample_grid(scope_key, scope_cache, data_version, sample_csv):
    df = reference.scope(reference.load(str(sample_csv)), scope_key)
    sf = scope_cache.get(data_version, scope_key)
    assert _compare(sf, scope_key, df, GRID) > 100


@pytest.mark.parametrize("scope_key", ["all:full", "region:Asia", "category:Electronics", "all:nofin"])
def test_100k_grid(scope_key, dataset_100k):
    cache = ScopeFileCache(Path(dataset_100k["scopes_dir"]))
    sf = cache.get(dataset_100k["data_version"], scope_key)
    df = reference.scope(reference.load(dataset_100k["csv"]), scope_key)
    assert _compare(sf, scope_key, df, SMALL_GRID) > 50
