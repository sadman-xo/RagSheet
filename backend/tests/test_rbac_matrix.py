"""Each demo user x each data route x normal and changed payloads."""

from __future__ import annotations

import csv
import io

import pytest

from app.analytics.metrics import FINANCIAL_METRICS
from app.data import vocab
from app.data.schema import FINANCIAL_COLUMNS
from tests.conftest import DEMO_USERS, bearer

SCOPE = {
    "admin": (vocab.REGIONS, vocab.CATEGORIES), "exec": (vocab.REGIONS, vocab.CATEGORIES),
    "analyst": (vocab.REGIONS, vocab.CATEGORIES), "ops": (vocab.REGIONS, vocab.CATEGORIES),
    "rm.namerica": (("North America",), vocab.CATEGORIES), "rm.europe": (("Europe",), vocab.CATEGORIES),
    "rm.asia": (("Asia",), vocab.CATEGORIES), "rm.mideast": (("Middle East",), vocab.CATEGORIES),
    "cm.electronics": (vocab.REGIONS, ("Electronics",)), "cm.clothing": (vocab.REGIONS, ("Clothing",)),
    "cm.home": (vocab.REGIONS, ("Home & Kitchen",)), "cm.books": (vocab.REGIONS, ("Books & Media",)),
    "cm.beauty": (vocab.REGIONS, ("Beauty & Health",)),
}
FIN_KEYS = set(FINANCIAL_METRICS) | set(FINANCIAL_COLUMNS)


def _keys(obj, out=None) -> set[str]:
    out = set() if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(str(k).split("__")[0])
            _keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _keys(v, out)
    return out


def _check_common(user: str, r) -> None:
    assert r.status_code == 200, f"{user}: {r.status_code} {r.text[:300]}"
    if user == "analyst":
        assert "CUST-" not in r.text
    if user == "ops":
        assert not (_keys(r.json()) & FIN_KEYS), f"ops sees {_keys(r.json()) & FIN_KEYS}"


@pytest.mark.parametrize("user", DEMO_USERS)
def test_analytics_query_and_batch(client, tokens, user):
    regions, cats = SCOPE[user]
    h = bearer(tokens, user)
    r = client.post("/api/analytics/query", json={"metrics": ["gross_revenue", "orders"], "group_by": ["region", "category"]}, headers=h)
    _check_common(user, r)
    rows = r.json()["rows"]
    assert {x["region"] for x in rows} == set(regions)
    assert {x["category"] for x in rows} == set(cats)
    r = client.post("/api/analytics/batch", json={"queries": {"a": {"metrics": ["orders"], "group_by": ["country"]},
                                                              "b": {"metrics": ["aov"], "time_grain": "year"}}}, headers=h)
    _check_common(user, r)
    countries = {x["country"] for x in r.json()["results"]["a"]["rows"]}
    assert countries <= {c for c in vocab.COUNTRIES if vocab.COUNTRY_REGION[c] in regions}


@pytest.mark.parametrize("user", DEMO_USERS)
def test_pages_endpoints(client, tokens, user):
    h = bearer(tokens, user)
    for method, url, body in (
        ("POST", "/api/analytics/kpis", {"filters": {"years": [2023]}}),
        ("GET", "/api/analytics/insights", None),
        ("GET", "/api/meta/catalog", None),
        ("GET", "/api/meta/data-notes", None),
        ("GET", "/api/meta/columns", None),
        ("POST", "/api/analytics/distribution", {"field": "shipping_days", "group_by": "region"}),
        ("POST", "/api/analytics/compare", {"a": {"label": "2022", "filters": {"years": [2022]}}, "b": {"label": "2023", "filters": {"years": [2023]}},
                                            "metrics": ["gross_revenue", "orders"], "group_by": "shipping_method", "time_grain": "year_month"}),
        ("POST", "/api/orders/search", {"limit": 50}),
    ):
        r = client.request(method, url, json=body, headers=h)
        if url == "/api/meta/columns":
            assert r.status_code == 200
            cols = {c["name"]: c for c in r.json()["columns"]}
            assert all(cols[c]["visible"] == (user != "ops") for c in FINANCIAL_COLUMNS)
            continue
        _check_common(user, r)
    cat = client.get("/api/meta/catalog", headers=h).json()
    assert [x["name"] for x in cat["regions"]] == list(SCOPE[user][0])
    assert [x["name"] for x in cat["categories"]] == list(SCOPE[user][1])


@pytest.mark.parametrize("user", DEMO_USERS)
def test_orders_and_exports(client, tokens, user, scope_cache, data_version):
    regions, cats = SCOPE[user]
    h = bearer(tokens, user)
    r = client.post("/api/orders/search", json={"limit": 200, "with_total": True}, headers=h)
    _check_common(user, r)
    body = r.json()
    assert all(x["region"] in regions and x["category"] in cats for x in body["rows"])
    if user == "analyst":
        assert all(x["customer_id"].startswith("C-") for x in body["rows"])
    # keyset paging: page 2 continues after page 1 without overlap
    r2 = client.post("/api/orders/search", json={"limit": 200, "cursor": body["next_cursor"]}, headers=h)
    ids1 = {x["order_id"] for x in body["rows"]}
    ids2 = {x["order_id"] for x in r2.json()["rows"]}
    assert ids1 and ids2 and not ids1 & ids2
    # an order outside the scope gives 404 (same as a missing order)
    full = scope_cache.get(data_version, "all:full").cursor()
    outside = full.execute("SELECT order_id FROM orders WHERE region NOT IN (SELECT unnest($r)) OR category NOT IN (SELECT unnest($c)) LIMIT 1",
                           {"r": list(regions), "c": list(cats)}).fetchone()
    inside = body["rows"][0]["order_id"]
    assert client.get(f"/api/orders/{inside}", headers=h).status_code == 200
    if outside:
        assert client.get(f"/api/orders/{outside[0]}", headers=h).status_code == 404
    assert client.get("/api/orders/ORD-999999", headers=h).status_code == 404
    # export
    r = client.post("/api/export/orders", json={"limit": 50}, headers=h)
    assert r.status_code == 200
    rows = list(csv.reader(io.StringIO(r.text)))
    header = rows[0]
    if user == "ops":
        assert not {"Cost", "Profit", "Margin % (row)"} & set(header)
    if user == "analyst":
        assert "CUST-" not in r.text
    assert len(rows) > 50  # max 10k, not the page size


@pytest.mark.parametrize("user,body,code", [
    ("rm.asia", {"metrics": ["gross_revenue"], "filters": {"regions": ["Europe"]}}, 403),
    ("rm.asia", {"metrics": ["gross_revenue"], "filters": {"countries": ["Spain"]}}, 403),
    ("rm.europe", {"metrics": ["gross_revenue"], "filters": {"regions": ["Asia", "Europe"]}}, 403),
    ("cm.electronics", {"metrics": ["gross_revenue"], "filters": {"categories": ["Clothing"]}}, 403),
    ("cm.electronics", {"metrics": ["gross_revenue"], "filters": {"products": ["Nike Air Max"]}}, 403),
    ("cm.books", {"metrics": ["gross_revenue"], "filters": {"sub_categories": ["Laptops"]}}, 403),
    ("ops", {"metrics": ["margin_pct"]}, 403),
    ("ops", {"metrics": ["orders"], "sort_by": "orders", "group_by": ["region"]}, 200),
    ("ops", {"metrics": ["gross_profit", "orders"]}, 403),
    ("exec", {"metrics": ["not_a_metric"]}, 422),
    ("exec", {"metrics": ["orders"], "group_by": ["password_hash"]}, 422),
    ("exec", {"metrics": ["orders"], "filters": {"regions": ["Atlantis"]}}, 422),
    ("exec", {"metrics": ["orders"], "extra": 1}, 422),
    ("exec", {"metrics": ["orders"], "limit": 100000}, 422),
    ("exec", {"metrics": ["orders"], "group_by": ["region; DROP TABLE x"]}, 422),
])
def test_changed_payloads(client, tokens, user, body, code, owner_db):
    from tests.conftest import audit_rows, max_audit_id

    start = max_audit_id(owner_db)
    r = client.post("/api/analytics/query", json=body, headers=bearer(tokens, user))
    assert r.status_code == code, r.text
    if code == 403:
        assert audit_rows(owner_db, username=user, since_id=start), "a denial must be audited"


def test_changed_payloads_on_other_routes(client, tokens):
    h = bearer(tokens, "rm.asia")
    assert client.post("/api/orders/search", json={"filters": {"regions": ["Europe"]}}, headers=h).status_code == 403
    assert client.post("/api/export/orders", json={"filters": {"countries": ["UK"]}}, headers=h).status_code == 403
    assert client.post("/api/analytics/kpis", json={"filters": {"regions": ["Europe"]}}, headers=h).status_code == 403
    assert client.post("/api/analytics/batch", json={"queries": {"ok": {"metrics": ["orders"]},
                                                                  "bad": {"metrics": ["orders"], "filters": {"regions": ["Europe"]}}}},
                       headers=h).status_code == 403
    assert client.post("/api/analytics/distribution", json={"field": "profit"}, headers=bearer(tokens, "ops")).status_code == 403
    assert client.post("/api/export/query", json={"metrics": ["cost"]}, headers=bearer(tokens, "ops")).status_code == 403
    r = client.post("/api/orders/search", json={"q": "CUST-02791"}, headers=bearer(tokens, "analyst"))
    assert r.status_code == 200 and r.json()["rows"] == []
