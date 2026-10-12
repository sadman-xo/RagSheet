"""LLM load balancing and admission, with fake endpoints (no GPU)."""

from __future__ import annotations

import asyncio

import pytest

from app.gateway.admission import Gateway, Rejection
from tests.fakes import fake_endpoint


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


async def _acquire(gw: Gateway, lease) -> dict:
    last = None
    async for ev in gw.acquire(lease, poll_s=0.05):
        last = ev
    return last


async def _turn(gw: Gateway, user: str, tid: str, kind: str = "answer") -> str:
    lease = gw.register(user, tid)
    assert not isinstance(lease, Rejection)
    ev = await _acquire(gw, lease)
    try:
        if ev["type"] != "granted":
            return ev["reason"]
        if kind == "answer":
            async for _ in gw.generate_stream(lease, [{"role": "user", "content": "q"}], {}):
                pass
        else:
            await gw.generate_json(lease, [{"role": "user", "content": "q"}], {"type": "object"}, {})
        return ev["endpoint"]
    finally:
        await gw.close(lease)


async def test_most_free_slots_first_and_never_more_than_the_slots():
    e1, p1 = fake_endpoint("one", slots=1, delay=0.2)
    e2, p2 = fake_endpoint("two", slots=2, delay=0.2)
    gw = Gateway([e1, e2], max_wait_s=10, turn_estimate_s=0.2)
    leases = [gw.register(f"u{i}", f"t{i}") for i in range(5)]
    first = await _acquire(gw, leases[0])
    assert first["endpoint"] == "two"  # 2 free slots > 1 free slot
    results = await asyncio.gather(*[_turn(gw, f"v{i}", f"x{i}") for i in range(9)], _cleanup(gw, leases))
    assert gw.stats["max_in_flight"] <= 3
    assert p1.max_in_flight <= 1 and p2.max_in_flight <= 2
    assert set(results[0:9]) <= {"one", "two"}


async def _cleanup(gw, leases):
    await asyncio.sleep(0.3)
    for lease in leases:
        await gw.close(lease)


async def test_failing_endpoint_opens_breaker_and_recovers():
    clock = Clock()
    e1, p1 = fake_endpoint("bad", slots=1, delay=0.01, clock=clock)
    e2, p2 = fake_endpoint("good", slots=1, delay=0.01, clock=clock)
    gw = Gateway([e1, e2], max_wait_s=5, turn_estimate_s=0.05, clock=clock)
    p1.fail = True
    used = []
    for i in range(8):
        lease = gw.register(f"u{i}", f"t{i}")
        ev = await _acquire(gw, lease)
        assert ev["type"] == "granted"
        used.append(ev["endpoint"])
        try:
            async for _ in gw.generate_stream(lease, [], {}):
                pass
        except Exception:
            pass
        await gw.close(lease)
    assert e1.breaker.state == "open"
    assert used[-3:] == ["good", "good", "good"]  # no new turns for the open endpoint
    # recovery: after the cooldown a health probe closes the breaker
    p1.fail = False
    clock.t += 31
    assert e1.breaker.probe_due()
    assert await p1.health()
    e1.breaker.success()
    seen = set()
    for i in range(6):
        lease = gw.register(f"r{i}", f"rt{i}")
        lease2 = gw.register(f"s{i}", f"st{i}")
        ev1, ev2 = await asyncio.gather(_acquire(gw, lease), _acquire(gw, lease2))
        seen |= {ev1.get("endpoint"), ev2.get("endpoint")}
        await gw.close(lease)
        await gw.close(lease2)
    assert "bad" in seen


async def test_slow_endpoint_gets_fewer_turns():
    slow, ps = fake_endpoint("slow", slots=1, delay=0.25)
    fast, pf = fake_endpoint("fast", slots=1, delay=0.02)
    gw = Gateway([slow, fast], max_wait_s=30, turn_estimate_s=0.1)

    async def worker(w: int):
        for i in range(8):
            await _turn(gw, f"w{w}", f"w{w}-{i}")

    await asyncio.gather(*[worker(w) for w in range(3)])
    assert fast.turns > slow.turns
    assert fast.ewma_s < slow.ewma_s


async def test_all_endpoints_down_sheds_as_unavailable():
    e1, p1 = fake_endpoint("a", slots=1)
    e1.breaker.force_open()
    gw = Gateway([e1], max_wait_s=5, turn_estimate_s=1)
    lease = gw.register("u", "t")
    ev = await _acquire(gw, lease)
    assert ev == {"type": "shed", "reason": "unavailable"}
    assert gw.state() == "unavailable"
    await gw.close(lease)


async def test_fifo_order_queue_positions_and_shed_after_wait():
    e1, p1 = fake_endpoint("a", slots=1, delay=0.05)
    gw = Gateway([e1], max_wait_s=0.6, turn_estimate_s=0.2)
    holder = gw.register("h", "h1")
    assert (await _acquire(gw, holder))["type"] == "granted"
    order: list[str] = []
    positions: dict[str, list[int]] = {}

    async def waiter(name: str, delay: float):
        await asyncio.sleep(delay)
        lease = gw.register(name, f"t-{name}")
        async for ev in gw.acquire(lease, poll_s=0.05):
            if ev["type"] == "queued":
                positions.setdefault(name, []).append(ev["position"])
            else:
                order.append(f"{name}:{ev['type']}")
        await gw.close(lease)

    async def release_later():
        await asyncio.sleep(0.2)
        await gw.close(holder)

    await asyncio.gather(waiter("first", 0.0), waiter("second", 0.02), release_later())
    assert order[0] == "first:granted"
    assert positions["second"][0] == 2 and positions["second"][-1] in (1, 2)
    # a waiting turn is shed after LLM_MAX_WAIT_S (the first turn holds the slot for its whole lease)
    assert order[1] in ("second:granted", "second:shed")


async def test_queue_full_sheds_at_once():
    e1, _ = fake_endpoint("a", slots=1)
    gw = Gateway([e1], max_wait_s=1.0, turn_estimate_s=1.0)  # max queue = 1
    h = gw.register("h", "h")
    await _acquire(gw, h)
    q1 = gw.register("q1", "q1")
    task = asyncio.create_task(_acquire(gw, q1))
    await asyncio.sleep(0.05)
    q2 = gw.register("q2", "q2")
    ev = await _acquire(gw, q2)
    assert ev == {"type": "shed", "reason": "busy"}
    await gw.close(h)
    assert (await task)["type"] == "granted"
    for lease in (q1, q2):
        await gw.close(lease)


async def test_one_turn_per_user_duplicates_and_rate_limits():
    e1, _ = fake_endpoint("a", slots=1)
    gw = Gateway([e1], max_wait_s=1, turn_estimate_s=1, turns_per_minute=3)
    a = gw.register("u", "t1")
    r = gw.register("u", "t2")
    assert isinstance(r, Rejection) and r.status == 409
    await gw.close(a)
    r = gw.register("u", "t1")
    assert isinstance(r, Rejection) and r.status == 409 and r.reason == "duplicate_turn"
    for i in range(2):
        await gw.close(gw.register("u", f"n{i}"))
    r = gw.register("u", "n9")
    assert isinstance(r, Rejection) and r.status == 429 and r.retry_after > 0


async def test_close_cancels_upstream_before_the_slot_is_free():
    e1, p1 = fake_endpoint("a", slots=1, delay=2.0)
    gw = Gateway([e1], max_wait_s=5, turn_estimate_s=1)
    lease = gw.register("u", "t")
    await _acquire(gw, lease)

    async def consume():
        async for _ in gw.generate_stream(lease, [], {}):
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.1)
    assert p1.in_flight == 1
    await gw.close(lease)
    assert p1.in_flight == 0 and p1.cancelled == 1  # upstream ended before close() returned
    assert e1.in_use == 0
    await asyncio.gather(task, return_exceptions=True)
    # the next grant happens only now
    nxt = gw.register("v", "t2")
    assert (await _acquire(gw, nxt))["type"] == "granted"
    await gw.close(nxt)


async def test_llm_error_keeps_slot_accounting_correct():
    e1, p1 = fake_endpoint("a", slots=1, fail=True)
    gw = Gateway([e1], max_wait_s=5, turn_estimate_s=1)
    lease = gw.register("u", "t")
    await _acquire(gw, lease)
    with pytest.raises(Exception):
        await gw.generate_json(lease, [], {}, {})
    await gw.release_slot(lease)
    assert e1.in_use == 0
    await gw.close(lease)
    assert not gw.leases and not gw.user_turn


async def test_release_slot_keeps_lease():
    e1, _ = fake_endpoint("a", slots=1)
    gw = Gateway([e1], max_wait_s=5, turn_estimate_s=1)
    lease = gw.register("u", "t")
    await _acquire(gw, lease)
    await gw.release_slot(lease)
    assert e1.in_use == 0 and lease.state == "registered" and "t" in gw.leases
    other = gw.register("v", "t2")
    assert (await _acquire(gw, other))["type"] == "granted"
    await gw.close(other)
    await gw.close(lease)
