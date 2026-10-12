"""AST checks of the module boundaries."""

from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"


def _modules():
    for p in APP.rglob("*.py"):
        rel = p.relative_to(APP.parent).with_suffix("")
        yield ".".join(rel.parts), ast.parse(p.read_text(encoding="utf-8")), p.read_text(encoding="utf-8")


def _imports(tree) -> set[str]:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
            out |= {f"{node.module}.{a.name}" for a in node.names}
    return out


def _calls(tree) -> set[str]:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
                out.add(f"{f.value.id}.{f.attr}")
            elif isinstance(f, ast.Name):
                out.add(f.id)
    return out


def test_only_loader_and_generator_read_dataset_files():
    for name, tree, src in _modules():
        if name in ("app.data.loader", "app.data.generator", "app.config"):
            continue
        assert "read_csv" not in src or name in ("app.data.scopestore",), name
        assert "ecommerce_sales" not in src or name in ("app.config",), name


def test_only_scopestore_calls_scope_rows():
    for name, tree, src in _modules():
        if "scope_rows(" in src and name not in ("app.data.scopestore",):
            # the schema helpers only name the function's columns, never call it
            assert name in ("app.data.schema",), name


def test_only_scoped_and_scopestore_open_duckdb():
    for name, tree, src in _modules():
        if "duckdb.connect" in _calls(tree) or "duckdb.connect(" in src:
            assert name in ("app.data.scoped", "app.data.scopestore"), name


def test_gateway_imports_no_data_code():
    forbidden = ("app.data", "app.analytics", "app.rag", "app.db", "app.security", "app.api", "app.chat")
    for name, tree, _src in _modules():
        if name.startswith("app.gateway"):
            for imp in _imports(tree):
                assert not imp.startswith(forbidden), f"{name} imports {imp}"


def _walk_skip_sync_defs(node):
    """Walk an async function, but not into nested sync functions (they run in threads through run_sync)."""
    stack = list(ast.iter_child_nodes(node))
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.Lambda)):
            continue
        yield n
        stack.extend(ast.iter_child_nodes(n))


def test_async_code_uses_run_sync_for_the_database():
    """Async functions must not open database transactions directly."""
    for name, tree, _src in _modules():
        if not (name.startswith("app.chat") or name.startswith("app.api")):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                for sub in _walk_skip_sync_defs(node):
                    if isinstance(sub, ast.Call):
                        f = sub.func
                        if isinstance(f, ast.Attribute) and f.attr in ("scoped", "unscoped", "write", "begin", "connect") \
                                and isinstance(f.value, ast.Name) and f.value.id in ("db", "engine", "dbengine"):
                            raise AssertionError(f"{name}.{node.name} calls db.{f.attr} directly; use db.run_sync")


def test_rest_routes_are_sync_and_chat_routes_async():
    from app.api.route_policy import iter_api_routes
    from app.main import app

    import inspect

    for method, path, route in iter_api_routes(app):
        is_async = inspect.iscoroutinefunction(route.endpoint)
        if path in ("/api/chat/stream", "/api/chat/ask"):
            assert is_async, path
        elif not path.startswith("/api/chat/") and path not in ("/api/admin/system",):
            assert not is_async, path
