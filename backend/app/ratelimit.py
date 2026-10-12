"""Per-process token buckets for /auth/login and /export/* (a soft limit; x number of api processes).

The chat limits are global in the gateway, and the login lockout is global in PostgreSQL.
"""

from __future__ import annotations

import threading
import time


class TokenBucket:
    def __init__(self, capacity: int, per_seconds: float):
        self.capacity = capacity
        self.rate = capacity / per_seconds
        self._state: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def take(self, key: str) -> float:
        """Take one token. Returns 0 if allowed, else the seconds to wait."""
        now = time.monotonic()
        with self._lock:
            tokens, last = self._state.get(key, (float(self.capacity), now))
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            if tokens >= 1:
                self._state[key] = (tokens - 1, now)
                if len(self._state) > 50_000:
                    self._state.clear()
                return 0.0
            self._state[key] = (tokens, now)
            return (1 - tokens) / self.rate

    def reset(self) -> None:
        with self._lock:
            self._state.clear()


login_limiter = TokenBucket(capacity=20, per_seconds=60)
export_limiter = TokenBucket(capacity=10, per_seconds=60)
