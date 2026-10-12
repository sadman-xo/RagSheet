"""Order search pages (date windows + keyset cursor) give the same rows as a full sort (pandas oracle)."""

from __future__ import annotations

import pytest

from tests.conftest import bearer

CASES = [
    ("exec", {}, "date_desc"),
    ("exec", {}, "date_asc"),
    ("exec", {"years": [2023]}, "date_desc"),
    ("exec", {"date_from": "2022-03-01", "date_to": "2022-03-20"}, "date_asc"),
    ("exec", {"products": ["Dell XPS 15"]}, "date_desc"),  # few rows a day: the window must grow
    ("rm.asia", {"categories": ["Books & Media"], "years": [2024]}, "date_desc"),
    ("cm.home", {"statuses": ["Cancelled"]}, "date_asc"),
]


def _oracle(sample_csv, user: str, filters: dict, sort: str) -> list[str]:
    from eval import reference

    df = reference.load(str(sample_csv))
    scope = {"rm.asia": {"regions": ["Asia"]}, "cm.home": {"categories": ["Home & Kitchen"]}}.get(user, {})
    df = reference.apply_filters(reference.apply_filters(df, scope), filters)
    asc = sort == "date_asc"
    df = df.sort_values(["order_date", "order_id"], ascending=[asc, asc])
    return list(df.order_id)


@pytest.mark.parametrize("user,filters,sort", CASES)
def test_pages_equal_full_sort(client, tokens, sample_csv, user, filters, sort):
    expected = _oracle(sample_csv, user, filters, sort)
    got: list[str] = []
    body = {"limit": 40, "filters": filters, "sort": sort}
    total = None
    for _ in range(4):  # the first 4 pages
        r = client.post("/api/orders/search", json=body, headers=bearer(tokens, user))
        assert r.status_code == 200, r.text
        data = r.json()
        total = data["total"] if total is None else total
        got += [row["order_id"] for row in data["rows"]]
        if not data["next_cursor"]:
            break
        body = {**body, "cursor": data["next_cursor"], "with_total": False}
    assert total == len(expected)
    assert got == expected[: len(got)]
    assert len(got) == min(len(expected), 160)
