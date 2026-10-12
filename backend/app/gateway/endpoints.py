"""LLM endpoints: slots, EWMA seconds per turn, breaker, model manager."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.gateway.breaker import Breaker
from app.gateway.model_manager import ModelManager
from app.gateway.providers import Provider

EWMA_ALPHA = 0.3


@dataclass
class Endpoint:
    name: str
    provider_kind: str
    url: str
    base_model: str
    slots: int
    provider: Provider
    manager: ModelManager | None
    breaker: Breaker = field(default_factory=Breaker)
    ewma_s: float = 18.0
    in_use: int = 0
    turns: int = 0
    tokens_per_s: float | None = None
    last_error: str | None = None

    @property
    def model(self) -> str:
        return self.manager.model if self.manager else self.base_model

    @property
    def ready(self) -> bool:
        return self.manager is None or self.manager.state == "ready"

    @property
    def healthy(self) -> bool:
        return self.ready and self.breaker.allows_turns

    @property
    def free(self) -> int:
        return max(0, self.slots - self.in_use)

    def record_turn(self, seconds: float) -> None:
        if seconds <= 0:
            return
        self.turns += 1
        self.ewma_s = EWMA_ALPHA * seconds + (1 - EWMA_ALPHA) * self.ewma_s

    def describe(self) -> dict:
        d = {
            "name": self.name, "provider": self.provider_kind, "url": self.url, "model": self.base_model,
            "slots": self.slots, "in_use": self.in_use, "breaker": self.breaker.state, "ewma_s": round(self.ewma_s, 2),
            "turns": self.turns, "tokens_per_s": self.tokens_per_s, "healthy": self.healthy, "last_error": self.last_error,
        }
        if self.manager:
            d.update(self.manager.describe())
        else:
            d.update({"model_state": "ready", "pull_progress": None, "vram_bytes": None})
        return d
