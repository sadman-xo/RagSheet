"""Admin routes: users, audit log, role matrix, system, AI quality."""

from __future__ import annotations

import csv
import io
import json
import secrets as pysecrets
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from app import audit
from app.api.errors import ApiError
from app.config import get_settings
from app.data import vocab
from app.data.scoped import get_cache, load_manifest
from app.db import engine as db
from app.security import passwords
from app.security.deps import Principal, get_principal, request_info, require_admin
from app.security.policy import ROLE_LABELS, PolicyError, Scope, build_scope

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])

USER_COLS = ("id, username, display_name, role, region, category, is_active, is_synthetic, failed_logins, "
             "locked_until, created_at, last_login_at, token_version")


def _user_row(r) -> dict:
    d = dict(r._mapping)
    for k in ("locked_until", "created_at", "last_login_at"):
        if d.get(k) is not None:
            d[k] = d[k].isoformat()
    d["role_label"] = ROLE_LABELS.get(d["role"], d["role"])
    return d


@router.get("/users")
def list_users(include_synthetic: bool = False) -> dict:
    with db.unscoped() as c:
        rows = c.execute(text(f"SELECT {USER_COLS} FROM app.users WHERE (:syn OR NOT is_synthetic) ORDER BY id"),
                         {"syn": include_synthetic}).all()
    return {"users": [_user_row(r) for r in rows]}


class NewUser(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=40, pattern=r"^[a-z0-9._-]+$")
    display_name: str = Field(min_length=1, max_length=80)
    role: str
    region: str | None = None
    category: str | None = None
    password: str = Field(min_length=8, max_length=72)


class UserPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    role: str | None = None
    region: str | None = None
    category: str | None = None
    is_active: bool | None = None


def _validate_scope(role: str, region: str | None, category: str | None) -> tuple[str | None, str | None]:
    region = region if role == "regional_manager" else None
    category = category if role == "category_manager" else None
    try:
        build_scope(role, region, category)
    except PolicyError as exc:
        raise ApiError(422, "INVALID_SCOPE", exc.message)
    return region, category


@router.post("/users")
def create_user(body: NewUser, request: Request, admin: Principal = Depends(get_principal)) -> dict:
    region, category = _validate_scope(body.role, body.region, body.category)
    problems = passwords.password_problems(body.password)
    if problems:
        raise ApiError(422, "WEAK_PASSWORD", "The password needs " + ", ".join(problems) + ".")
    pw_hash = passwords.hash_password(body.password)

    def _w(c):
        exists = c.execute(text("SELECT 1 FROM app.users WHERE username = :u"), {"u": body.username}).first()
        if exists:
            raise ApiError(409, "USERNAME_TAKEN", "The username is already used.")
        r = c.execute(text(f"""INSERT INTO app.users (username, display_name, password_hash, role, region, category)
                              VALUES (:u, :d, :h, :r, :reg, :cat) RETURNING {USER_COLS}"""),
                      {"u": body.username, "d": body.display_name, "h": pw_hash, "r": body.role, "reg": region, "cat": category}).first()
        audit.record(c, "user_change", **audit.principal_fields(admin), req=request_info(request),
                     detail={"op": "create", "target": body.username, "role": body.role, "region": region, "category": category})
        return r

    return {"user": _user_row(db.write(_w))}


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserPatch, request: Request, admin: Principal = Depends(get_principal)) -> dict:
    def _w(c):
        cur = c.execute(text(f"SELECT {USER_COLS} FROM app.users WHERE id = :id FOR UPDATE"), {"id": user_id}).first()
        if cur is None:
            raise ApiError(404, "NOT_FOUND", "User not found.")
        role = body.role or cur.role
        region = body.region if body.region is not None else cur.region
        category = body.category if body.category is not None else cur.category
        region, category = _validate_scope(role, region, category)
        is_active = cur.is_active if body.is_active is None else body.is_active
        removes_admin = cur.role == "admin" and cur.is_active and (role != "admin" or not is_active)
        if removes_admin:
            # Lock all active admins, then count: two admins cannot remove each other at the same time.
            admins = c.execute(text("SELECT id FROM app.users WHERE role = 'admin' AND is_active FOR UPDATE")).all()
            if len(admins) <= 1:
                raise ApiError(409, "LAST_ADMIN", "The last active admin cannot be removed.")
        scope_changed = (role, region, category, is_active) != (cur.role, cur.region, cur.category, cur.is_active)
        r = c.execute(text(f"""UPDATE app.users SET display_name = :d, role = :r, region = :reg, category = :cat,
                               is_active = :act, token_version = token_version + :bump WHERE id = :id RETURNING {USER_COLS}"""),
                      {"d": body.display_name or cur.display_name, "r": role, "reg": region, "cat": category,
                       "act": is_active, "bump": 1 if scope_changed else 0, "id": user_id}).first()
        audit.record(c, "user_change", **audit.principal_fields(admin), req=request_info(request),
                     detail={"op": "update", "target": cur.username,
                             "before": {"role": cur.role, "region": cur.region, "category": cur.category, "is_active": cur.is_active},
                             "after": {"role": role, "region": region, "category": category, "is_active": is_active},
                             "sessions_ended": scope_changed})
        return r

    return {"user": _user_row(db.write(_w))}


class ResetBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    new_password: str | None = Field(default=None, min_length=8, max_length=72)


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, body: ResetBody, request: Request, admin: Principal = Depends(get_principal)) -> dict:
    new_pw = body.new_password or ("Pa" + pysecrets.token_urlsafe(9) + "7")
    problems = passwords.password_problems(new_pw)
    if problems:
        raise ApiError(422, "WEAK_PASSWORD", "The password needs " + ", ".join(problems) + ".")
    h = passwords.hash_password(new_pw)

    def _w(c):
        r = c.execute(text("""UPDATE app.users SET password_hash = :h, token_version = token_version + 1, failed_logins = 0,
                              locked_until = NULL WHERE id = :id RETURNING username"""), {"h": h, "id": user_id}).first()
        if r is None:
            raise ApiError(404, "NOT_FOUND", "User not found.")
        audit.record(c, "user_change", **audit.principal_fields(admin), req=request_info(request),
                     detail={"op": "reset_password", "target": r.username})
        return r

    db.write(_w)
    return {"ok": True, "temporary_password": None if body.new_password else new_pw}


def _audit_rows(admin: Principal, before_id: int | None, limit: int, action: str | None, username: str | None,
                ts_from: datetime | None, ts_to: datetime | None) -> list[dict]:
    with db.scoped(admin.id) as c:
        rows = c.execute(text("SELECT * FROM app.admin_audit(:b, :l, :a, :u, :f, :t)"),
                         {"b": before_id, "l": limit, "a": action, "u": username, "f": ts_from, "t": ts_to}).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        d["ts"] = d["ts"].isoformat()
        d["ip"] = str(d["ip"]) if d["ip"] is not None else None
        d["request_id"] = str(d["request_id"]) if d["request_id"] else None
        out.append(d)
    return out


@router.get("/audit")
def audit_log(admin: Principal = Depends(get_principal), before_id: int | None = None, limit: int = Query(100, ge=1, le=500),
              action: str | None = None, username: str | None = None, ts_from: datetime | None = None,
              ts_to: datetime | None = None) -> dict:
    audit.flush()
    rows = _audit_rows(admin, before_id, limit, action, username, ts_from, ts_to)
    with db.scoped(admin.id) as c:
        summary = [dict(r) for r in c.execute(text("SELECT * FROM app.admin_audit_summary(24)")).mappings().all()]
    return {"rows": rows, "next_before_id": rows[-1]["id"] if len(rows) == limit else None, "summary_24h": summary}


@router.get("/audit/export")
def audit_export(request: Request, admin: Principal = Depends(get_principal), action: str | None = None,
                 username: str | None = None) -> StreamingResponse:
    rows: list[dict] = []
    before = None
    while len(rows) < 10_000:
        page = _audit_rows(admin, before, 1000, action, username, None, None)
        rows += page
        if len(page) < 1000:
            break
        before = page[-1]["id"]
    audit.record_now("export", **audit.principal_fields(admin), req=request_info(request), detail={"kind": "audit", "rows": len(rows)})
    buf = io.StringIO()
    w = csv.writer(buf)
    cols = ["id", "ts", "username", "role", "action", "scope_key", "ip", "replica", "detail", "flags"]
    w.writerow(cols)
    for r in rows:
        w.writerow([json.dumps(r[c]) if c in ("detail", "flags") else ("'" + str(r[c]) if str(r[c] or "")[:1] in "=+-@" else r[c]) for c in cols])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="panorama_audit.csv"'})


@router.get("/roles")
def roles() -> dict:
    examples = {"admin": (None, None), "executive": (None, None), "regional_manager": ("Asia", None),
                "category_manager": (None, "Electronics"), "analyst": (None, None), "operations": (None, None)}
    out = []
    for role in vocab.ROLES:
        sc: Scope = build_scope(role, *examples[role])
        out.append({
            "role": role, "label": ROLE_LABELS[role],
            "rows": "Own region only" if role == "regional_manager" else "Own category only" if role == "category_manager" else "All",
            "financial": sc.financial, "customer_id": "Real" if sc.pii_raw else "Pseudonym (C-…)",
            "company_totals": sc.company_totals, "pages": list(sc.pages), "capabilities": sorted(sc.capabilities),
            "scope_key_example": sc.scope_key, "landing": sc.landing,
        })
    return {"roles": out}


@router.get("/system")
async def system(admin: Principal = Depends(get_principal)) -> dict:
    s = get_settings()

    def _db_part() -> dict:
        with db.unscoped() as c:
            meta = c.execute(text("SELECT data_version, dataset, row_count, min_date, max_date, loaded_at FROM sales.meta WHERE id = 1")).mappings().first()
            rag = c.execute(text("SELECT corpus_hash, version, doc_count, built_at FROM rag.manifest WHERE id = 1")).mappings().first()
            workers = c.execute(text("SELECT * FROM app.worker_stats WHERE updated_at > now() - interval '2 minutes' ORDER BY replica, process_id")).mappings().all()
            conns = c.execute(text("""SELECT usename, application_name, state, count(*) AS n FROM pg_stat_activity
                                      WHERE datname = current_database() GROUP BY 1, 2, 3 ORDER BY 4 DESC""")).mappings().all()
            try:
                slow = c.execute(text("""SELECT left(regexp_replace(query, '\\s+', ' ', 'g'), 160) AS query, calls,
                                         round(mean_exec_time::numeric, 2) AS mean_ms, round(total_exec_time::numeric, 1) AS total_ms
                                         FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 10""")).mappings().all()
            except Exception:
                slow = []
            stats = c.execute(text("SELECT xact_commit, xact_rollback, numbackends FROM pg_stat_database WHERE datname = current_database()")).mappings().first()
        return {"meta": dict(meta) if meta else None, "rag": dict(rag) if rag else None, "workers": [dict(w) for w in workers],
                "connections": [dict(r) for r in conns], "slow_queries": [dict(r) for r in slow], "db_stats": dict(stats) if stats else None}

    part = await db.run_sync(_db_part)
    meta = part["meta"]
    scope_files = []
    if meta:
        try:
            m = load_manifest(s.scopes_dir, meta["data_version"])
            scope_files = [{"key": k, "rows": e["rows"], "bytes": e["bytes"], "rollup_rows": e["rollup_rows"]} for k, e in m["files"].items()]
        except Exception:
            scope_files = []
    gateway = None
    try:
        from app.chat import gateway_client

        gateway = await gateway_client.status()
    except Exception as exc:  # gateway down or not built
        gateway = {"available": False, "error": str(exc)[:200]}

    def _jsonable(v):
        if isinstance(v, dict):
            return {k: _jsonable(x) for k, x in v.items()}
        if isinstance(v, list):
            return [_jsonable(x) for x in v]
        if hasattr(v, "isoformat"):
            return v.isoformat()
        if hasattr(v, "as_integer_ratio") and not isinstance(v, (int, float, bool)):
            return float(v)
        return v

    return _jsonable({
        "replica": s.replica, "build_id": s.build_id, "dataset": meta, "rag": part["rag"], "scope_files": scope_files,
        "open_scope_files": get_cache().stats(), "workers": part["workers"],
        "audit_dropped_total": sum(w.get("audit_dropped", 0) or 0 for w in part["workers"]),
        "db_connections": part["connections"], "slow_queries": part["slow_queries"], "db_stats": part["db_stats"],
        "gateway": gateway, "settings": {"api_workers": s.api_workers, "llm_model": s.llm_model, "llm_parallel": s.llm_parallel,
                                         "llm_max_wait_s": s.llm_max_wait_s, "dataset": s.dataset, "demo_mode": s.demo_mode},
    })


@router.get("/ai-quality")
def ai_quality(admin: Principal = Depends(get_principal), days: int = Query(30, ge=1, le=365)) -> dict:
    with db.scoped(admin.id) as c:
        modes = [dict(r) for r in c.execute(text("SELECT * FROM app.admin_ai_quality(:d)"), {"d": days}).mappings().all()]
        fb = c.execute(text("SELECT * FROM app.admin_feedback(50)")).mappings().all()
    feedback = []
    for r in fb:
        d = dict(r)
        d["created_at"] = d["created_at"].isoformat()
        feedback.append(d)
    report = None
    for p in (Path("/app/eval/reports/latest.json"), Path(__file__).resolve().parents[2] / "eval/reports/latest.json"):
        if p.exists():
            try:
                report = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                report = None
            break
    return {"modes": modes, "feedback": feedback, "eval_report": report}
