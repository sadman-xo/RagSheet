"""Run the LLM gateway (one process)."""

from __future__ import annotations

import uvicorn

from app.config import get_settings


def main() -> None:
    s = get_settings()
    uvicorn.run("app.gateway.app:app", host="0.0.0.0", port=s.gateway_port, workers=1, access_log=False, log_level="info")


if __name__ == "__main__":
    main()
