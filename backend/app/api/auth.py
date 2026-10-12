"""Authentication routes.

Lockout = reserve, then verify:
1. A username read gets the user ID (an unknown username gets a dummy-hash bcrypt and 401).
2. One UPDATE ... WHERE id AND is_active AND not locked ... RETURNING counts the attempt. All new values are
   calculated in SET from the row. The transaction commits before bcrypt. The row lock makes parallel attempts
   wait in turn on all replicas, so exactly 5 attempts are counted. No row returned -> 429 without bcrypt.
3. On success, one transaction resets the counter and writes the login audit row.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from app import audit
from app.api.errors import ApiError
from app.config import get_settings
from app.db import engine as db
from app.ratelimit import login_limiter
from app.security import passwords, tokens
from app.security.deps import Principal, get_principal, get_scope, request_info
from app.security.policy import ROLE_LABELS, Scope
from app.analytics.metrics import describe as describe_metrics

router = APIRouter(prefix="/api/auth", tags=["auth"])

RESERVE_SQL = text("""
UPDATE app.users SET
  failed_logins = CASE
      WHEN locked_until IS NOT NULL OR last_failed_at IS NULL OR last_failed_at < :now - make_interval(mins => :window)
      THEN 1 ELSE failed_logins + 1 END,
  last_failed_at = :now,
  locked_until = CASE
      WHEN (CASE WHEN locked_until IS NOT NULL OR last_failed_at IS NULL OR last_failed_at < :now - make_interval(mins => :window)
                 THEN 1 ELSE failed_logins + 1 END) >= :max_failures
      THEN :now + make_interval(mins => :lock_minutes) ELSE NULL END
WHERE id = :id AND is_active AND (locked_until IS NULL OR locked_until <= :now)
RETURNING password_hash, failed_logins, locked_until, token_version
""")

PAGES = [
    ("overview", "Overview", "/overview"), ("trends", "Trends", "/trends"), ("geography", "Geography", "/geography"),
    ("products", "Products", "/products"), ("profitability", "Profitability", "/profitability"),
    ("customers", "Customers", "/customers"), ("operations", "Operations", "/operations"),
    ("compare", "Compare", "/compare"), ("explorer", "Explorer", "/explorer"), ("orders", "Orders", "/orders"),
    ("assistant", "Assistant", "/assistant"), ("data-notes", "Data Notes", "/data-notes"), ("admin", "Admin", "/admin"),
]


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)
    want_token: bool = False


class PasswordBody(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


def _set_cookie(response: Response, token: str, ttl: int) -> None:
    s = get_settings()
    response.set_cookie(tokens.COOKIE, token, max_age=ttl, httponly=True, samesite="strict", secure=s.cookie_secure, path="/")


def me_payload(p: Principal, scope: Scope) -> dict:
    s = get_settings()
    return {
        "user": {"id": p.id, "username": p.username, "display_name": p.display_name, "role": p.role,
                 "role_label": ROLE_LABELS.get(p.role, p.role), "region": p.region, "category": p.category},
        "scope": scope.describe(),
        "fingerprint": scope.fingerprint,
        "capabilities": sorted(scope.capabilities),
        "pages": list(scope.pages),
        "navigation": [{"id": pid, "label": label, "path": path} for pid, label, path in PAGES if pid in scope.pages],
        "landing": scope.landing,
        "visible_columns": scope.visible_columns(),
        "allowed_metrics": scope.allowed_metrics(),
        "metrics": describe_metrics(scope.financial),
        "data": {"dataset": p.dataset, "data_version": p.data_version,
                 # The company row count is a company total: only roles with company totals get it.
                 "rows": p.row_count if scope.company_totals else None,
                 "min_date": p.data_min.isoformat() if p.data_min else None,
                 "max_date": p.data_max.isoformat() if p.data_max else None},
        "demo_mode": s.demo_mode,
        "replica": s.replica,
    }


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response) -> dict:
    s = get_settings()
    req = request_info(request)
    username = body.username.strip().lower()
    wait = login_limiter.take(username)
    if wait > 0:
        raise ApiError(429, "TOO_MANY_ATTEMPTS", "Too many sign-in attempts. Wait and try again.",
                       headers={"Retry-After": str(int(wait) + 1)})
    with db.unscoped() as c:
        row = c.execute(text("SELECT id, is_active FROM app.users WHERE username = :u"), {"u": username}).first()
    if row is None or not row.is_active:
        passwords.dummy_verify(body.password)
        audit.record_now("login_failed", username=username, req=req, detail={"reason": "unknown_or_inactive"})
        raise ApiError(401, "INVALID_LOGIN", "The username or password is not correct.")
    uid = row.id
    now = tokens.now()
    params = {"id": uid, "now": now, "window": s.lockout_window_minutes, "lock_minutes": s.lockout_minutes,
              "max_failures": s.lockout_max_failures}
    reserved = db.write(lambda c: c.execute(RESERVE_SQL, params).first())
    if reserved is None:
        audit.record_now("login_locked", user_id=uid, username=username, req=req)
        raise ApiError(429, "ACCOUNT_LOCKED", f"The account is locked for {s.lockout_minutes} minutes after "
                       f"{s.lockout_max_failures} failed sign-ins.", headers={"Retry-After": str(s.lockout_minutes * 60)})
    # bcrypt runs outside any transaction
    if not passwords.verify_password(body.password, reserved.password_hash):
        detail = {"failed_logins": reserved.failed_logins}
        if reserved.locked_until is not None:
            detail["locked_until"] = reserved.locked_until.isoformat()
        audit.record_now("login_failed", user_id=uid, username=username, req=req, detail=detail)
        raise ApiError(401, "INVALID_LOGIN", "The username or password is not correct.")

    def _success(c):
        r = c.execute(text("""UPDATE app.users SET failed_logins = 0, last_failed_at = NULL, locked_until = NULL,
                              last_login_at = :now WHERE id = :id RETURNING role, token_version"""),
                      {"id": uid, "now": now}).first()
        audit.record(c, "login", user_id=uid, username=username, role=r.role, req=req)
        return r

    r = db.write(_success)
    token, ttl = tokens.issue(uid, r.token_version)
    _set_cookie(response, token, ttl)
    p = get_principal_for(uid)
    from app.security.policy import build_scope

    payload = me_payload(p, build_scope(p.role, p.region, p.category))
    if body.want_token:
        payload["access_token"] = token
    return payload


def get_principal_for(uid: int) -> Principal:
    from app.security.deps import load_principal

    p = load_principal(uid)
    if p is None:
        raise ApiError(401, "SESSION_EXPIRED", "Please sign in again.")
    return p


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    try:
        p = get_principal(request)
    except ApiError:
        p = None
    if p is not None:
        audit.record_now("logout", **audit.principal_fields(p), req=request_info(request))
    response.delete_cookie(tokens.COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(principal: Principal = Depends(get_principal), scope: Scope = Depends(get_scope)) -> dict:
    return me_payload(principal, scope)


@router.post("/password")
def change_password(body: PasswordBody, request: Request, response: Response,
                    principal: Principal = Depends(get_principal)) -> dict:
    with db.unscoped() as c:
        h = c.execute(text("SELECT password_hash FROM app.users WHERE id = :id"), {"id": principal.id}).scalar_one()
    if not passwords.verify_password(body.current_password, h):
        audit.record_now("password_change_failed", **audit.principal_fields(principal), req=request_info(request))
        raise ApiError(400, "WRONG_PASSWORD", "The current password is not correct.")
    problems = passwords.password_problems(body.new_password)
    if problems:
        raise ApiError(422, "WEAK_PASSWORD", "The new password needs " + ", ".join(problems) + ".")
    new_hash = passwords.hash_password(body.new_password)

    def _w(c):
        v = c.execute(text("UPDATE app.users SET password_hash = :h, token_version = token_version + 1 WHERE id = :id "
                           "RETURNING token_version"), {"h": new_hash, "id": principal.id}).scalar_one()
        audit.record(c, "password_change", **audit.principal_fields(principal), req=request_info(request))
        return v

    ver = db.write(_w)
    token, ttl = tokens.issue(principal.id, ver)
    _set_cookie(response, token, ttl)
    return {"ok": True}

