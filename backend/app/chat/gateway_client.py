"""Client for the LLM gateway (the api never calls an LLM server directly).

Gateway down: 1 s connect timeout and 3 s admission read timeout. Then the turn runs in basic mode.
"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

import httpx

from app.config import app_secret, get_settings

CONNECT_TIMEOUT = 1.0
ADMISSION_TIMEOUT = 3.0

_client: httpx.AsyncClient | None = None


class GatewayDown(Exception):
    """The gateway cannot be reached."""


class GatewayRejected(Exception):
    def __init__(self, status: int, reason: str, retry_after: float = 0.0):
        super().__init__(reason)
        self.status = status
        self.reason = reason
        self.retry_after = retry_after


class GenerationError(Exception):
    """The LLM call failed (the turn continues in basic mode)."""


def _headers() -> dict:
    return {"X-Gateway-Token": app_secret("gateway_token")}


async def startup() -> None:
    global _client
    if _client is None:
        s = get_settings()
        _client = httpx.AsyncClient(
            base_url=s.gateway_url,
            timeout=httpx.Timeout(120.0, connect=CONNECT_TIMEOUT),
            limits=httpx.Limits(max_connections=400, max_keepalive_connections=50),
        )


async def shutdown() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def set_client(client: httpx.AsyncClient | None) -> None:
    """Tests use an in-process transport."""
    global _client
    _client = client


async def client() -> httpx.AsyncClient:
    if _client is None:
        await startup()
    return _client  # type: ignore[return-value]


class LeaseClient:
    def __init__(self, turn_id: str, resp: httpx.Response, lines: AsyncIterator[str]):
        self.turn_id = turn_id
        self._resp = resp
        self._lines = lines
        self.granted = False
        self.endpoint: str | None = None
        self.lost = False
        self.closed = False
        self._reader = asyncio.create_task(self._read())

    async def _read(self) -> None:
        try:
            async for _line in self._lines:
                pass
        except (httpx.HTTPError, asyncio.CancelledError):
            pass
        finally:
            if not self.closed:
                self.lost = True

    async def acquire(self) -> AsyncIterator[dict]:
        c = await client()
        try:
            async with c.stream("POST", f"/v1/turn/{self.turn_id}/acquire", headers=_headers(),
                                timeout=httpx.Timeout(60.0, connect=CONNECT_TIMEOUT)) as r:
                if r.status_code != 200:
                    yield {"type": "shed", "reason": "unavailable"}
                    return
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    ev = json.loads(line)
                    if ev.get("type") == "granted":
                        self.granted = True
                        self.endpoint = ev.get("endpoint")
                    yield ev
                    if ev.get("type") in ("granted", "shed"):
                        return
        except httpx.HTTPError:
            yield {"type": "shed", "reason": "unavailable"}

    async def plan(self, messages: list[dict], schema: dict, options: dict) -> dict:
        c = await client()
        try:
            r = await c.post(f"/v1/turn/{self.turn_id}/generate", headers=_headers(),
                             json={"kind": "plan", "messages": messages, "json_schema": schema, "options": options})
        except httpx.HTTPError as exc:
            raise GenerationError(str(exc)) from exc
        if r.status_code != 200:
            raise GenerationError(f"gateway {r.status_code}")
        return r.json()

    async def stream_answer(self, messages: list[dict], options: dict) -> AsyncIterator[dict]:
        c = await client()
        try:
            async with c.stream("POST", f"/v1/turn/{self.turn_id}/generate", headers=_headers(),
                                json={"kind": "answer", "messages": messages, "options": options}) as r:
                if r.status_code != 200:
                    raise GenerationError(f"gateway {r.status_code}")
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    ev = json.loads(line)
                    if ev.get("type") == "error":
                        raise GenerationError(ev.get("code", "llm_error"))
                    yield ev
        except httpx.HTTPError as exc:
            raise GenerationError(str(exc)) from exc

    async def release_slot(self) -> None:
        if not self.granted:
            return
        self.granted = False
        c = await client()
        try:
            await c.post(f"/v1/turn/{self.turn_id}/release_slot", headers=_headers(), timeout=5.0)
        except httpx.HTTPError:
            pass

    async def close(self) -> None:
        """Close the lease stream: the gateway cancels any upstream call, then frees the slot."""
        if self.closed:
            return
        self.closed = True
        self._reader.cancel()
        try:
            await self._resp.aclose()
        except Exception:
            pass
        await asyncio.gather(self._reader, return_exceptions=True)


async def register(user_id: int, turn_id: str) -> LeaseClient:
    c = await client()
    try:
        req = c.build_request("POST", "/v1/turn", json={"user_id": str(user_id), "turn_id": turn_id}, headers=_headers(),
                              timeout=httpx.Timeout(None, connect=CONNECT_TIMEOUT))
        resp = await asyncio.wait_for(c.send(req, stream=True), timeout=ADMISSION_TIMEOUT)
    except (httpx.HTTPError, asyncio.TimeoutError, OSError) as exc:
        raise GatewayDown(str(exc) or type(exc).__name__) from exc
    if resp.status_code != 200:
        await resp.aclose()
        raise GatewayDown(f"gateway status {resp.status_code}")
    lines = resp.aiter_lines()
    try:
        first = await asyncio.wait_for(lines.__anext__(), timeout=ADMISSION_TIMEOUT)
    except (asyncio.TimeoutError, StopAsyncIteration, httpx.HTTPError) as exc:
        await resp.aclose()
        raise GatewayDown("no admission answer") from exc
    ev = json.loads(first)
    if ev.get("type") == "rejected":
        await resp.aclose()
        raise GatewayRejected(int(ev.get("status", 429)), ev.get("reason", "rejected"), float(ev.get("retry_after", 0)))
    return LeaseClient(turn_id, resp, lines)


async def status() -> dict:
    c = await client()
    try:
        r = await c.get("/v1/status", headers=_headers(), timeout=httpx.Timeout(2.0, connect=CONNECT_TIMEOUT))
        r.raise_for_status()
        return {"available": True, **r.json()}
    except (httpx.HTTPError, ValueError) as exc:
        return {"available": False, "error": type(exc).__name__}
