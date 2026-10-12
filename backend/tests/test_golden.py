"""All reference values of the plan (sample dataset), through the engine and the scope files."""

from __future__ import annotations

import pytest

from app.analytics import engine
from app.analytics.spec import Filters, QuerySpec
from eval.reference import REFERENCE


@pytest.fixture(scope="module")
def full(scope_cache, data_version):
    return scope_cache.get(data_version, "all:full")


def q(sf, key="all:full", **kw):
    return engine.run_query(sf, key, QuerySpec(**kw))


def test_revenue_and_profit(full):
    t = q(full, metrics=["gross_revenue", "net_revenue", "delivered_revenue", "gross_profit", "margin_pct"])["totals"]
    assert t["gross_revenue"] == pytest.approx(REFERENCE["gross_revenue"], abs=0.005)
    assert t["net_revenue"] == pytest.approx(REFERENCE["net_revenue"], abs=0.005)
    assert t["delivered_revenue"] == pytest.approx(REFERENCE["delivered_revenue"], abs=0.005)
    assert t["gross_profit"] == pytest.approx(REFERENCE["gross_profit"], abs=0.005)
    assert round(t["margin_pct"], 2) == REFERENCE["margin_pct"]


def test_rates_and_aov(full):
    t = q(full, metrics=["return_rate", "cancellation_rate", "aov"])["totals"]
    assert round(t["return_rate"], 2) == REFERENCE["return_rate"]
    assert round(t["cancellation_rate"], 2) == REFERENCE["cancellation_rate"]
    assert round(t["aov"], 2) == REFERENCE["aov"]


def test_electronics_q3_2023(full):
    t = q(full, metrics=["gross_revenue", "orders"], filters=Filters(categories=["Electronics"], years=[2023], quarters=[3]))["totals"]
    assert t["gross_revenue"] == pytest.approx(REFERENCE["electronics_q3_2023"][0], abs=0.005)
    assert t["orders"] == REFERENCE["electronics_q3_2023"][1]


def test_asia_electronics_q3_2023(full, scope_cache, data_version):
    t = q(full, metrics=["gross_revenue", "orders"],
          filters=Filters(regions=["Asia"], categories=["Electronics"], years=[2023], quarters=[3]))["totals"]
    assert t["gross_revenue"] == pytest.approx(REFERENCE["asia_electronics_q3_2023"][0], abs=0.005)
    assert t["orders"] == REFERENCE["asia_electronics_q3_2023"][1]
    # The same number in the Asia regional manager's own scope file
    asia = scope_cache.get(data_version, "region:Asia")
    t2 = q(asia, "region:Asia", metrics=["gross_revenue"], filters=Filters(categories=["Electronics"], years=[2023], quarters=[3]))["totals"]
    assert t2["gross_revenue"] == pytest.approx(REFERENCE["asia_electronics_q3_2023"][0], abs=0.005)


def test_top_region(full):
    rows = q(full, metrics=["gross_revenue"], group_by=["region"], limit=1)["rows"]
    assert rows[0]["region"] == REFERENCE["top_region"][0]
    assert rows[0]["gross_revenue"] == pytest.approx(REFERENCE["top_region"][1], abs=0.005)


def test_h1_2024_vs_h1_2023(full):
    t = q(full, metrics=["gross_revenue"], filters=Filters(date_from="2024-01-01", date_to="2024-06-30"),
          compare="prior_year_lfl")["totals"]
    assert t["gross_revenue"] == pytest.approx(REFERENCE["h1_2024"], abs=0.005)
    assert t["gross_revenue__prior"] == pytest.approx(REFERENCE["h1_2023"], abs=0.005)
    assert round(t["gross_revenue__pct"], 2) == REFERENCE["h1_change_pct"]


def test_customers(full):
    t = q(full, metrics=["unique_customers", "repeat_customer_rate"])["totals"]
    assert t["unique_customers"] == REFERENCE["unique_customers"]
    assert round(t["repeat_customer_rate"], 2) == REFERENCE["repeat_rate"]


def test_more_eval_values(full):
    asia = q(full, metrics=["gross_revenue"], group_by=["country"], filters=Filters(regions=["Asia"]), limit=1)["rows"][0]
    assert (asia["country"], round(asia["gross_revenue"], 2)) == REFERENCE["asia_top_country"]
    spain = q(full, metrics=["return_rate"], filters=Filters(countries=["Spain"]))["totals"]
    assert round(spain["return_rate"], 2) == REFERENCE["spain_return_rate"]
    prod = q(full, metrics=["gross_profit"], group_by=["product"], filters=Filters(categories=["Electronics"]), limit=1)["rows"][0]
    assert (prod["product"], round(prod["gross_profit"], 2)) == REFERENCE["electronics_top_profit_product"]
    debit = q(full, metrics=["cancellation_rate"], filters=Filters(payment_methods=["Debit Card"]))["totals"]
    assert round(debit["cancellation_rate"], 2) == REFERENCE["debit_card_cancellation"]


def test_loss_starts_at_40_percent_discount(full):
    rows = q(full, metrics=["loss_order_pct"], group_by=["discount_band"], filters=Filters(categories=["Electronics"]))["rows"]
    by = {r["discount_band"]: r["loss_order_pct"] for r in rows}
    assert by["25%"] == 0
    assert by["40%"] > 40
