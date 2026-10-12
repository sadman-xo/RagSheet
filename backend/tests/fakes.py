"""Fake LLM providers and helpers for the gateway, chat, and RAG tests."""

from __future__ import annotations

import asyncio
import json
import time

from app.gateway.breaker import Breaker
from app.gateway.endpoints import Endpoint
from app.gateway.providers import CallStats


class FakeProvider:
    """Counts parallel calls and cancellations. Can be slow, fail, or return scripted content."""

    name = "fake"

    def __init__(self, delay: float = 0.05, tokens: list[str] | None = None, plan: str | dict | None = None, fail: bool = False):
        self.delay = delay
        self.tokens = tokens or ["The ", "answer ", "is ", "here."]
        self.plan = plan if plan is not None else {"intent": "metric"}
        self.fail = fail
        self.healthy = True
        self.in_flight = 0
        self.max_in_flight = 0
        self.calls = 0
        self.cancelled = 0
        self.events: list[tuple[float, str]] = []
        self.prompts: list[list[dict]] = []

    def _enter(self) -> None:
        self.calls += 1
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        self.events.append((time.monotonic(), "start"))

    def _exit(self, cancelled: bool = False) -> None:
        self.in_flight -= 1
        if cancelled:
            self.cancelled += 1
        self.events.append((time.monotonic(), "cancel" if cancelled else "end"))

    async def health(self) -> bool:
        return self.healthy

    async def chat_json(self, model, messages, schema, options):
        self._enter()
        self.prompts.append(messages)
        cancelled = False
        try:
            await asyncio.sleep(self.delay)
            if self.fail:
                raise RuntimeError("fake failure")
            content = self.plan(messages) if callable(self.plan) else self.plan
            return (content if isinstance(content, str) else json.dumps(content)), CallStats(output_tokens=10, seconds=self.delay, tokens_per_s=50)
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            self._exit(cancelled=cancelled)

    async def chat_stream(self, model, messages, options, stats: CallStats):
        self._enter()
        self.prompts.append(messages)
        cancelled = False
        try:
            if self.fail:
                await asyncio.sleep(self.delay / 2)
                raise RuntimeError("fake failure")
            tokens = self.tokens(messages) if callable(self.tokens) else self.tokens
            for tok in tokens:
                await asyncio.sleep(self.delay / max(1, len(tokens)))
                yield tok
            stats.output_tokens = len(tokens)
            stats.tokens_per_s = 40.0
        except (asyncio.CancelledError, GeneratorExit):
            cancelled = True
            raise
        finally:
            self._exit(cancelled=cancelled)

    async def aclose(self) -> None:
        return None


def fake_endpoint(name: str, slots: int = 1, delay: float = 0.05, clock=time.monotonic, **kw) -> tuple[Endpoint, FakeProvider]:
    p = FakeProvider(delay=delay, **kw)
    ep = Endpoint(name=name, provider_kind="fake", url="", base_model="fake-model", slots=slots, provider=p, manager=None,
                  breaker=Breaker(threshold=3, cooldown_s=30.0, clock=clock))
    return ep, p


def build_fixture_corpus(conn, data_version: str) -> None:  # replaced by the RAG milestone fixture
    try:
        from tests.rag_fixture import build
    except ImportError:
        return
    build(conn, data_version)
