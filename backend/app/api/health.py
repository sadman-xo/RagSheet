"""Health endpoints (no data values)."""

from __future__ import annotations

import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import get_settings
from app.data.scoped import load_manifest
from app.db import engine as db

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("/live")
def live() -> dict:
    s = get_settings()
    return {"status": "ok", "replica": s.replica, "pid": os.getpid()}


@router.get("/ready")
def ready():
    s = get_settings()
    checks = {"database": False, "scope_manifest": False}
    try:
        with db.unscoped() as c:
            dv = c.execute(text("SELECT data_version FROM sales.meta WHERE id = 1")).scalar()
        checks["database"] = True
        if dv:
            load_manifest(s.scopes_dir, dv)
            checks["scope_manifest"] = True
    except Exception:
        pass
    ok = all(checks.values())
    return JSONResponse(status_code=200 if ok else 503,
                        content={"status": "ok" if ok else "not_ready", "replica": s.replica, "checks": checks})
