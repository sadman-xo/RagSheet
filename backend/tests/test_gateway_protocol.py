"""The lease protocol over real HTTP: api gateway_client <-> gateway app (fake endpoint)."""

from __future__ import annotations

import asyncio
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from app.chat import gateway_client as gc
from app.gateway.admission import Gateway
from app.gateway.app import create_app
from tests.fakes import fake_endpoint

TOKEN = "test-token"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture()
def server():
    ep, provider = fake_endpoint("fake", slots=1, delay=1.0, tokens=["a ", "b ", "c ", "d ", "e "])
    gw = Gateway([ep], max_wait_s=2.0, turn_estimate_s=1.0)
    app = create_app(gateway=gw, token=TOKEN, run_monitor=False)
    port = _free_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"))
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    deadline = time.time() + 10
    while not srv.started and time.time() < deadline:
        time.sleep(0.05)
    yield {"url": f"http://127.0.0.1:{port}", "gw": gw, "provider": provider, "ep": ep}
    srv.should_exit = True
    th.join(timeout=5)


@pytest.fixture()
async def client(server, monkeypatch):
    c = httpx.AsyncClient(base_url=server["url"], timeout=httpx.Timeout(60, connect=1.0))
    gc.set_client(c)
    monkeypatch.setattr(gc, "_headers", lambda: {"X-Gateway-Token": TOKEN})
    yield c
    gc.set_client(None)
    await c.aclose()


async def _wait(cond, timeout=3.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if cond():
            return True
        await asyncio.sleep(0.02)
    return False


async def test_full_turn(server, client):
    lease = await gc.register(1, "turn-1")
    events = [ev async for ev in lease.acquire()]
    assert events[-1]["type"] == "granted"
    plan = await lease.plan([{"role": "user", "content": "q"}], {"type": "object"}, {})
    assert plan["content"]
    text = "".join([ev["text"] async for ev in lease.stream_answer([], {}) if ev["type"] == "token"])
    assert text == "a b c d e "
    await lease.close()
    assert await _wait(lambda: not server["gw"].leases)
    assert server["ep"].in_use == 0


async def test_closing_the_lease_cancels_the_answer(server, client):
    lease = await gc.register(2, "turn-2")
    [ev async for ev in lease.acquire()]

    async def consume():
        async for _ in lease.stream_answer([], {}):
            pass

    task = asyncio.create_task(consume())
    assert await _wait(lambda: server["provider"].in_flight == 1)
    await lease.close()
    assert await _wait(lambda: server["provider"].cancelled == 1 and server["ep"].in_use == 0)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_second_turn_of_a_user_is_rejected_with_409(server, client):
    lease = await gc.register(3, "turn-3a")
    with pytest.raises(gc.GatewayRejected) as e:
        await gc.register(3, "turn-3b")
    assert e.value.status == 409
    await lease.close()
    assert await _wait(lambda: not server["gw"].leases)
    lease2 = await gc.register(3, "turn-3c")
    await lease2.close()


async def test_queued_then_shed(server, client):
    a = await gc.register(4, "turn-4a")
    assert [ev async for ev in a.acquire()][-1]["type"] == "granted"
    b = await gc.register(5, "turn-4b")
    events = [ev async for ev in b.acquire()]
    assert events[0]["type"] == "queued" and events[0]["position"] == 1
    assert events[-1] == {"type": "shed", "reason": "busy"}  # waited LLM_MAX_WAIT_S (2 s)
    await a.close()
    await b.close()


async def test_status_and_bad_token(server, client):
    st = await gc.status()
    assert st["available"] and st["total_slots"] == 1
    r = await client.get("/v1/status", headers={"X-Gateway-Token": "wrong"})
    assert r.status_code == 401


async def test_gateway_down_is_detected_fast(monkeypatch):
    c = httpx.AsyncClient(base_url="http://127.0.0.1:9", timeout=httpx.Timeout(60, connect=1.0))
    gc.set_client(c)
    monkeypatch.setattr(gc, "_headers", lambda: {"X-Gateway-Token": TOKEN})
    t0 = time.monotonic()
    with pytest.raises(gc.GatewayDown):
        await gc.register(9, "turn-9")
    assert time.monotonic() - t0 < 3.5
    assert (await gc.status())["available"] is False
    gc.set_client(None)
    await c.aclose()
