"""Settings for all Panorama processes (api, init, gateway, tests).

Plain settings come from the environment (.env through Docker Compose).
Secrets come from files in the secrets volumes. They are never in the environment.
"""

from __future__ import annotations

import json
import os
import socket
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _read_build_id() -> str:
    p = Path(__file__).resolve().parent.parent / "BUILD_ID"
    try:
        return p.read_text(encoding="utf-8").strip() or "dev"
    except OSError:
        return "dev"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    # Build and runtime identity (the image writes /app/BUILD_ID: a hash of the source)
    build_id: str = Field(default_factory=lambda: _read_build_id())
    demo_mode: bool = True

    # Dataset
    dataset: str = "sample"  # sample | 1m | custom size through dataset_rows
    dataset_rows: int = 1_000_000
    data_raw_dir: Path = Path("/data/raw")
    datasets_dir: Path = Path("/datasets")
    scopes_dir: Path = Path("/scopes")
    sample_file: str = "ecommerce_sales.csv"

    # Database
    db_host: str = "postgres"
    db_port: int = 5432
    db_name: str = "panorama"
    db_app_user: str = "panorama_app"
    db_pool_size: int = 8  # 8 + 2 = 10 connections for each api process (keeps idle connections, less reconnecting)
    db_max_overflow: int = 2
    db_pool_timeout: float = 5.0

    # Secrets folders (volumes)
    secrets_app_dir: Path = Path("/secrets/app")
    secrets_db_dir: Path = Path("/secrets/db")
    secrets_gw_dir: Path = Path("/secrets/gw")

    # API
    api_workers: int = 1
    allowed_origins: str = "http://localhost:8080,http://127.0.0.1:8080,http://localhost:5173"
    cookie_secure: bool = False
    jwt_ttl_hours: int = 8
    lockout_minutes: int = 5
    lockout_window_minutes: int = 15
    lockout_max_failures: int = 5
    loadtest_users: int = 0
    export_max_rows: int = 10_000

    # LLM gateway
    gateway_url: str = "http://llm-gateway:9000"
    gateway_port: int = 9000
    llm_provider: str = "ollama"
    llm_endpoint: str = "http://ollama:11434"
    llm_model: str = "qwen3:4b-instruct-2507-q4_K_M"
    llm_parallel: int = 4
    llm_endpoints: str = ""
    llm_max_wait_s: float = 20.0
    llm_turn_estimate_s: float = 8.0
    auto_pull_model: bool = True
    llm_num_ctx: int = 4096
    llm_num_thread: int = 2  # CPU threads of Ollama: the GPU does the work; 6 only for the CPU-only mode
    llm_num_batch: int = 512
    chat_turns_per_minute: int = 30
    chat_gpu_turns_per_minute: int = 12

    # RAG
    rag_hnsw_threshold: int = 50_000
    embed_model: str = "BAAI/bge-small-en-v1.5"
    fastembed_cache_path: str = "/opt/models"

    # Retention
    audit_query_retention_days: int = 14
    audit_retention_days: int = 90
    chat_retention_days: int = 90

    # Replica name for health and the admin system page
    replica: str = Field(default_factory=socket.gethostname)

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def dataset_path(self) -> Path:
        if self.dataset == "sample":
            return self.data_raw_dir / self.sample_file
        rows = 1_000_000 if self.dataset == "1m" else self.dataset_rows
        return self.datasets_dir / f"generated_{rows}.csv"

    @property
    def dataset_rows_target(self) -> int:
        if self.dataset == "sample":
            return 0
        return 1_000_000 if self.dataset == "1m" else self.dataset_rows

    def llm_endpoint_list(self) -> list[dict]:
        if self.llm_endpoints.strip():
            items = json.loads(self.llm_endpoints)
            if not isinstance(items, list) or not items:
                raise ValueError("LLM_ENDPOINTS must be a non-empty JSON list")
            return items
        return [{
            "name": "default",
            "provider": self.llm_provider,
            "url": self.llm_endpoint,
            "model": self.llm_model,
            "slots": max(1, self.llm_parallel),
        }]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def read_secret(folder: Path, name: str) -> str:
    """Read one secret file. A missing secret is a hard error (fail closed)."""
    path = folder / name
    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:  # pragma: no cover - depends on the volume
        raise RuntimeError(f"secret {name} is missing in {folder}") from exc
    if not value:
        raise RuntimeError(f"secret {name} is empty")
    return value


@lru_cache(maxsize=None)
def app_secret(name: str) -> str:
    return read_secret(get_settings().secrets_app_dir, name)


def set_thread_limits() -> None:
    """Keep numeric libraries on one thread in the api (the GPU model needs the CPU)."""
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ.setdefault(var, "1")
