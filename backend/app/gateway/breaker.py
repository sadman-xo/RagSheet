"""Circuit breaker for one LLM endpoint.

closed: turns go to the endpoint. After 3 failures in a row: open (no new turns).
After 30 s, a health probe can close it again.
"""

from __future__ import annotations

import time


class Breaker:
    def __init__(self, threshold: int = 3, cooldown_s: float = 30.0, clock=time.monotonic):
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self.clock = clock
        self.failures = 0
        self.opened_at: float | None = None
        self.total_failures = 0

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "closed"
        return "half_open" if self.clock() - self.opened_at >= self.cooldown_s else "open"

    @property
    def allows_turns(self) -> bool:
        return self.opened_at is None

    def success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def failure(self) -> None:
        self.failures += 1
        self.total_failures += 1
        if self.failures >= self.threshold and self.opened_at is None:
            self.opened_at = self.clock()

    def probe_due(self) -> bool:
        return self.state == "half_open"

    def force_open(self) -> None:
        self.opened_at = self.clock()
        self.failures = max(self.failures, self.threshold)
