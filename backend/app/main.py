"""Panorama api (FastAPI). Stateless: any replica can serve any request.

REST routes are plain `def` (FastAPI runs them in its thread pool). Only the chat routes are async.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app import audit
from app.config import get_settings, set_thread_limits

set_thread_limits()

from app.api import admin, analytics, auth, export, health, meta, orders  # noqa: E402
from app.api import errors  # noqa: E402

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    audit.buffer.start()
    try:  # open the scope files now (checksums, connections), not in the first request
        import threading

        from app.data.scoped import get_cache, load_manifest
        from app.db import engine as dbe
        from sqlalchemy import text as _text

        def _warm() -> None:
            try:
                with dbe.unscoped() as c:
                    dv = c.execute(_text("SELECT data_version FROM sales.meta WHERE id = 1")).scalar()
                if dv:
                    for key in load_manifest(get_settings().scopes_dir, dv)["files"]:
                        get_cache().get(dv, key)
            except Exception as exc:  # the requests open the files later
                print(f"scope warm-up skipped: {exc}", flush=True)
            try:  # DuckDB imports pandas on the first result fetch; the chat parser compiles its patterns
                from datetime import date

                import pandas  # noqa: F401

                from app.chat.entities import parse
                from app.security.policy import build_scope

                parse("What was the gross revenue of Electronics in Q3 2023?", build_scope("executive", None, None), date.today())
            except Exception as exc:  # pragma: no cover
                print(f"chat warm-up skipped: {exc}", flush=True)

        threading.Thread(target=_warm, name="scope-warmup", daemon=True).start()
    except Exception:  # pragma: no cover
        pass
    try:  # load the embedding model now, not in the first chat turn
        import anyio

        from app.rag.embedder import get_embedder

        await anyio.to_thread.run_sync(lambda: get_embedder().embed_query("warm up"))
    except Exception as exc:  # pragma: no cover - the model is in the image
        print(f"embedder warm-up failed: {exc}", flush=True)
    try:
        from app.chat import gateway_client

        await gateway_client.startup()
    except ImportError:  # pragma: no cover
        pass
    yield
    try:
        from app.chat import gateway_client

        await gateway_client.shutdown()
    except ImportError:  # pragma: no cover
        pass
    audit.buffer.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="Panorama API", version="1.0.0", docs_url=None, redoc_url=None,
                  openapi_url="/api/openapi.json", lifespan=lifespan)
    errors.install(app)
    settings = get_settings()
    origins = set(settings.origins)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = str(uuid.uuid4())
        audit.buffer.requests += 1
        # Origin check for state-changing requests. Bearer-token clients (tests, load test) send Origin too,
        # but a missing Origin is accepted only with a Bearer token.
        if request.method in UNSAFE and request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            has_bearer = request.headers.get("authorization", "").lower().startswith("bearer ")
            if origin is not None and origin not in origins:
                return JSONResponse(status_code=403, content={"error": {"code": "BAD_ORIGIN", "message": "Origin not allowed.", "detail": {}}})
            if origin is None and not has_bearer:
                return JSONResponse(status_code=403, content={"error": {"code": "BAD_ORIGIN", "message": "Origin header required.", "detail": {}}})
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Replica"] = settings.replica
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    for module in (health, auth, meta, analytics, orders, export, admin):
        app.include_router(module.router)
    try:
        from app.api import chat

        app.include_router(chat.router)
    except ImportError:  # pragma: no cover - before M8
        pass
    return app


app = create_app()
