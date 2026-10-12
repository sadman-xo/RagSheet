"""One-shot init job. Runs at each `docker compose up`; each step is skipped if nothing changed.

1. Wait for PostgreSQL (30 s retry).
2. As postgres: roles, extensions, database owner, REVOKE TEMPORARY, pg_read_all_stats, app password.
3. SET ROLE panorama_owner: Alembic upgrade head.
4. Dataset: sample, or generate the 1M dataset if it is missing; checks and load (skip if data_version is the same).
5. Scope files with rollups (skip if the manifest is current).
6. Seed users (+ LOADTEST_USERS synthetic users with DEMO_MODE).
7. Retention.
8. RAG documents (skip if corpus_hash is the same).
9. ANALYZE.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy import create_engine, pool, text

from app.config import Settings, get_settings, read_secret

BACKEND_DIR = Path(__file__).resolve().parent.parent
OWNER = "panorama_owner"
APP = "panorama_app"


def log(msg: str) -> None:
    print(f"init: {msg}", flush=True)


def superuser_conninfo(s: Settings, dbname: str | None = None) -> dict:
    return {
        "host": s.db_host, "port": s.db_port, "dbname": dbname or s.db_name, "user": "postgres",
        "password": read_secret(s.secrets_db_dir, "postgres_password"), "connect_timeout": 3,
        "application_name": "panorama-init",
    }


def wait_for_postgres(s: Settings, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            with psycopg.connect(**superuser_conninfo(s), autocommit=True) as conn:
                conn.execute("SELECT 1")
                return
        except psycopg.OperationalError as exc:
            if time.monotonic() > deadline:
                raise RuntimeError(f"PostgreSQL is not reachable: {exc}") from exc
            time.sleep(1)


def setup_roles(conn: psycopg.Connection, app_password: str, dbname: str) -> None:
    """Cluster roles and database settings (as postgres, autocommit)."""
    conn.execute(f"""
        DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{OWNER}') THEN CREATE ROLE {OWNER} NOLOGIN; END IF;
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP}') THEN CREATE ROLE {APP} LOGIN; END IF;
        END $$""")
    conn.execute(f"ALTER ROLE {OWNER} WITH NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION")
    # Utility statements cannot take bind parameters: the password is a quoted literal.
    conn.execute(sql.SQL("ALTER ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}")
                 .format(sql.Identifier(APP), sql.Literal(app_password)))
    conn.execute(f"ALTER ROLE {APP} SET statement_timeout = '5s'")
    conn.execute(f"ALTER ROLE {APP} SET lock_timeout = '2s'")
    conn.execute(f"ALTER ROLE {APP} SET idle_in_transaction_session_timeout = '10s'")
    conn.execute(f"GRANT pg_read_all_stats TO {APP}")
    setup_database(conn, dbname)


def setup_database(conn: psycopg.Connection, dbname: str) -> None:
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")
    conn.execute(sql.SQL("ALTER DATABASE {} OWNER TO {}").format(sql.Identifier(dbname), sql.Identifier(OWNER)))
    conn.execute(sql.SQL("REVOKE TEMPORARY ON DATABASE {} FROM PUBLIC").format(sql.Identifier(dbname)))
    conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")


def run_migrations(s: Settings, dbname: str | None = None, revision: str = "head") -> None:
    from alembic import command
    from alembic.config import Config

    from app.db.engine import superuser_url

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    engine = create_engine(superuser_url(dbname), poolclass=pool.NullPool)
    try:
        with engine.connect() as c:
            c.execute(text(f"SET ROLE {OWNER}"))
            c.commit()
            cfg.attributes["connection"] = c
            command.upgrade(cfg, revision)
            c.commit()
    finally:
        engine.dispose()


def owner_connection(s: Settings, dbname: str | None = None) -> psycopg.Connection:
    conn = psycopg.connect(**superuser_conninfo(s, dbname), autocommit=True)
    conn.execute(f"SET ROLE {OWNER}")
    return conn


def step_dataset(conn: psycopg.Connection, s: Settings) -> str:
    from app.data import generator, loader

    path = s.dataset_path
    if s.dataset != "sample":
        generator.ensure_dataset(s.data_raw_dir / s.sample_file, path, s.dataset_rows_target)
    if not path.exists():
        raise RuntimeError(f"dataset file {path} is missing")
    version = loader.file_version(path)
    if loader.current_version(conn) == version:
        log(f"dataset {s.dataset} (data_version {version}) is already loaded; skip")
        return version
    ds = loader.read_dataset(path, s.dataset)
    pii_key = read_secret(s.secrets_app_dir, "pii_hmac_key").encode()
    loader.load_to_postgres(conn, ds, pii_key)
    return version


def step_scopes(conn: psycopg.Connection, s: Settings, data_version: str) -> None:
    from app.data import scopestore

    s.scopes_dir.mkdir(parents=True, exist_ok=True)
    scopestore.build_all(conn, data_version, s.scopes_dir, threads=os.cpu_count())


def step_users(conn: psycopg.Connection, s: Settings) -> None:
    from app.db import seed

    made = seed.seed_demo_users(conn)
    log(f"seeded {made} demo users")
    if s.loadtest_users > 0:
        if not s.demo_mode:
            log("LOADTEST_USERS is ignored because DEMO_MODE is false")
        else:
            n = seed.seed_loadtest_users(conn, s.loadtest_users)
            log(f"seeded {n} load-test users")


def step_retention(conn: psycopg.Connection, s: Settings) -> None:
    from app.db.maintenance import run_retention

    log(f"retention: {run_retention(conn, s)}")


def step_rag(conn: psycopg.Connection, s: Settings, data_version: str) -> None:
    try:
        from app.rag import indexer
    except ImportError:  # pragma: no cover - before M7
        log("RAG indexer is not available; skip")
        return
    indexer.build_if_needed(conn, s, data_version)


def main() -> int:
    s = get_settings()
    t0 = time.monotonic()
    try:
        wait_for_postgres(s)
        app_pw = read_secret(s.secrets_app_dir, "app_db_password")
        with psycopg.connect(**superuser_conninfo(s), autocommit=True) as conn:
            setup_roles(conn, app_pw, s.db_name)
        log("roles and extensions ready")
        run_migrations(s)
        log("migrations at head")
        with owner_connection(s) as conn:
            version = step_dataset(conn, s)
            step_scopes(conn, s, version)
            step_users(conn, s)
            step_retention(conn, s)
            step_rag(conn, s, version)
            conn.execute("ANALYZE app.users")
    except Exception as exc:  # fail with a clear log line; the api does not start
        log(f"FAILED: {type(exc).__name__}: {exc}")
        raise
    log(f"done in {time.monotonic() - t0:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
