from __future__ import annotations

import pandas as pd
import pytest

from app.data import loader
from app.data.validation import DatasetError


def test_sample_reads_and_passes_checks(sample_csv):
    ds = loader.read_dataset(sample_csv, "sample")
    assert ds.rows == 10_000
    assert list(ds.df.columns)[:3] == ["order_id", "order_date", "year"]  # BOM removed from the header
    assert ds.df["order_date"].max() == pd.Timestamp("2024-12-24")
    assert ds.df["order_date"].min() == pd.Timestamp("2021-01-05")
    assert len(ds.data_version) == 12


def test_data_quality_counts(sample_csv):
    df = loader.read_csv(sample_csv)
    g = df.groupby("customer_id")
    assert int((g["customer_segment"].nunique() > 1).sum()) == 2209
    assert int((g["customer_gender"].nunique() > 1).sum()) == 1856
    assert int((g["country"].nunique() > 1).sum()) == 2838
    assert int(((df["order_status"] == "Processing") & (df["year"] == 2021)).sum()) == 93


def _write_broken(tmp_path, sample_csv, mutate):
    text = sample_csv.read_text(encoding="utf-8-sig").splitlines()
    text = mutate(text)
    p = tmp_path / "broken.csv"
    p.write_text("\n".join(text) + "\n", encoding="utf-8")
    return p


def test_missing_column_fails(tmp_path, sample_csv):
    def mutate(lines):
        return [",".join(line.split(",")[:-1]) for line in lines]
    with pytest.raises(DatasetError):
        loader.read_dataset(_write_broken(tmp_path, sample_csv, mutate), "x")


def test_wrong_revenue_fails(tmp_path, sample_csv):
    def mutate(lines):
        parts = lines[1].split(",")
        parts[17] = str(float(parts[17]) + 5)  # Revenue
        lines[1] = ",".join(parts)
        return lines
    with pytest.raises(DatasetError, match="revenue"):
        loader.read_dataset(_write_broken(tmp_path, sample_csv, mutate), "x")


def test_unknown_region_fails(tmp_path, sample_csv):
    def mutate(lines):
        parts = lines[2].split(",")
        parts[9] = "Atlantis"
        lines[2] = ",".join(parts)
        return lines
    with pytest.raises(DatasetError, match="region"):
        loader.read_dataset(_write_broken(tmp_path, sample_csv, mutate), "x")


def test_duplicate_order_id_fails(tmp_path, sample_csv):
    def mutate(lines):
        return lines + [lines[1]]
    with pytest.raises(DatasetError, match="duplicate"):
        loader.read_dataset(_write_broken(tmp_path, sample_csv, mutate), "x")


def test_bad_hierarchy_fails(tmp_path, sample_csv):
    def mutate(lines):
        parts = lines[3].split(",")
        parts[10] = "Japan" if parts[9] != "Asia" else "France"  # country outside its region
        lines[3] = ",".join(parts)
        return lines
    with pytest.raises(DatasetError, match="region"):
        loader.read_dataset(_write_broken(tmp_path, sample_csv, mutate), "x")


def test_star_schema_counts(test_db, owner_db):
    c = owner_db
    assert c.execute("SELECT count(*) FROM sales.fact_orders").fetchone()[0] == 10_000
    assert c.execute("SELECT count(*) FROM sales.dim_geography").fetchone()[0] == 18
    assert c.execute("SELECT count(*) FROM sales.dim_product").fetchone()[0] == 70
    assert c.execute("SELECT count(*) FROM sales.dim_customer").fetchone()[0] == 5348
    assert c.execute("SELECT max(order_date) FROM sales.dim_date").fetchone()[0].isoformat() == "2024-12-24"
    # pseudonyms are unique and have the C-XXXXXXXX form
    bad = c.execute("SELECT count(*) FROM sales.dim_customer WHERE customer_key !~ '^C-[A-Z2-7]{8}$'").fetchone()[0]
    assert bad == 0


def test_pseudonym_collisions_are_resolved():
    keys = loader.customer_keys([f"CUST-{i:06d}" for i in range(5000)], b"k")
    assert len(set(keys.values())) == 5000
