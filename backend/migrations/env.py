"""Alembic environment.

Only init (and the test fixtures) run migrations. They connect as the postgres superuser and run
SET ROLE panorama_owner first, so panorama_owner owns every object. A caller can pass an open
connection in config.attributes["connection"].
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool, text

from app.db.models import HNSW_INDEX_NAME, metadata

config = context.config
if config.config_file_name is not None and not config.attributes.get("connection"):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

SCHEMAS = {"app", "sales", "rag"}


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return name in SCHEMAS
    return True


def include_object(obj, name, type_, reflected, compare_to):
    # The HNSW index exists only above RAG_HNSW_THRESHOLD; init creates it.
    if type_ == "index" and name == HNSW_INDEX_NAME:
        return False
    return True


def _configure(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=metadata,
        include_schemas=True,
        include_name=include_name,
        include_object=include_object,
        compare_type=True,
        transaction_per_migration=False,
    )


def run_migrations_online() -> None:
    conn = config.attributes.get("connection")
    if conn is not None:
        _configure(conn)
        with context.begin_transaction():
            context.run_migrations()
        return

    from app.db.engine import superuser_url

    engine = create_engine(superuser_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        connection.execute(text("SET ROLE panorama_owner"))
        connection.commit()
        _configure(connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("offline mode is not supported")
run_migrations_online()
