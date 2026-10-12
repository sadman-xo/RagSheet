from __future__ import annotations

from app.api.route_policy import ROUTE_POLICY, iter_api_routes
from app.main import app
from app.security.deps import get_principal, get_scoped_dataset
from tests.conftest import bearer


def _calls(dependant) -> set:
    out = set()
    for d in dependant.dependencies:
        out.add(d.call)
        out |= _calls(d)
    return out


def _names(dependant) -> set[str]:
    return {getattr(c, "__name__", "") for c in _calls(dependant)}


def _policies() -> dict:
    try:
        import app.api.chat  # noqa: F401
        return ROUTE_POLICY
    except ImportError:  # before the chat milestone
        return {k: v for k, v in ROUTE_POLICY.items() if v != "chat"}


def test_every_route_is_in_the_policy_list():
    routes = {(m, p) for m, p, _ in iter_api_routes(app)}
    assert routes - set(ROUTE_POLICY) == set(), "routes without a policy"
    assert set(_policies()) - routes == set(), "policies without a route"


def test_dependencies_match_the_policy():
    for method, path, route in iter_api_routes(app):
        policy = ROUTE_POLICY[(method, path)]
        calls = _calls(route.dependant)
        names = _names(route.dependant)
        if policy in ("dashboard", "orders", "export"):
            assert get_scoped_dataset in calls, f"{method} {path} must use get_scoped_dataset"
        if policy == "export":
            assert "require_export" in names, path
        if policy == "chat":
            assert "require_chat" in names, path
        if policy == "admin":
            assert "require_admin" in names, path
        if policy == "any":
            assert get_principal in calls, path
        if policy == "public":
            assert get_principal not in calls, path


def test_unauthenticated_requests_get_401(client):
    client.cookies.clear()
    for (method, path), policy in _policies().items():
        if policy == "public":
            continue
        url = path.replace("{order_id}", "ORD-000001").replace("{user_id}", "1").replace("{session_id}", "1").replace("{message_id}", "1")
        r = client.request(method, url, json={})
        assert r.status_code == 401, f"{method} {path}: {r.status_code}"


def test_admin_routes_need_admin(client, tokens):
    for (method, path), policy in ROUTE_POLICY.items():
        if policy != "admin":
            continue
        url = path.replace("{user_id}", "1")
        for user in ("exec", "analyst", "ops", "rm.asia"):
            r = client.request(method, url, json={}, headers=bearer(tokens, user))
            assert r.status_code == 403, f"{user} {method} {path}: {r.status_code}"
