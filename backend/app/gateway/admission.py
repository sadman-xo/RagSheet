"""Admission control: leases, per-user limits, one global FIFO queue, slots, shedding.

- A turn registers (lease). Per user: 1 turn in flight, 30 turns each minute, no duplicate turn_id.
- acquire puts the turn in the FIFO queue (12 GPU turns each minute for each user). When a slot is free on
  any endpoint, the head of the queue gets it (the balancer selects the endpoint).
- A turn waits at most LLM_MAX_WAIT_S. If the queue is full, or the wait is too long, the turn is shed.
  The gateway never sheds a granted turn.
- A turn holds at most one slot, from its first GPU call to its last.
- When the lease ends, the gateway first cancels the turn's tasks (this closes the upstream request), then frees
  the slot. Thus no endpoint gets more requests than its slots.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import AsyncIterator, Callable

from app.gateway import balancer
from app.gateway.endpoints import Endpoint
from app.gateway.providers import CallStats

LEASE_MAX_AGE_S = 300.0
DUPLICATE_WINDOW_S = 600.0


class GatewayError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass
class Lease:
    turn_id: str
    user_id: str
    created: float
    state: str = "registered"  # registered | queued | granted | closed
    endpoint: Endpoint | None = None
    granted_at: float | None = None
    queued_at: float | None = None
    waiter: asyncio.Future | None = None
    tasks: set = field(default_factory=set)
    gpu_seconds: float = 0.0
    calls: int = 0


@dataclass
class Rejection:
    status: int
    reason: str
    retry_after: float = 0.0


class Gateway:
    def __init__(self, endpoints: list[Endpoint], max_wait_s: float = 20.0, turn_estimate_s: float = 18.0,
                 turns_per_minute: int = 30, gpu_turns_per_minute: int = 12, clock: Callable[[], float] = time.monotonic):
        self.endpoints = endpoints
        self.max_wait_s = max_wait_s
        self.seed_s = turn_estimate_s
        for e in endpoints:
            e.ewma_s = turn_estimate_s
        self.turns_per_minute = turns_per_minute
        self.gpu_turns_per_minute = gpu_turns_per_minute
        self.clock = clock
        self.leases: dict[str, Lease] = {}
        self.user_turn: dict[str, str] = {}
        self.reg_times: dict[str, deque] = {}
        self.gpu_times: dict[str, deque] = {}
        self.recent_ids: dict[str, float] = {}
        self.queue: deque[Lease] = deque()
        self.stats = {"registered": 0, "rejected": 0, "granted": 0, "shed": 0, "shed_busy": 0, "shed_down": 0,
                      "released": 0, "closed": 0, "calls": 0, "call_errors": 0, "max_in_flight": 0}

    # ------------------------------------------------------------------ helpers
    @property
    def total_slots(self) -> int:
        return sum(e.slots for e in self.endpoints)

    @property
    def in_flight(self) -> int:
        return sum(e.in_use for e in self.endpoints)

    def ewma(self) -> float:
        return balancer.weighted_ewma(self.endpoints, self.seed_s)

    def max_queue(self) -> int:
        slots = balancer.healthy_slots(self.endpoints)
        return max(1, math.floor(self.max_wait_s * max(slots, 1) / max(self.ewma(), 0.1)))

    def eta(self, position: int) -> float:
        return balancer.eta_seconds(position, self.endpoints, self.seed_s)

    @staticmethod
    def _rate(times: deque, now: float, limit: int, window: float = 60.0) -> float:
        while times and now - times[0] > window:
            times.popleft()
        if len(times) >= limit:
            return window - (now - times[0])
        return 0.0

    # ------------------------------------------------------------------ register / close
    def register(self, user_id: str, turn_id: str) -> Lease | Rejection:
        now = self.clock()
        self._expire(now)
        if turn_id in self.leases or turn_id in self.recent_ids:
            self.stats["rejected"] += 1
            return Rejection(409, "duplicate_turn")
        if user_id in self.user_turn:
            self.stats["rejected"] += 1
            return Rejection(409, "turn_in_flight", 1.0)
        times = self.reg_times.setdefault(user_id, deque())
        wait = self._rate(times, now, self.turns_per_minute)
        if wait > 0:
            self.stats["rejected"] += 1
            return Rejection(429, "too_many_turns", wait)
        times.append(now)
        lease = Lease(turn_id=turn_id, user_id=user_id, created=now)
        self.leases[turn_id] = lease
        self.user_turn[user_id] = turn_id
        self.recent_ids[turn_id] = now
        self.stats["registered"] += 1
        return lease

    def _expire(self, now: float) -> None:
        for tid, ts in list(self.recent_ids.items()):
            if now - ts > DUPLICATE_WINDOW_S:
                del self.recent_ids[tid]

    async def close(self, lease: Lease) -> None:
        """End the lease: cancel its tasks (upstream requests stop), free the slot, remove the lease."""
        if lease.state == "closed":
            return
        was_queued = lease.state == "queued"
        lease.state = "closed"
        if was_queued and lease in self.queue:
            self.queue.remove(lease)
        if lease.waiter and not lease.waiter.done():
            lease.waiter.set_result(("shed", "closed"))
        await self._cancel_tasks(lease)
        self._free_slot(lease)
        self.leases.pop(lease.turn_id, None)
        if self.user_turn.get(lease.user_id) == lease.turn_id:
            del self.user_turn[lease.user_id]
        self.stats["closed"] += 1
        self.dispatch()

    async def _cancel_tasks(self, lease: Lease) -> None:
        tasks = [t for t in lease.tasks if not t.done()]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        lease.tasks.clear()

    def _free_slot(self, lease: Lease) -> None:
        ep = lease.endpoint
        if ep is None:
            return
        ep.in_use = max(0, ep.in_use - 1)
        if lease.granted_at is not None:
            ep.record_turn(self.clock() - lease.granted_at)
        lease.endpoint = None
        lease.granted_at = None
        self.stats["released"] += 1

    async def release_slot(self, lease: Lease) -> None:
        """Free the slot but keep the lease (for example: the planner ran, the answer is a template)."""
        await self._cancel_tasks(lease)
        self._free_slot(lease)
        if lease.state == "granted":
            lease.state = "registered"
        self.dispatch()

    async def reap(self) -> int:
        """Close leases that are too old (a lost connection that was not detected)."""
        now = self.clock()
        old = [lease for lease in self.leases.values() if now - lease.created > LEASE_MAX_AGE_S]
        for lease in old:
            await self.close(lease)
        return len(old)

    # ------------------------------------------------------------------ queue
    def dispatch(self) -> None:
        while self.queue:
            ep = balancer.pick(self.endpoints)
            if ep is None:
                return
            lease = self.queue.popleft()
            self._grant(lease, ep)

    def _grant(self, lease: Lease, ep: Endpoint) -> None:
        ep.in_use += 1
        lease.endpoint = ep
        lease.state = "granted"
        lease.granted_at = self.clock()
        self.stats["granted"] += 1
        self.stats["max_in_flight"] = max(self.stats["max_in_flight"], self.in_flight)
        if lease.waiter and not lease.waiter.done():
            lease.waiter.set_result(("granted", ep.name))

    def _shed(self, lease: Lease, reason: str) -> dict:
        if lease in self.queue:
            self.queue.remove(lease)
        lease.state = "registered"
        self.stats["shed"] += 1
        self.stats["shed_down" if reason == "unavailable" else "shed_busy"] += 1
        return {"type": "shed", "reason": reason}

    async def acquire(self, lease: Lease, poll_s: float = 2.0) -> AsyncIterator[dict]:
        """Yield queued{pos, eta_s} events, then granted{endpoint} or shed{reason}."""
        if lease.state == "closed":
            yield {"type": "shed", "reason": "closed"}
            return
        if lease.state == "granted" and lease.endpoint is not None:
            yield {"type": "granted", "endpoint": lease.endpoint.name}
            return
        now = self.clock()
        times = self.gpu_times.setdefault(lease.user_id, deque())
        wait = self._rate(times, now, self.gpu_turns_per_minute)
        if wait > 0:
            ev = self._shed(lease, "rate_limited")
            ev["retry_after"] = round(wait, 1)
            yield ev
            return
        if balancer.healthy_slots(self.endpoints) == 0:
            yield self._shed(lease, "unavailable")
            return
        if len(self.queue) >= self.max_queue():
            yield self._shed(lease, "busy")
            return
        times.append(now)
        loop = asyncio.get_running_loop()
        lease.waiter = loop.create_future()
        lease.state = "queued"
        lease.queued_at = now
        self.queue.append(lease)
        self.dispatch()
        deadline = now + self.max_wait_s
        try:
            while True:
                if lease.waiter.done():
                    kind, value = lease.waiter.result()
                    if kind == "granted":
                        yield {"type": "granted", "endpoint": value, "waited_s": round(self.clock() - now, 2)}
                    else:
                        yield {"type": "shed", "reason": value}
                    return
                pos = self.queue.index(lease) + 1 if lease in self.queue else 0
                yield {"type": "queued", "position": pos, "eta_s": round(self.eta(pos), 1)}
                remaining = deadline - self.clock()
                if remaining <= 0:
                    yield self._shed(lease, "busy")
                    return
                if balancer.healthy_slots(self.endpoints) == 0:
                    yield self._shed(lease, "unavailable")
                    return
                try:
                    await asyncio.wait_for(asyncio.shield(lease.waiter), timeout=min(poll_s, remaining))
                except asyncio.TimeoutError:
                    pass
        finally:
            if lease.state == "queued":  # the caller left while waiting
                self._shed(lease, "left")

    # ------------------------------------------------------------------ generation
    def _check_granted(self, lease: Lease) -> Endpoint:
        if lease.state == "closed":
            raise GatewayError(410, "lease_closed", "The turn has ended.")
        if lease.state != "granted" or lease.endpoint is None:
            raise GatewayError(409, "no_slot", "The turn has no GPU slot.")
        return lease.endpoint

    def _record(self, ep: Endpoint, stats: CallStats, ok: bool, error: str | None = None) -> None:
        self.stats["calls"] += 1
        if ok:
            ep.breaker.success()
            if stats.tokens_per_s:
                ep.tokens_per_s = round(stats.tokens_per_s, 1)
        else:
            self.stats["call_errors"] += 1
            ep.breaker.failure()
            ep.last_error = (error or "")[:200]

    async def generate_json(self, lease: Lease, messages: list[dict], schema: dict, options: dict) -> tuple[str, CallStats]:
        ep = self._check_granted(lease)

        async def call():
            return await ep.provider.chat_json(ep.model, messages, schema, options)

        task = asyncio.create_task(call())
        lease.tasks.add(task)
        lease.calls += 1
        try:
            content, stats = await task
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._record(ep, CallStats(), False, f"{type(exc).__name__}: {exc}")
            raise GatewayError(502, "llm_error", f"The LLM call failed: {type(exc).__name__}")
        finally:
            lease.tasks.discard(task)
        self._record(ep, stats, True)
        return content, stats

    async def generate_stream(self, lease: Lease, messages: list[dict], options: dict) -> AsyncIterator[dict]:
        """Yield {"type": "token", "text"} events, then {"type": "done", stats}."""
        ep = self._check_granted(lease)
        q: asyncio.Queue = asyncio.Queue()
        stats = CallStats()
        END = object()

        async def produce():
            try:
                async for piece in ep.provider.chat_stream(ep.model, messages, options, stats):
                    await q.put(piece)
                self._record(ep, stats, True)
                await q.put(END)
            except asyncio.CancelledError:
                await q.put(END)
                raise
            except Exception as exc:
                self._record(ep, stats, False, f"{type(exc).__name__}: {exc}")
                await q.put(GatewayError(502, "llm_error", f"The LLM call failed: {type(exc).__name__}"))

        task = asyncio.create_task(produce())
        lease.tasks.add(task)
        lease.calls += 1
        try:
            while True:
                item = await q.get()
                if item is END:
                    break
                if isinstance(item, GatewayError):
                    raise item
                yield {"type": "token", "text": item}
            if task.cancelled():
                yield {"type": "cancelled"}
                return
            yield {"type": "done", "output_tokens": stats.output_tokens, "prompt_tokens": stats.prompt_tokens,
                   "seconds": round(stats.seconds, 2), "tokens_per_s": stats.tokens_per_s}
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            lease.tasks.discard(task)

    # ------------------------------------------------------------------ status
    def state(self) -> str:
        if not self.endpoints:
            return "unavailable"
        if any(e.healthy for e in self.endpoints):
            return "busy" if self.queue and self.in_flight >= balancer.healthy_slots(self.endpoints) else "ready"
        managers = [e.manager for e in self.endpoints if e.manager]
        if any(m.state == "downloading" for m in managers):
            return "downloading"
        if any(m.state in ("checking", "creating", "loading", "unknown") for m in managers):
            return "loading"
        return "unavailable"

    def status(self) -> dict:
        progress = None
        for e in self.endpoints:
            if e.manager and e.manager.state == "downloading":
                progress = e.manager.progress
        return {
            "state": self.state(), "queue_length": len(self.queue), "max_queue": self.max_queue(),
            "in_flight": self.in_flight, "total_slots": self.total_slots,
            "healthy_slots": balancer.healthy_slots(self.endpoints), "ewma_s": round(self.ewma(), 2),
            "max_wait_s": self.max_wait_s, "leases": len(self.leases), "pull_progress": progress,
            "model": self.endpoints[0].base_model if self.endpoints else None,
            "stats": dict(self.stats), "endpoints": [e.describe() for e in self.endpoints],
        }
