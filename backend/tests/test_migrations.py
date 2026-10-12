from __future__ import annotations

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, pool, text

from app import init as initmod
from app.config import get_settings
from app.db import models
from app.db.engine import superuser_url
from tests.conftest import _create_db, admin_conn

DB = "panorama_test_migr"


def _cfg() -> Config:
    cfg = Config(str(initmod.BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(initmod.BACKEND_DIR / "migrations"))
    return cfg


def _with_owner(fn):
    eng = create_engine(superuser_url(DB), poolclass=pool.NullPool)
    try:
        with eng.connect() as c:
            c.execute(text("SET ROLE panorama_owner"))
            c.commit()
            cfg = _cfg()
            cfg.attributes["connection"] = c
            fn(cfg)
            c.commit()
    finally:
        eng.dispose()


def _schemas() -> set[str]:
    with psycopg.connect(**initmod.superuser_conninfo(get_settings(), DB)) as c:
        return {r[0] for r in c.execute("SELECT nspname FROM pg_namespace WHERE nspname IN ('app','sales','rag')").fetchall()}


@pytest.fixture()
def empty_db(test_db):
    _create_db(DB)
    with psycopg.connect(**initmod.superuser_conninfo(get_settings(), DB), autocommit=True) as c:
        initmod.setup_database(c, DB)
    yield DB
    with admin_conn() as c:
        c.execute(f'DROP DATABASE IF EXISTS "{DB}" WITH (FORCE)')


def test_upgrade_check_downgrade(empty_db):
    _with_owner(lambda cfg: command.upgrade(cfg, "head"))
    assert _schemas() == {"app", "sales", "rag"}
    _with_owner(lambda cfg: command.check(cfg))  # raises if the models and the database differ
    _with_owner(lambda cfg: command.downgrade(cfg, "-1"))  # one step: the RAG policy change
    assert _schemas() == {"app", "sales", "rag"}
    _with_owner(lambda cfg: command.downgrade(cfg, "base"))
    assert _schemas() == set()
    _with_owner(lambda cfg: command.upgrade(cfg, "head"))
    assert _schemas() == {"app", "sales", "rag"}


def test_failed_migration_changes_nothing(empty_db, monkeypatch):
    broken = Table("broken", MetaData(), Column("id", Integer), schema="no_such_schema")
    monkeypatch.setattr(models, "CREATE_ORDER", tuple(models.CREATE_ORDER) + (broken,))
    with pytest.raises(Exception):
        _with_owner(lambda cfg: command.upgrade(cfg, "head"))
    assert _schemas() == set()
    with psycopg.connect(**initmod.superuser_conninfo(get_settings(), DB)) as c:
        assert c.execute("SELECT to_regclass('public.alembic_version')").fetchone()[0] is None
