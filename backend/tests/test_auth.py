from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.config import app_secret
from app.ratelimit import TokenBucket
from app.security import passwords, tokens
from tests.conftest import ORIGIN, audit_rows, max_audit_id


@pytest.fixture()
def temp_user(owner_db):
    name = f"t_{uuid.uuid4().hex[:8]}"
    h = passwords.hash_password("Right#Pass1")
    owner_db.execute("INSERT INTO app.users (username, display_name, password_hash, role) VALUES (%s, 'Temp', %s, 'executive')", (name, h))
    uid = owner_db.execute("SELECT id FROM app.users WHERE username = %s", (name,)).fetchone()[0]
    yield name, uid
    owner_db.execute("UPDATE app.users SET is_active = false WHERE id = %s", (uid,))


@pytest.fixture()
def no_rate_limit(monkeypatch):
    import app.api.auth as auth_mod

    monkeypatch.setattr(auth_mod, "login_limiter", TokenBucket(capacity=10_000, per_seconds=1))


def _login(client, user, pw, **kw):
    return client.post("/api/auth/login", json={"username": user, "password": pw, "want_token": True}, **kw)


def test_login_cookie_flags_and_me(client, temp_user):
    name, _ = temp_user
    r = _login(client, name, "Right#Pass1")
    assert r.status_code == 200
    sc = r.headers["set-cookie"].lower()
    assert "pa_session=" in sc and "httponly" in sc and "samesite=strict" in sc and "path=/" in sc
    me = client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["user"]["username"] == name
    client.post("/api/auth/logout")
    client.cookies.clear()
    assert client.get("/api/auth/me").status_code == 401


def test_bad_tokens(client, temp_user):
    name, uid = temp_user
    good = _login(client, name, "Right#Pass1").json()["access_token"]
    client.cookies.clear()
    now = datetime.now(timezone.utc)
    secret = app_secret("jwt_secret")
    expired = jwt.encode({"sub": str(uid), "ver": 1, "iat": now - timedelta(hours=9), "exp": now - timedelta(hours=1), "iss": "panorama"}, secret, algorithm="HS256")
    tampered = good[:-3] + ("AAA" if not good.endswith("AAA") else "BBB")
    header = jwt.utils.base64url_encode(b'{"alg":"none","typ":"JWT"}').decode()
    body = jwt.utils.base64url_encode(f'{{"sub":"{uid}","ver":1,"iss":"panorama","iat":{int(now.timestamp())},"exp":{int(now.timestamp()) + 3600}}}'.encode()).decode()
    none_alg = f"{header}.{body}."
    other_secret = jwt.encode({"sub": str(uid), "ver": 1, "iat": now, "exp": now + timedelta(hours=1), "iss": "panorama"}, "x" * 40, algorithm="HS256")
    for t in (expired, tampered, none_alg, other_secret, "garbage"):
        r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {t}"})
        assert r.status_code == 401, t
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {good}"}).status_code == 200


def test_token_version_change_ends_sessions(client, temp_user, owner_db):
    name, uid = temp_user
    tok = _login(client, name, "Right#Pass1").json()["access_token"]
    client.cookies.clear()
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get("/api/auth/me", headers=h).status_code == 200
    owner_db.execute("UPDATE app.users SET token_version = token_version + 1 WHERE id = %s", (uid,))
    assert client.get("/api/auth/me", headers=h).status_code == 401


def test_origin_check(client, temp_user):
    name, _ = temp_user
    r = client.post("/api/auth/login", json={"username": name, "password": "Right#Pass1"}, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403
    from fastapi.testclient import TestClient

    from app.main import app

    bare = TestClient(app)  # no Origin header, no Bearer token
    assert bare.post("/api/auth/login", json={"username": name, "password": "Right#Pass1"}).status_code == 403


def test_wrong_and_unknown_logins(client, temp_user, owner_db, no_rate_limit):
    name, _ = temp_user
    start = max_audit_id(owner_db)
    assert _login(client, name, "wrong").status_code == 401
    assert _login(client, "nobody_" + name, "wrong").status_code == 401
    rows = audit_rows(owner_db, "login_failed", since_id=start)
    assert {r["username"] for r in rows} >= {name, "nobody_" + name}


def test_parallel_wrong_logins_count_exactly_five(client, temp_user, owner_db, no_rate_limit):
    name, uid = temp_user
    before = passwords.bcrypt_calls()
    with ThreadPoolExecutor(max_workers=25) as ex:
        codes = list(ex.map(lambda _: _login(client, name, "wrong-password").status_code, range(50)))
    assert passwords.bcrypt_calls() - before == 5
    assert codes.count(401) == 5
    assert codes.count(429) == 45
    r = owner_db.execute("SELECT failed_logins, locked_until IS NOT NULL FROM app.users WHERE id = %s", (uid,)).fetchone()
    assert r == (5, True)
    # Locked: even the right password gets 429 without bcrypt
    b2 = passwords.bcrypt_calls()
    assert _login(client, name, "Right#Pass1").status_code == 429
    assert passwords.bcrypt_calls() == b2


def test_lock_expires(client, temp_user, owner_db, no_rate_limit, monkeypatch):
    name, uid = temp_user
    for _ in range(5):
        _login(client, name, "wrong")
    assert owner_db.execute("SELECT locked_until IS NOT NULL FROM app.users WHERE id = %s", (uid,)).fetchone()[0]
    later = datetime.now(timezone.utc) + timedelta(minutes=5, seconds=5)
    monkeypatch.setattr(tokens, "now", lambda: later)
    assert _login(client, name, "wrong").status_code == 401
    r = owner_db.execute("SELECT failed_logins, locked_until FROM app.users WHERE id = %s", (uid,)).fetchone()
    assert r == (1, None)
    assert _login(client, name, "Right#Pass1").status_code == 200
    assert owner_db.execute("SELECT failed_logins FROM app.users WHERE id = %s", (uid,)).fetchone()[0] == 0
    client.cookies.clear()


def test_password_change(client, temp_user):
    name, _ = temp_user
    tok = _login(client, name, "Right#Pass1").json()["access_token"]
    client.cookies.clear()
    h = {"Authorization": f"Bearer {tok}", "Origin": ORIGIN}
    assert client.post("/api/auth/password", json={"current_password": "nope", "new_password": "New#Pass22"}, headers=h).status_code == 400
    assert client.post("/api/auth/password", json={"current_password": "Right#Pass1", "new_password": "weak"}, headers=h).status_code == 422
    assert client.post("/api/auth/password", json={"current_password": "Right#Pass1", "new_password": "New#Pass22"}, headers=h).status_code == 200
    client.cookies.clear()
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"}).status_code == 401  # old token ended
    assert _login(client, name, "New#Pass22").status_code == 200
    client.cookies.clear()
