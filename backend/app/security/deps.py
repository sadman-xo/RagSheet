"""Request dependencies: principal -> scope (+ database key check) -> scoped dataset.

The principal read is one primary-key read (plus app.current_scope_key() and the data version) in one
autocommit statement (app.load_principal) that ends before the route body. It is never cached across requests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from fastapi import Depends, Request
from sqlalchemy import text

from app import audit
from app.api.errors import ApiError
from app.data.scoped import ScopeFile, get_cache
from app.db import engine as db
from app.security import tokens
from app.security.policy import PolicyError, Scope, build_scope

# One statement in autocommit mode (one round trip): the function sets the transaction-local app.user_id,
# so app.current_scope_key() is calculated by the database for this user, and the setting ends with the statement.
PRINCIPAL_SQL = text("SELECT * FROM app.load_principal(:uid)")


@dataclass(frozen=True)
class Principal:
    id: int
    username: str
    display_name: str
    role: str
    region: str | None
    category: str | None
    token_version: int
    is_synthetic: bool
    db_scope_key: str | None
    data_version: str | None
    dataset: str | None
    row_count: int | None
    data_min: date | None
    data_max: date | None


@dataclass(frozen=True)
class ScopedDataset:
    principal: Principal
    scope: Scope
    file: ScopeFile


def request_info(request: Request) -> audit.RequestInfo:
    ip = request.client.host if request.client else None
    return audit.RequestInfo(ip=ip, request_id=getattr(request.state, "request_id", None))


def _token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return request.cookies.get(tokens.COOKIE)


def load_principal(user_id: int) -> Principal | None:
    with db.autocommit() as c:
        r = c.execute(PRINCIPAL_SQL, {"uid": int(user_id)}).mappings().first()
    if r is None or not r["is_active"]:
        return None
    return Principal(
        id=r["id"], username=r["username"], display_name=r["display_name"], role=r["role"], region=r["region"],
        category=r["category"], token_version=r["token_version"], is_synthetic=r["is_synthetic"],
        db_scope_key=r["db_scope_key"], data_version=r["data_version"], dataset=r["dataset"],
        row_count=r["row_count"], data_min=r["min_date"], data_max=r["max_date"],
    )


def get_principal(request: Request) -> Principal:
    tok = _token(request)
    if not tok:
        raise ApiError(401, "NOT_AUTHENTICATED", "Please sign in.")
    try:
        uid, ver = tokens.decode(tok)
    except tokens.TokenError:
        raise ApiError(401, "SESSION_INVALID", "Your session is not valid. Please sign in again.")
    p = load_principal(uid)
    if p is None or p.token_version != ver:
        raise ApiError(401, "SESSION_EXPIRED", "Your session has ended. Please sign in again.")
    request.state.principal = p
    return p


def get_scope(request: Request, principal: Principal = Depends(get_principal)) -> Scope:
    try:
        scope = build_scope(principal.role, principal.region, principal.category)
    except PolicyError as exc:
        audit.record_now("permission_denied", **audit.principal_fields(principal), req=request_info(request),
                         detail={"code": exc.code, "path": request.url.path})
        raise
    if principal.db_scope_key != scope.scope_key:
        # Two independent calculations disagree: fail closed.
        audit.record_now("scope_mismatch", **audit.principal_fields(principal), req=request_info(request),
                         detail={"app_scope_key": scope.scope_key, "db_scope_key": principal.db_scope_key,
                                 "path": request.url.path})
        raise ApiError(500, "SCOPE_MISMATCH", "Your data scope could not be confirmed. The request was stopped.")
    request.state.scope = scope
    return scope


def require(capability: str):
    def _dep(request: Request, principal: Principal = Depends(get_principal), scope: Scope = Depends(get_scope)) -> Scope:
        if capability not in scope.capabilities:
            audit.record_now("permission_denied", **audit.principal_fields(principal, scope.scope_key),
                             req=request_info(request), detail={"capability": capability, "path": request.url.path})
            raise ApiError(403, "FORBIDDEN", "Your role cannot use this feature.")
        return scope
    _dep.__name__ = f"require_{capability}"
    return _dep


require_admin = require("admin")


def open_scope_file(principal: Principal, scope: Scope) -> ScopeFile:
    if not principal.data_version:
        raise ApiError(503, "NO_DATA", "No data is loaded yet.")
    return get_cache().get(principal.data_version, scope.scope_key)


def get_scoped_dataset(request: Request, principal: Principal = Depends(get_principal),
                       scope: Scope = Depends(require("dashboard"))) -> ScopedDataset:
    return ScopedDataset(principal=principal, scope=scope, file=open_scope_file(principal, scope))


def scope_violation(request: Request, ds_or_principal, scope: Scope, exc: PolicyError, extra: dict | None = None) -> None:
    principal = ds_or_principal.principal if isinstance(ds_or_principal, ScopedDataset) else ds_or_principal
    action = "scope_violation" if exc.code == "OUT_OF_SCOPE" else "permission_denied"
    audit.record_now(action, **audit.principal_fields(principal, scope.scope_key), req=request_info(request),
                     detail={"code": exc.code, "path": request.url.path, **exc.detail, **(extra or {})})
