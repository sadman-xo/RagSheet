"""LLM providers: Ollama (default) and OpenAI-compatible servers (vLLM).

Both offer the same interface. Cancelling the caller's task closes the upstream HTTP request, so the
server stops the sequence.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Protocol

import httpx

THINK_RE = re.compile(r"<think>.*?</think>\s*", re.S)


@dataclass
class CallStats:
    prompt_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    tokens_per_s: float | None = None
    extra: dict = field(default_factory=dict)


class Provider(Protocol):
    name: str

    async def health(self) -> bool: ...
    async def chat_json(self, model: str, messages: list[dict], schema: dict, options: dict) -> tuple[str, CallStats]: ...
    def chat_stream(self, model: str, messages: list[dict], options: dict, stats: CallStats) -> AsyncIterator[str]: ...
    async def aclose(self) -> None: ...


def strip_think(text: str) -> str:
    return THINK_RE.sub("", text).strip()


class OllamaProvider:
    name = "ollama"

    def __init__(self, url: str, timeout: float = 300.0):
        self.url = url.rstrip("/")
        self.client = httpx.AsyncClient(base_url=self.url, timeout=httpx.Timeout(timeout, connect=3.0))

    async def aclose(self) -> None:
        await self.client.aclose()

    async def health(self) -> bool:
        try:
            r = await self.client.get("/api/version", timeout=3.0)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    @staticmethod
    def _options(options: dict) -> dict:
        return {k: v for k, v in options.items() if k in ("temperature", "num_predict", "top_p", "top_k", "seed", "repeat_penalty", "stop")}

    async def chat_json(self, model, messages, schema, options):
        t0 = time.perf_counter()
        body = {"model": model, "messages": messages, "format": schema, "stream": False, "think": False,
                "keep_alive": -1, "options": self._options(options)}
        r = await self.client.post("/api/chat", json=body)
        r.raise_for_status()
        data = r.json()
        stats = CallStats(prompt_tokens=data.get("prompt_eval_count", 0), output_tokens=data.get("eval_count", 0),
                          seconds=time.perf_counter() - t0)
        if data.get("eval_duration"):
            stats.tokens_per_s = data.get("eval_count", 0) / (data["eval_duration"] / 1e9)
        return strip_think(data.get("message", {}).get("content", "")), stats

    async def chat_stream(self, model, messages, options, stats: CallStats):
        t0 = time.perf_counter()
        body = {"model": model, "messages": messages, "stream": True, "think": False, "keep_alive": -1,
                "options": self._options(options)}
        in_think = False
        async with self.client.stream("POST", "/api/chat", json=body) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.strip():
                    continue
                data = json.loads(line)
                if data.get("error"):
                    raise RuntimeError(data["error"])
                piece = data.get("message", {}).get("content", "")
                if piece:
                    # Remove a <think>…</think> block if a model emits one.
                    if "<think>" in piece:
                        in_think = True
                        piece = piece.split("<think>", 1)[0]
                    if in_think:
                        if "</think>" in piece:
                            in_think = False
                            piece = piece.split("</think>", 1)[1]
                        else:
                            piece = ""
                    if piece:
                        yield piece
                if data.get("done"):
                    stats.prompt_tokens = data.get("prompt_eval_count", 0)
                    stats.output_tokens = data.get("eval_count", 0)
                    if data.get("eval_duration"):
                        stats.tokens_per_s = data["eval_count"] / (data["eval_duration"] / 1e9)
        stats.seconds = time.perf_counter() - t0


class OpenAICompatProvider:
    name = "openai_compatible"

    def __init__(self, url: str, timeout: float = 300.0):
        self.url = url.rstrip("/")
        self.client = httpx.AsyncClient(base_url=self.url, timeout=httpx.Timeout(timeout, connect=3.0))

    async def aclose(self) -> None:
        await self.client.aclose()

    async def health(self) -> bool:
        try:
            r = await self.client.get("/models", timeout=3.0)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def models(self) -> list[str]:
        r = await self.client.get("/models", timeout=5.0)
        r.raise_for_status()
        return [m["id"] for m in r.json().get("data", [])]

    @staticmethod
    def _body(model, messages, options) -> dict:
        return {"model": model, "messages": messages, "temperature": options.get("temperature", 0.2),
                "max_tokens": options.get("num_predict", 256), "chat_template_kwargs": {"enable_thinking": False}}

    async def chat_json(self, model, messages, schema, options):
        t0 = time.perf_counter()
        body = self._body(model, messages, options)
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "plan", "schema": schema, "strict": True}}
        r = await self.client.post("/chat/completions", json=body)
        r.raise_for_status()
        data = r.json()
        usage = data.get("usage", {})
        secs = time.perf_counter() - t0
        stats = CallStats(prompt_tokens=usage.get("prompt_tokens", 0), output_tokens=usage.get("completion_tokens", 0), seconds=secs)
        stats.tokens_per_s = stats.output_tokens / secs if secs > 0 else None
        return strip_think(data["choices"][0]["message"]["content"] or ""), stats

    async def chat_stream(self, model, messages, options, stats: CallStats):
        t0 = time.perf_counter()
        body = self._body(model, messages, options)
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
        async with self.client.stream("POST", "/chat/completions", json=body) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                data = json.loads(payload)
                if data.get("usage"):
                    stats.prompt_tokens = data["usage"].get("prompt_tokens", 0)
                    stats.output_tokens = data["usage"].get("completion_tokens", 0)
                for ch in data.get("choices", []):
                    piece = (ch.get("delta") or {}).get("content")
                    if piece:
                        yield piece
        stats.seconds = time.perf_counter() - t0
        if stats.seconds > 0 and stats.output_tokens:
            stats.tokens_per_s = stats.output_tokens / stats.seconds


def make_provider(kind: str, url: str) -> Provider:
    if kind == "ollama":
        return OllamaProvider(url)
    if kind in ("openai_compatible", "vllm", "openai"):
        return OpenAICompatProvider(url)
    raise ValueError(f"unknown LLM provider {kind!r}")
