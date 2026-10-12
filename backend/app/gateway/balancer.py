"""LLM load balancer: select the endpoint for the next turn.

Among healthy endpoints with a free slot, select the one with the most free slots, then the lowest
EWMA seconds per turn (a faster endpoint gets more turns).
"""

from __future__ import annotations

import math

from app.gateway.endpoints import Endpoint


def pick(endpoints: list[Endpoint]) -> Endpoint | None:
    candidates = [e for e in endpoints if e.healthy and e.free > 0]
    if not candidates:
        return None
    return max(candidates, key=lambda e: (e.free, -e.ewma_s, -endpoints.index(e)))


def healthy_slots(endpoints: list[Endpoint]) -> int:
    return sum(e.slots for e in endpoints if e.healthy)


def weighted_ewma(endpoints: list[Endpoint], seed: float) -> float:
    hs = [e for e in endpoints if e.healthy]
    total = sum(e.slots for e in hs)
    if not total:
        return seed
    return sum(e.ewma_s * e.slots for e in hs) / total


def eta_seconds(position: int, endpoints: list[Endpoint], seed: float) -> float:
    slots = healthy_slots(endpoints)
    if slots == 0:
        return float("inf")
    return math.ceil(position / slots) * weighted_ewma(endpoints, seed)
