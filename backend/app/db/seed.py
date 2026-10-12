"""Seed the demo users (and synthetic load-test users with DEMO_MODE). Run by init."""

from __future__ import annotations

from pathlib import Path

import psycopg
import yaml

from app.data import vocab
from app.security.passwords import hash_password

DEMO_FILE = Path(__file__).with_name("demo_users.yaml")


def demo_users() -> tuple[str, list[dict]]:
    data = yaml.safe_load(DEMO_FILE.read_text(encoding="utf-8"))
    return data["password"], data["users"]


def seed_demo_users(conn: psycopg.Connection) -> int:
    password, users = demo_users()
    existing = {r[0] for r in conn.execute("SELECT username FROM app.users").fetchall()}
    made = 0
    for u in users:
        if u["username"] in existing:
            continue
        conn.execute(
            """INSERT INTO app.users (username, display_name, password_hash, role, region, category)
               VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (username) DO NOTHING""",
            (u["username"], u["display_name"], hash_password(password), u["role"], u.get("region"), u.get("category")),
        )
        made += 1
    return made


def loadtest_scopes() -> list[dict]:
    """One template for each of the 13 demo scopes (admin, exec, 4 regions, 5 categories, analyst, ops)."""
    out = [{"tag": "admin", "role": "admin"}, {"tag": "exec", "role": "executive"},
           {"tag": "analyst", "role": "analyst"}, {"tag": "ops", "role": "operations"}]
    for r in vocab.REGIONS:
        out.append({"tag": "rm-" + r.lower().replace(" ", ""), "role": "regional_manager", "region": r})
    for c in vocab.CATEGORIES:
        out.append({"tag": "cm-" + c.lower().split()[0], "role": "category_manager", "category": c})
    return out


def seed_loadtest_users(conn: psycopg.Connection, per_scope_total: int) -> int:
    """LOADTEST_USERS synthetic users lt.<scope>.<n>, spread over the 13 scopes."""
    if per_scope_total <= 0:
        return 0
    password, _ = demo_users()
    pw_hash = hash_password(password)  # one hash for all synthetic users (same password)
    scopes = loadtest_scopes()
    made = 0
    rows = []
    for i in range(per_scope_total):
        s = scopes[i % len(scopes)]
        n = i // len(scopes) + 1
        rows.append((f"lt.{s['tag']}.{n}", f"Load test {s['tag']} {n}", pw_hash, s["role"], s.get("region"), s.get("category")))
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(
                """INSERT INTO app.users (username, display_name, password_hash, role, region, category, is_synthetic)
                   VALUES (%s, %s, %s, %s, %s, %s, true) ON CONFLICT (username) DO NOTHING""",
                row,
            )
            made += cur.rowcount
    return made
