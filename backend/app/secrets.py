"""One-shot job: make each secret one time.

Each file is created with O_EXCL and mode 0600. An existing file is never changed.
Three volumes keep the secrets apart:
- secrets_db:  the postgres superuser password (postgres and init only)
- secrets_app: the panorama_app password, JWT secret, PII HMAC key, gateway token (api and init)
- secrets_gw:  the gateway token (llm-gateway only)
"""

from __future__ import annotations

import os
import secrets as pysecrets
import sys
from pathlib import Path

from app.config import get_settings


def _create(path: Path, value: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(value)
    return True


def _token(n: int = 32) -> str:
    return pysecrets.token_urlsafe(n)


def main() -> int:
    s = get_settings()
    made: list[str] = []
    if _create(s.secrets_db_dir / "postgres_password", _token(24)):
        made.append("db/postgres_password")
    for name in ("app_db_password", "jwt_secret", "pii_hmac_key"):
        if _create(s.secrets_app_dir / name, _token(32 if name != "app_db_password" else 24)):
            made.append(f"app/{name}")

    # The gateway token must be the same in both volumes.
    app_tok = s.secrets_app_dir / "gateway_token"
    gw_tok = s.secrets_gw_dir / "gateway_token"
    if app_tok.exists():
        value = app_tok.read_text(encoding="utf-8").strip()
    elif gw_tok.exists():
        value = gw_tok.read_text(encoding="utf-8").strip()
    else:
        value = _token(32)
    if _create(app_tok, value):
        made.append("app/gateway_token")
    if _create(gw_tok, value):
        made.append("gw/gateway_token")
    if app_tok.read_text(encoding="utf-8").strip() != gw_tok.read_text(encoding="utf-8").strip():
        print("secrets: gateway_token differs between volumes", file=sys.stderr)
        return 1

    print("secrets: created " + (", ".join(made) if made else "nothing (all present)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
