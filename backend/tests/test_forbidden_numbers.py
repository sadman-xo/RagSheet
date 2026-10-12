"""Out-of-scope totals, in different formats, never appear in a scoped user's responses or CSV files."""

from __future__ import annotations

import pytest

from app.analytics.formatting import number_forms
from eval import reference
from tests.conftest import bearer

REQUESTS = [
    ("POST", "/api/analytics/kpis", {}),
    ("POST", "/api/analytics/kpis", {"filters": {"years": [2023]}}),
    ("POST", "/api/analytics/query", {"metrics": ["gross_revenue", "net_revenue", "orders"], "group_by": ["region"]}),
    ("POST", "/api/analytics/query", {"metrics": ["gross_revenue"], "group_by": ["category"]}),
    ("POST", "/api/analytics/query", {"metrics": ["gross_revenue"], "time_grain": "year"}),
    ("GET", "/api/analytics/insights", None),
    ("GET", "/api/meta/data-notes", None),
    ("GET", "/api/meta/catalog", None),
    ("POST", "/api/export/query", {"metrics": ["gross_revenue", "gross_profit"], "group_by": ["country"]}),
    ("POST", "/api/analytics/compare", {"a": {"label": "a", "filters": {"years": [2022]}}, "b": {"label": "b", "filters": {"years": [2023]}},
                                        "metrics": ["gross_revenue"]}),
]


def _forbidden(df_all, user_scope: str) -> list[str]:
    """Totals that the user must never see: the company total and other scopes' totals."""
    out = []
    totals = [df_all["revenue"].sum(), df_all["profit"].sum()]
    kind, _, value = user_scope.partition(":")
    col = "region" if kind == "region" else "category"
    for other, g in df_all.groupby(col):
        if other != value:
            totals += [g["revenue"].sum(), g["profit"].sum()]
            for y, gy in g.groupby("year"):
                totals.append(gy["revenue"].sum())
    forms = []
    for t in totals:
        forms += [f for f in number_forms(round(float(t), 2)) if len(f) >= 6]
    return forms


@pytest.mark.parametrize("user,scope", [("rm.asia", "region:Asia"), ("rm.europe", "region:Europe"),
                                        ("cm.electronics", "category:Electronics"), ("cm.beauty", "category:Beauty & Health")])
def test_no_out_of_scope_numbers(client, tokens, sample_csv, user, scope):
    df = reference.load(str(sample_csv))
    forbidden = _forbidden(df, scope)
    assert "1,274,657.55" in forbidden or user != "rm.asia"  # Europe revenue for the Asia manager
    h = bearer(tokens, user)
    for method, url, body in REQUESTS:
        r = client.request(method, url, json=body, headers=h)
        assert r.status_code == 200, (url, r.text[:200])
        text = r.text
        hits = [f for f in forbidden if f in text]
        assert not hits, f"{user} {url}: {hits[:3]}"
