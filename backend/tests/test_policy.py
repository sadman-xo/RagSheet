from __future__ import annotations

import pytest

from app.analytics.spec import Filters, QuerySpec
from app.data import vocab
from app.data.scopestore import scope_keys
from app.security import policy
from app.security.policy import PolicyError, authorize, build_scope
from tests.conftest import audit_rows, bearer, max_audit_id


def test_unknown_role_and_missing_scope_fail_closed():
    with pytest.raises(PolicyError) as e:
        build_scope("superuser", None, None)
    assert e.value.status == 403
    with pytest.raises(PolicyError):
        build_scope("regional_manager", None, None)
    with pytest.raises(PolicyError):
        build_scope("regional_manager", "Atlantis", None)
    with pytest.raises(PolicyError):
        build_scope("category_manager", None, "")


def test_columns_for_each_role():
    fin = {"cost", "profit", "profit_margin_pct", "is_loss", "profit_after_shipping"}
    for role in vocab.ROLES:
        sc = build_scope(role, "Asia", "Clothing")
        cols = set(sc.visible_columns())
        if role == "operations":
            assert not cols & fin
            assert "profitability" not in sc.pages and "customers" not in sc.pages
        else:
            assert fin <= cols
        assert ("admin" in sc.pages) == (role == "admin")
        assert sc.pii_raw == (role != "analyst")


def test_scope_keys_and_fingerprints_differ():
    scopes = [build_scope("admin", None, None), build_scope("analyst", None, None), build_scope("operations", None, None)]
    scopes += [build_scope("regional_manager", r, None) for r in vocab.REGIONS]
    scopes += [build_scope("category_manager", None, c) for c in vocab.CATEGORIES]
    keys = [s.scope_key for s in scopes]
    assert sorted(keys) == sorted(scope_keys())
    assert len({s.fingerprint for s in scopes}) == 12
    assert build_scope("admin", None, None).scope_key == build_scope("executive", None, None).scope_key


def test_authorize():
    rm = build_scope("regional_manager", "Asia", None)
    authorize(QuerySpec(metrics=["gross_revenue"], filters=Filters(regions=["Asia"], countries=["Japan"])), rm)
    for f in (Filters(regions=["Europe"]), Filters(countries=["Spain"]), Filters(regions=["Asia", "Europe"])):
        with pytest.raises(PolicyError) as e:
            authorize(QuerySpec(metrics=["gross_revenue"], filters=f), rm)
        assert e.value.code == "OUT_OF_SCOPE"
    cm = build_scope("category_manager", None, "Electronics")
    with pytest.raises(PolicyError):
        authorize(QuerySpec(metrics=["orders"], filters=Filters(products=["Nike Air Max"])), cm)
    ops = build_scope("operations", None, None)
    with pytest.raises(PolicyError) as e:
        authorize(QuerySpec(metrics=["orders", "margin_pct"]), ops)
    assert e.value.code == "FORBIDDEN_METRIC"
    authorize(QuerySpec(metrics=["orders", "return_rate"], group_by=["region"]), ops)


def test_scope_mismatch_fails_closed(client, tokens, owner_db, monkeypatch):
    """If the database key and the build_scope key differ, the request fails with 500 and an audit row."""
    real = policy.build_scope

    def wrong(role, region, category):
        if role == "regional_manager":
            return real(role, "Europe", None)
        return real(role, region, category)

    import app.security.deps as deps

    monkeypatch.setattr(deps, "build_scope", wrong)
    start = max_audit_id(owner_db)
    r = client.post("/api/analytics/query", json={"metrics": ["gross_revenue"]}, headers=bearer(tokens, "rm.asia"))
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "SCOPE_MISMATCH"
    rows = audit_rows(owner_db, "scope_mismatch", "rm.asia", since_id=start)
    assert rows and rows[0]["detail"]["db_scope_key"] == "region:Asia"
