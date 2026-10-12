"""The list of all routes and their access policy. test_route_coverage checks that each route is here,
that data routes use get_scoped_dataset, and that admin routes need admin."""

from __future__ import annotations

# (method, path) -> policy
ROUTE_POLICY: dict[tuple[str, str], str] = {
    ("GET", "/api/health/live"): "public",
    ("GET", "/api/health/ready"): "public",
    ("POST", "/api/auth/login"): "public",
    ("POST", "/api/auth/logout"): "public",
    ("GET", "/api/auth/me"): "any",
    ("POST", "/api/auth/password"): "any",
    ("GET", "/api/meta/catalog"): "dashboard",
    ("GET", "/api/meta/metrics"): "any",
    ("GET", "/api/meta/columns"): "any",
    ("GET", "/api/meta/data-notes"): "dashboard",
    ("POST", "/api/analytics/query"): "dashboard",
    ("POST", "/api/analytics/batch"): "dashboard",
    ("POST", "/api/analytics/kpis"): "dashboard",
    ("POST", "/api/analytics/compare"): "dashboard",
    ("POST", "/api/analytics/distribution"): "dashboard",
    ("GET", "/api/analytics/insights"): "dashboard",
    ("POST", "/api/orders/search"): "orders",
    ("GET", "/api/orders/{order_id}"): "orders",
    ("POST", "/api/export/orders"): "export",
    ("POST", "/api/export/query"): "export",
    ("POST", "/api/chat/stream"): "chat",
    ("POST", "/api/chat/ask"): "chat",
    ("GET", "/api/chat/status"): "chat",
    ("GET", "/api/chat/suggestions"): "chat",
    ("GET", "/api/chat/sessions"): "chat",
    ("GET", "/api/chat/sessions/{session_id}"): "chat",
    ("POST", "/api/chat/messages/{message_id}/feedback"): "chat",
    ("GET", "/api/admin/users"): "admin",
    ("POST", "/api/admin/users"): "admin",
    ("PATCH", "/api/admin/users/{user_id}"): "admin",
    ("POST", "/api/admin/users/{user_id}/reset-password"): "admin",
    ("GET", "/api/admin/audit"): "admin",
    ("GET", "/api/admin/audit/export"): "admin",
    ("GET", "/api/admin/roles"): "admin",
    ("GET", "/api/admin/system"): "admin",
    ("GET", "/api/admin/ai-quality"): "admin",
}

DATA_POLICIES = {"dashboard", "orders", "export", "chat"}


def iter_api_routes(app_or_router, prefix: str = ""):
    """Yield (method, path, APIRoute) for every API route (FastAPI keeps included routers as lazy objects)."""
    from fastapi.routing import APIRoute

    for r in getattr(app_or_router, "routes", []):
        if isinstance(r, APIRoute):
            for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
                yield m, prefix + r.path, r
        elif hasattr(r, "original_router"):
            ctx = getattr(r, "include_context", None)
            extra = getattr(ctx, "prefix", "") or ""
            yield from iter_api_routes(r.original_router, prefix + extra)
