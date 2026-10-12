from __future__ import annotations

import pandas as pd

from app.data import generator, loader, vocab
from app.data.validation import validate


def _tvd(a: pd.Series, b: pd.Series) -> float:
    pa = a.value_counts(normalize=True)
    pb = b.value_counts(normalize=True)
    idx = pa.index.union(pb.index)
    return float(0.5 * (pa.reindex(idx, fill_value=0) - pb.reindex(idx, fill_value=0)).abs().sum())


def test_deterministic(sample_csv):
    a = generator.generate(sample_csv, 5_000, seed=7)
    b = generator.generate(sample_csv, 5_000, seed=7)
    pd.testing.assert_frame_equal(a, b)
    c = generator.generate(sample_csv, 5_000, seed=8)
    assert not a.equals(c)


def test_output_passes_hard_checks_and_keeps_vocabulary(sample_csv, tmp_path):
    g = generator.generate(sample_csv, 100_000)
    assert validate(g) == []
    p = tmp_path / "g.csv"
    generator.write_csv(g, p)
    back = loader.read_csv(p)  # the same CSV format as the original
    assert validate(back) == []
    assert back["order_id"].is_unique
    assert set(back["region"]) == set(vocab.REGIONS)
    assert set(back["country"]) == set(vocab.COUNTRIES)
    assert set(back["product_name"]) == set(vocab.PRODUCTS)
    assert set(back["order_status"]) == set(vocab.STATUSES)


def test_distributions_close_to_original(sample_csv):
    src = loader.read_csv(sample_csv)
    g = generator.generate(sample_csv, 100_000)
    assert _tvd(src["order_date"].dt.to_period("M"), g["order_date"].dt.to_period("M")) < 0.02
    assert _tvd(src["product_name"], g["product_name"]) < 0.02
    assert _tvd(src["region"], g["region"]) < 0.02
    assert _tvd(src["order_status"], g["order_status"]) < 0.02
    assert g["order_date"].min() >= src["order_date"].min()
    assert g["order_date"].max() <= src["order_date"].max()
    # repeat customers about like the original (54.77 %)
    vc = g["customer_id"].value_counts()
    assert 0.45 < (vc >= 2).mean() < 0.65
    # weighted margin stays close to the original (27.21 %)
    assert abs(g["profit"].sum() / g["revenue"].sum() * 100 - 27.21) < 1.5
