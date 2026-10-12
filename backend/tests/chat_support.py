"""Helpers for chat tests: an in-process gateway with fake LLMs, and an api client that uses it."""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from contextlib import contextmanager

import uvicorn
from fastapi.testclient import TestClient

from app.chat import gateway_client
from app.config import app_secret, get_settings
from app.gateway.admission import Gateway
from app.gateway.app import create_app
from tests.conftest import ORIGIN
from tests.fakes import fake_endpoint


def echo_tokens(messages: list[dict]) -> list[str]:
    """EchoLLM: the answer is the full prompt (so a test can see everything the model saw)."""
    return ["\n".join(m["content"] for m in messages)]


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@contextmanager
def fake_gateway(slots: int = 1, max_wait: float = 3.0, delay: float = 0.05, **provider_kw):
    ep, prov = fake_endpoint("fake", slots=slots, delay=delay, **provider_kw)
    gw = Gateway([ep], max_wait_s=max_wait, turn_estimate_s=0.5)
    app = create_app(gateway=gw, token=app_secret("gateway_token"), run_monitor=False)
    port = _free_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"))
    loop = asyncio.new_event_loop()

    def run():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(srv.serve())

    th = threading.Thread(target=run, daemon=True)
    th.start()
    t0 = time.time()
    while not srv.started and time.time() - t0 < 10:
        time.sleep(0.02)
    try:
        yield {"url": f"http://127.0.0.1:{port}", "gw": gw, "provider": prov, "ep": ep, "loop": loop}
    finally:
        srv.should_exit = True
        th.join(timeout=5)


@contextmanager
def chat_client(gateway_url: str):
    from app.main import app

    s = get_settings()
    old = s.gateway_url
    s.gateway_url = gateway_url
    gateway_client.set_client(None)
    try:
        with TestClient(app, headers={"Origin": ORIGIN}) as c:
            yield c
    finally:
        s.gateway_url = old
        gateway_client.set_client(None)


def parse_sse(text: str) -> list[tuple[str, dict]]:
    out = []
    event, data = None, []
    for line in text.splitlines():
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].strip())
        elif not line.strip():
            if event and data:
                try:
                    out.append((event, json.loads("\n".join(data))))
                except json.JSONDecodeError:
                    pass
            event, data = None, []
    if event and data:
        out.append((event, json.loads("\n".join(data))))
    return out


def answer_of(events: list[tuple[str, dict]]) -> str:
    text = ""
    for name, data in events:
        if name == "token":
            text += data["text"]
        elif name == "replace":
            text = data["text"]
    return text


def done_of(events) -> dict:
    return next((d for n, d in events if n == "done"), {})


def ask(client, token: str, message: str, **kw) -> tuple[int, list[tuple[str, dict]], str]:
    import uuid

    body = {"message": message, "turn_id": str(uuid.uuid4()), **kw}
    r = client.post("/api/chat/stream", json=body, headers={"Authorization": f"Bearer {token}"})
    if r.status_code != 200:
        return r.status_code, [], r.text
    return 200, parse_sse(r.text), r.text
