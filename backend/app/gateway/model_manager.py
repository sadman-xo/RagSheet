"""Model manager for one endpoint.

Ollama: check /api/version and /api/show; pull the model with progress if it is missing (AUTO_PULL_MODEL);
create the derived model panorama-<sha8(base, options)> (num_ctx, num_thread, num_batch), so that every call
uses the same options and Ollama never reloads the model; warm up; read /api/ps for the VRAM use.
OpenAI-compatible: wait until /v1/models lists the model.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time

import httpx


def derived_name(base: str, options: dict) -> str:
    h = hashlib.sha256((base + json.dumps(options, sort_keys=True)).encode()).hexdigest()[:8]
    return f"panorama-{h}"


class ModelManager:
    def __init__(self, provider_kind: str, url: str, base_model: str, options: dict, auto_pull: bool = True):
        self.kind = provider_kind
        self.url = url.rstrip("/")
        self.base = base_model
        self.options = options
        self.auto_pull = auto_pull
        self.derived = derived_name(base_model, options) if provider_kind == "ollama" else base_model
        self.state = "unknown"     # unknown | checking | downloading | creating | loading | ready | error
        self.progress: float | None = None
        self.error: str | None = None
        self.vram_bytes: int | None = None
        self.size_bytes: int | None = None
        self.ready_at: float | None = None

    @property
    def model(self) -> str:
        return self.derived

    def describe(self) -> dict:
        return {"model_state": self.state, "pull_progress": self.progress, "model_error": self.error,
                "vram_bytes": self.vram_bytes, "size_bytes": self.size_bytes, "derived_model": self.derived}

    async def ensure(self) -> bool:
        """Bring the model to the ready state. Returns True when ready."""
        try:
            if self.kind == "ollama":
                return await self._ensure_ollama()
            return await self._ensure_openai()
        except (httpx.HTTPError, OSError, ValueError, KeyError) as exc:
            self.state = "error"
            self.error = f"{type(exc).__name__}: {exc}"[:300]
            return False

    async def _ensure_openai(self) -> bool:
        self.state = "checking"
        async with httpx.AsyncClient(base_url=self.url, timeout=10) as c:
            r = await c.get("/models")
            r.raise_for_status()
            ids = [m["id"] for m in r.json().get("data", [])]
        if self.base not in ids:
            self.state = "loading"
            self.error = f"model {self.base} not listed yet"
            return False
        self.state = "ready"
        self.error = None
        self.ready_at = time.time()
        return True

    async def _ensure_ollama(self) -> bool:
        async with httpx.AsyncClient(base_url=self.url, timeout=httpx.Timeout(600, connect=3)) as c:
            self.state = "checking"
            (await c.get("/api/version")).raise_for_status()
            if (await c.post("/api/show", json={"model": self.base})).status_code != 200:
                if not self.auto_pull:
                    self.state = "error"
                    self.error = f"model {self.base} is missing and AUTO_PULL_MODEL is false"
                    return False
                await self._pull(c)
            if (await c.post("/api/show", json={"model": self.derived})).status_code != 200:
                self.state = "creating"
                r = await c.post("/api/create", json={"model": self.derived, "from": self.base, "parameters": self.options, "stream": False})
                if r.status_code != 200:
                    raise ValueError(f"create failed: {r.status_code} {r.text[:200]}")
            self.state = "loading"
            r = await c.post("/api/chat", json={"model": self.derived, "messages": [{"role": "user", "content": "Reply with OK."}],
                                                "stream": False, "think": False, "keep_alive": -1, "options": {"num_predict": 2}})
            r.raise_for_status()
            await self.refresh_ps(c)
        self.state = "ready"
        self.error = None
        self.progress = None
        self.ready_at = time.time()
        return True

    async def _pull(self, c: httpx.AsyncClient) -> None:
        self.state = "downloading"
        self.progress = 0.0
        async with c.stream("POST", "/api/pull", json={"model": self.base, "stream": True}, timeout=httpx.Timeout(None, connect=5)) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.strip():
                    continue
                data = json.loads(line)
                if data.get("error"):
                    raise ValueError(data["error"])
                total, done = data.get("total"), data.get("completed")
                if total and done is not None and total > 50_000_000:  # the large weights layer
                    self.progress = done / total * 100
        self.progress = 100.0

    async def refresh_ps(self, c: httpx.AsyncClient | None = None) -> None:
        if self.kind != "ollama":
            return
        own = c is None
        c = c or httpx.AsyncClient(base_url=self.url, timeout=5)
        try:
            r = await c.get("/api/ps")
            for m in r.json().get("models", []):
                if m.get("name", "").split(":")[0] == self.derived or m.get("model", "").split(":")[0] == self.derived:
                    self.vram_bytes = m.get("size_vram")
                    self.size_bytes = m.get("size")
        except (httpx.HTTPError, ValueError):
            pass
        finally:
            if own:
                await c.aclose()


async def run_until_ready(mm: ModelManager, stop: asyncio.Event, retry_s: float = 10.0) -> None:
    while not stop.is_set():
        if await mm.ensure():
            return
        try:
            await asyncio.wait_for(stop.wait(), timeout=retry_s)
        except asyncio.TimeoutError:
            pass
