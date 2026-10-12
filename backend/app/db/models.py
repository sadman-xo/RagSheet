"""Table definitions (SQLAlchemy Core). Alembic creates them; `alembic check` compares them with the database.

The app uses Core statements only (no ORM objects leave a transaction).
"""

from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB, TSVECTOR, UUID

from app.data import vocab

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)

EMBED_DIM = 384
HNSW_INDEX_NAME = "ix_documents_embedding_hnsw"


def _in(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IN ({vocab.sql_in_list(values)})"


# ---------------------------------------------------------------------------
# app schema
# ---------------------------------------------------------------------------
users = Table(
    "users", metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("username", Text, nullable=False),
    Column("display_name", Text, nullable=False),
    Column("password_hash", Text, nullable=False),
    Column("role", Text, nullable=False),
    Column("region", Text, nullable=True),
    Column("category", Text, nullable=True),
    Column("is_active", Boolean, nullable=False, server_default=text("true")),
    Column("is_synthetic", Boolean, nullable=False, server_default=text("false")),
    Column("token_version", Integer, nullable=False, server_default=text("1")),
    Column("failed_logins", Integer, nullable=False, server_default=text("0")),
    Column("last_failed_at", DateTime(timezone=True), nullable=True),
    Column("locked_until", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("last_login_at", DateTime(timezone=True), nullable=True),
    UniqueConstraint("username"),
    CheckConstraint(_in("role", vocab.ROLES), name="role_valid"),
    CheckConstraint("(role = 'regional_manager') = (region IS NOT NULL)", name="region_iff_rm"),
    CheckConstraint("(role = 'category_manager') = (category IS NOT NULL)", name="category_iff_cm"),
    CheckConstraint(f"region IS NULL OR {_in('region', vocab.REGIONS)}", name="region_valid"),
    CheckConstraint(f"category IS NULL OR {_in('category', vocab.CATEGORIES)}", name="category_valid"),
    CheckConstraint("failed_logins >= 0", name="failed_logins_nonneg"),
    schema="app",
)

audit_log = Table(
    "audit_log", metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("ts", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("user_id", BigInteger, nullable=True),
    Column("username", Text, nullable=True),
    Column("role", Text, nullable=True),
    Column("action", Text, nullable=False),
    Column("scope_key", Text, nullable=True),
    Column("ip", INET, nullable=True),
    Column("request_id", UUID(as_uuid=False), nullable=True),
    Column("replica", Text, nullable=True),
    Column("detail", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("flags", ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")),
    Index(None, "ts"),
    Index(None, "user_id", "ts"),
    Index(None, "action", "ts"),
    schema="app",
)

chat_sessions = Table(
    "chat_sessions", metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("user_id", BigInteger, ForeignKey("app.users.id"), nullable=False),
    Column("title", Text, nullable=False),
    Column("scope_fp", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("id", "user_id"),
    Index(None, "user_id", "updated_at"),
    schema="app",
)

chat_messages = Table(
    "chat_messages", metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("session_id", BigInteger, nullable=False),
    Column("user_id", BigInteger, nullable=False),
    Column("role", Text, nullable=False),
    Column("content", Text, nullable=False),
    Column("plan", JSONB, nullable=True),
    Column("sources", JSONB, nullable=True),
    Column("verification", JSONB, nullable=True),
    Column("mode", Text, nullable=True),
    Column("timings", JSONB, nullable=True),
    Column("flags", ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")),
    Column("turn_id", UUID(as_uuid=False), nullable=False),
    Column("parent_message_id", BigInteger, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    ForeignKeyConstraint(["session_id", "user_id"], ["app.chat_sessions.id", "app.chat_sessions.user_id"]),
    UniqueConstraint("user_id", "turn_id", "role"),
    UniqueConstraint("id", "user_id"),
    CheckConstraint("role IN ('user', 'assistant')", name="role_valid"),
    Index(None, "session_id", "created_at"),
    schema="app",
)

feedback = Table(
    "feedback", metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("message_id", BigInteger, nullable=False),
    Column("user_id", BigInteger, nullable=False),
    Column("rating", SmallInteger, nullable=False),
    Column("comment", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    ForeignKeyConstraint(["message_id", "user_id"], ["app.chat_messages.id", "app.chat_messages.user_id"]),
    UniqueConstraint("message_id", "user_id"),
    CheckConstraint("rating IN (-1, 1)", name="rating_valid"),
    schema="app",
)

worker_stats = Table(
    "worker_stats", metadata,
    Column("process_id", Text, primary_key=True),
    Column("replica", Text, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("requests", BigInteger, nullable=False, server_default=text("0")),
    Column("write_p95_ms", Float, nullable=True),
    Column("audit_dropped", BigInteger, nullable=False, server_default=text("0")),
    Column("audit_written", BigInteger, nullable=False, server_default=text("0")),
    Column("cache_hits", BigInteger, nullable=False, server_default=text("0")),
    Column("cache_misses", BigInteger, nullable=False, server_default=text("0")),
    Column("detail", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    schema="app",
)

# ---------------------------------------------------------------------------
# sales schema (star schema)
# ---------------------------------------------------------------------------
dim_date = Table(
    "dim_date", metadata,
    Column("date_key", Integer, primary_key=True, autoincrement=False),
    Column("order_date", Date, nullable=False),
    Column("year", SmallInteger, nullable=False),
    Column("quarter", SmallInteger, nullable=False),
    Column("month", SmallInteger, nullable=False),
    Column("year_month", CHAR(7), nullable=False),
    Column("season", Text, nullable=False),
    Column("day_of_week", Text, nullable=False),
    UniqueConstraint("order_date"),
    CheckConstraint("quarter BETWEEN 1 AND 4", name="quarter_valid"),
    CheckConstraint("month BETWEEN 1 AND 12", name="month_valid"),
    CheckConstraint(_in("season", vocab.SEASONS), name="season_valid"),
    schema="sales",
)

dim_geography = Table(
    "dim_geography", metadata,
    Column("geo_id", SmallInteger, primary_key=True, autoincrement=False),
    Column("country", Text, nullable=False),
    Column("region", Text, nullable=False),
    UniqueConstraint("country"),
    CheckConstraint(_in("region", vocab.REGIONS), name="region_valid"),
    schema="sales",
)

dim_product = Table(
    "dim_product", metadata,
    Column("product_id", SmallInteger, primary_key=True, autoincrement=False),
    Column("product_name", Text, nullable=False),
    Column("sub_category", Text, nullable=False),
    Column("category", Text, nullable=False),
    UniqueConstraint("product_name"),
    CheckConstraint(_in("category", vocab.CATEGORIES), name="category_valid"),
    schema="sales",
)

dim_customer = Table(
    "dim_customer", metadata,
    Column("customer_sk", Integer, primary_key=True, autoincrement=False),
    Column("customer_id", String(16), nullable=False),
    Column("customer_key", CHAR(10), nullable=False),
    UniqueConstraint("customer_id"),
    UniqueConstraint("customer_key"),
    schema="sales",
)

fact_orders = Table(
    "fact_orders", metadata,
    Column("order_id", String(12), primary_key=True),
    Column("date_key", Integer, ForeignKey("sales.dim_date.date_key"), nullable=False),
    Column("geo_id", SmallInteger, ForeignKey("sales.dim_geography.geo_id"), nullable=False),
    Column("product_id", SmallInteger, ForeignKey("sales.dim_product.product_id"), nullable=False),
    Column("customer_sk", Integer, ForeignKey("sales.dim_customer.customer_sk"), nullable=False),
    Column("customer_segment", Text, nullable=False),
    Column("customer_gender", Text, nullable=False),
    Column("unit_price", Numeric(10, 2), nullable=False),
    Column("quantity", SmallInteger, nullable=False),
    Column("discount", Numeric(3, 2), nullable=False),
    Column("revenue", Numeric(12, 2), nullable=False),
    Column("cost", Numeric(12, 2), nullable=False),
    Column("profit", Numeric(12, 2), nullable=False),
    Column("profit_margin_pct", Numeric(6, 2), nullable=False),
    Column("shipping_cost", Numeric(8, 2), nullable=False),
    Column("shipping_method", Text, nullable=False),
    Column("shipping_days", SmallInteger, nullable=False),
    Column("payment_method", Text, nullable=False),
    Column("order_status", Text, nullable=False),
    CheckConstraint(_in("order_status", vocab.STATUSES), name="status_valid"),
    CheckConstraint(_in("customer_segment", vocab.SEGMENTS), name="segment_valid"),
    CheckConstraint(_in("customer_gender", vocab.GENDERS), name="gender_valid"),
    CheckConstraint(_in("shipping_method", vocab.SHIPPING_METHODS), name="shipping_method_valid"),
    CheckConstraint(_in("payment_method", vocab.PAYMENT_METHODS), name="payment_method_valid"),
    CheckConstraint("quantity BETWEEN 1 AND 100", name="quantity_range"),
    CheckConstraint("discount BETWEEN 0 AND 0.9", name="discount_range"),
    CheckConstraint("unit_price > 0", name="unit_price_positive"),
    CheckConstraint("shipping_cost >= 0", name="shipping_cost_nonneg"),
    CheckConstraint("shipping_days BETWEEN 0 AND 365", name="shipping_days_range"),
    CheckConstraint("abs(revenue - round(unit_price * quantity * (1 - discount), 2)) <= 0.01", name="revenue_formula"),
    CheckConstraint("abs(profit - (revenue - cost)) <= 0.01", name="profit_formula"),
    Index(None, "date_key", postgresql_using="brin"),
    Index(None, "geo_id"),
    Index(None, "product_id"),
    Index(None, "customer_sk"),
    schema="sales",
)

meta = Table(
    "meta", metadata,
    Column("id", SmallInteger, primary_key=True, autoincrement=False),
    Column("data_version", Text, nullable=False),
    Column("dataset", Text, nullable=False),
    Column("row_count", BigInteger, nullable=False),
    Column("min_date", Date, nullable=False),
    Column("max_date", Date, nullable=False),
    Column("loaded_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("id = 1", name="single_row"),
    schema="sales",
)

# ---------------------------------------------------------------------------
# rag schema
# ---------------------------------------------------------------------------
documents = Table(
    "documents", metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("doc_key", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("body", Text, nullable=False),
    Column("embed_text", Text, nullable=False),
    Column("coverage_region", Text, nullable=True),
    Column("coverage_category", Text, nullable=True),
    Column("is_financial", Boolean, nullable=False, server_default=text("false")),
    Column("spec", JSONB, nullable=True),
    Column("deep_link", Text, nullable=True),
    Column("meta", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("embedding", Vector(EMBED_DIM), nullable=False),
    Column("tsv", TSVECTOR, Computed("to_tsvector('english'::regconfig, title || ' ' || embed_text)", persisted=True)),
    UniqueConstraint("doc_key"),
    CheckConstraint("kind IN ('knowledge', 'insight', 'entity', 'summary')", name="kind_valid"),
    Index(None, "tsv", postgresql_using="gin"),
    Index(None, "kind"),
    schema="rag",
)

manifest = Table(
    "manifest", metadata,
    Column("id", SmallInteger, primary_key=True, autoincrement=False),
    Column("corpus_hash", Text, nullable=False),
    Column("version", Integer, nullable=False),
    Column("doc_count", Integer, nullable=False),
    Column("built_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("id = 1", name="single_row"),
    schema="rag",
)

# Creation order for the initial migration
CREATE_ORDER = (
    users, audit_log, chat_sessions, chat_messages, feedback, worker_stats,
    dim_date, dim_geography, dim_product, dim_customer, fact_orders, meta,
    documents, manifest,
)
