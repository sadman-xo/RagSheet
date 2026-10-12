"""Test fixtures.

A session fixture, as postgres, builds the template database panorama_test_tmpl one time: extensions,
migrations under SET ROLE panorama_owner, the sample CSV load, temporary scope files, demo users, and a
RAG fixture corpus with a deterministic fake embedder. Each pytest-xdist worker then creates its own
database from the template. App and security tests connect as panorama_app.
"""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path

import psycopg
import pytest

from app import init as initmod
from app.config import get_settings, read_secret
from app.data import generator, loader, scopestore
from app.data.scoped import ScopeFileCache, set_cache
from app.db import engine as dbengine
from app.db import seed

TEMPLATE = "panorama_test_tmpl"
TEMPLATE_100K = "panorama_test_100k"


def worker_id() -> str:
    return os.environ.get("PYTEST_XDIST_WORKER", "gw0")


def admin_conn() -> psycopg.Connection:
    return psycopg.connect(**initmod.superuser_conninfo(get_settings(), "postgres"), autocommit=True)


def _create_db(name: str, template: str | None = None) -> None:
    with admin_conn() as c:
        c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        if template:
            c.execute(f'CREATE DATABASE "{name}" TEMPLATE "{template}"')
        else:
            c.execute(f'CREATE DATABASE "{name}"')


def build_template(name: str, csv_path: Path, dataset_name: str, scopes_dir: Path, rag: bool = True) -> str:
    s = get_settings()
    _create_db(name)
    with psycopg.connect(**initmod.superuser_conninfo(s, name), autocommit=True) as c:
        initmod.setup_roles(c, read_secret(s.secrets_app_dir, "app_db_password"), name)
    initmod.run_migrations(s, dbname=name)
    pii_key = read_secret(s.secrets_app_dir, "pii_hmac_key").encode()
    with initmod.owner_connection(s, name) as c:
        ds = loader.read_dataset(csv_path, dataset_name)
        loader.load_to_postgres(c, ds, pii_key)
        scopestore.build_all(c, ds.data_version, scopes_dir, threads=4)
        seed.seed_demo_users(c)
        if rag:
            try:
                from tests.fakes import build_fixture_corpus
            except ImportError:  # pragma: no cover
                build_fixture_corpus = None
            if build_fixture_corpus is not None:
                build_fixture_corpus(c, ds.data_version)
    return ds.data_version


class _FileLock:
    def __init__(self, path: Path):
        self.path = path

    def __enter__(self):
        self.fh = open(self.path, "w")
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self.fh, fcntl.LOCK_UN)
        self.fh.close()


@pytest.fixture(scope="session")
def shared_dir(tmp_path_factory) -> Path:
    # The parent of the per-worker base temp is shared by all xdist workers of one run.
    root = tmp_path_factory.getbasetemp()
    if os.environ.get("PYTEST_XDIST_WORKER"):
        root = root.parent
    d = root / "shared"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest.fixture(scope="session")
def sample_csv(settings) -> Path:
    return settings.data_raw_dir / settings.sample_file


@pytest.fixture(scope="session")
def template_db(shared_dir, sample_csv) -> dict:
    """Build the sample template database and scope files one time for all workers."""
    info_file = shared_dir / "template.json"
    with _FileLock(shared_dir / "template.lock"):
        if not info_file.exists():
            scopes_dir = shared_dir / "scopes"
            dv = build_template(TEMPLATE, sample_csv, "sample", scopes_dir)
            info_file.write_text(json.dumps({"data_version": dv, "scopes_dir": str(scopes_dir)}))
    return json.loads(info_file.read_text())


@pytest.fixture(scope="session")
def test_db(template_db) -> str:
    """This worker's database (a copy of the template) and the app engine connected to it as panorama_app."""
    name = f"panorama_test_{worker_id()}"
    _create_db(name, TEMPLATE)
    # A copy does not keep the database owner and privileges: set them again.
    with psycopg.connect(**initmod.superuser_conninfo(get_settings(), name), autocommit=True) as c:
        initmod.setup_database(c, name)
    eng = dbengine.make_engine(dbengine.app_url(name), pool_size=10, max_overflow=10)
    dbengine.set_engine(eng)
    set_cache(ScopeFileCache(Path(template_db["scopes_dir"])))
    yield name
    eng.dispose()
    dbengine.set_engine(None)
    with admin_conn() as c:
        c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture(scope="session")
def data_version(template_db) -> str:
    return template_db["data_version"]


@pytest.fixture(scope="session")
def scope_cache(template_db) -> ScopeFileCache:
    return ScopeFileCache(Path(template_db["scopes_dir"]))


@pytest.fixture(scope="session")
def owner_db(test_db):
    """psycopg connection as panorama_owner on this worker's database."""
    with initmod.owner_connection(get_settings(), test_db) as c:
        yield c


@pytest.fixture(scope="session")
def superuser_db(test_db):
    with psycopg.connect(**initmod.superuser_conninfo(get_settings(), test_db), autocommit=True) as c:
        yield c


def app_connect(dbname: str) -> psycopg.Connection:
    s = get_settings()
    return psycopg.connect(host=s.db_host, port=s.db_port, dbname=dbname, user=s.db_app_user,
                           password=read_secret(s.secrets_app_dir, "app_db_password"), autocommit=False)


@pytest.fixture()
def app_db(test_db):
    """A fresh psycopg connection as panorama_app (no autocommit)."""
    c = app_connect(test_db)
    yield c
    c.rollback()
    c.close()


@pytest.fixture(scope="session")
def user_ids(owner_db) -> dict[str, int]:
    return {r[0]: r[1] for r in owner_db.execute("SELECT username, id FROM app.users").fetchall()}


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------
ORIGIN = "http://localhost:8080"
DEMO_PASSWORD = "Demo@2024"
DEMO_USERS = ["admin", "exec", "rm.namerica", "rm.europe", "rm.asia", "rm.mideast", "cm.electronics", "cm.clothing",
              "cm.home", "cm.books", "cm.beauty", "analyst", "ops"]


@pytest.fixture(scope="session")
def client(test_db):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.ratelimit import login_limiter

    login_limiter.reset()
    with TestClient(app, headers={"Origin": ORIGIN}) as c:
        yield c


@pytest.fixture(scope="session")
def tokens(client) -> dict[str, str]:
    out = {}
    for u in DEMO_USERS:
        r = client.post("/api/auth/login", json={"username": u, "password": DEMO_PASSWORD, "want_token": True})
        assert r.status_code == 200, r.text
        out[u] = r.json()["access_token"]
    client.cookies.clear()
    return out


def bearer(tokens: dict, user: str) -> dict:
    return {"Authorization": f"Bearer {tokens[user]}"}


def audit_rows(owner_db, action: str | None = None, username: str | None = None, since_id: int = 0) -> list[dict]:
    from app import audit

    audit.flush()
    sql = "SELECT id, action, username, role, scope_key, detail, flags FROM app.audit_log WHERE id > %s"
    params: list = [since_id]
    if action:
        sql += " AND action = %s"
        params.append(action)
    if username:
        sql += " AND username = %s"
        params.append(username)
    cur = owner_db.execute(sql + " ORDER BY id", params)
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def max_audit_id(owner_db) -> int:
    return owner_db.execute("SELECT coalesce(max(id), 0) FROM app.audit_log").fetchone()[0]


# ---------------------------------------------------------------------------
# 100k generated dataset (oracle grid at a larger size)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def dataset_100k(shared_dir, sample_csv) -> dict:
    info_file = shared_dir / "t100k.json"
    with _FileLock(shared_dir / "t100k.lock"):
        if not info_file.exists():
            csv_path = shared_dir / "generated_100000.csv"
            generator.write_csv(generator.generate(sample_csv, 100_000), csv_path)
            scopes_dir = shared_dir / "scopes100k"
            dv = build_template(TEMPLATE_100K, csv_path, "100k", scopes_dir, rag=False)
            info_file.write_text(json.dumps({"data_version": dv, "scopes_dir": str(scopes_dir), "csv": str(csv_path)}))
    return json.loads(info_file.read_text())
