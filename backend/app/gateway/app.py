"""LLM gateway HTTP service (one process, internal network only, no database access).

Two-phase lease protocol (header X-Gateway-Token):
1. POST /v1/turn {user_id, turn_id}: NDJSON lease stream. First line: registered or rejected{status, retry_after}.
   The stream stays open; when it closes, the gateway cancels the turn's tasks, then frees the slot and the lease.
2. POST /v1/turn/{id}/acquire: NDJSON queued{position, eta_s} every 2 s, then granted{endpoint} or shed{reason}.
3. POST /v1/turn/{id}/generate: a planner JSON call, or a streamed answer (NDJSON tokens), on the granted endpoint.
4. POST /v1/turn/{id}/release_slot: frees the slot and keeps the lease.
"""

from __future__ import annotations

import asyncio
import hmac
import json
from contextlib import asynccontextmanager
from typing import AsyncIterator

import anyio
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.config import Settings, get_settings, read_secret
from app.gateway.admission import Gateway, GatewayError, Lease, Rejection
from app.gateway.breaker import Breaker
from app.gateway.endpoints import Endpoint
from app.gateway.model_manager import ModelManager, run_until_ready
from app.gateway.providers import make_provider

PING_S = 5.0


class TurnBody(BaseModel):
    user_id: str = Field(max_length=64)
    turn_id: str = Field(max_length=64)


class GenerateBody(BaseModel):
    kind: str = Field(pattern="^(plan|answer)$")
    messages: list[dict]
    json_schema: dict | None = None
    options: dict = Field(default_factory=dict)


def build_endpoints(s: Settings) -> list[Endpoint]:
    options = {"num_ctx": s.llm_num_ctx, "num_thread": s.llm_num_thread, "num_batch": s.llm_num_batch}
    out = []
    for i, cfg in enumerate(s.llm_endpoint_list()):
        kind = cfg.get("provider", "ollama")
        url = cfg["url"]
        model = cfg.get("model", s.llm_model)
        mm = ModelManager(kind, url, model, options if kind == "ollama" else {}, auto_pull=s.auto_pull_model)
        out.append(Endpoint(name=cfg.get("name", f"ep{i + 1}"), provider_kind=kind, url=url, base_model=model,
                            slots=int(cfg.get("slots", 1)), provider=make_provider(kind, url), manager=mm,
                            breaker=Breaker(threshold=3, cooldown_s=30.0)))
    return out


def _line(obj: dict) -> bytes:
    return (json.dumps(obj) + "\n").encode()


async def _monitor(gw: Gateway, stop: asyncio.Event) -> None:
    """Model managers, breaker probes, VRAM refresh, and the lease reaper."""
    tasks = [asyncio.create_task(run_until_ready(e.manager, stop)) for e in gw.endpoints if e.manager]
    last_ps = 0.0
    loop = asyncio.get_running_loop()
    try:
        while not stop.is_set():
            for e in gw.endpoints:
                if e.breaker.probe_due() and await e.provider.health():
                    if e.manager is None or await e.manager.ensure():
                        e.breaker.success()
                        gw.dispatch()
                elif e.manager and e.manager.state in ("error",) and not stop.is_set():
                    if await e.manager.ensure():
                        gw.dispatch()
            if loop.time() - last_ps > 30:
                last_ps = loop.time()
                for e in gw.endpoints:
                    if e.manager and e.manager.state == "ready":
                        await e.manager.refresh_ps()
            await gw.reap()
            gw.dispatch()
            try:
                await asyncio.wait_for(stop.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass
    finally:
        for t in tasks:
            t.cancel()


def create_app(gateway: Gateway | None = None, token: str | None = None, run_monitor: bool = True) -> FastAPI:
    state: dict = {"gw": gateway, "token": token}

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        s = get_settings()
        if state["gw"] is None:
            state["gw"] = Gateway(build_endpoints(s), max_wait_s=s.llm_max_wait_s, turn_estimate_s=s.llm_turn_estimate_s,
                                  turns_per_minute=s.chat_turns_per_minute, gpu_turns_per_minute=s.chat_gpu_turns_per_minute)
        if state["token"] is None:
            state["token"] = read_secret(s.secrets_gw_dir, "gateway_token")
        stop = asyncio.Event()
        mon = asyncio.create_task(_monitor(state["gw"], stop)) if run_monitor else None
        yield
        stop.set()
        if mon:
            mon.cancel()
            await asyncio.gather(mon, return_exceptions=True)
        for e in state["gw"].endpoints:
            await e.provider.aclose()

    app = FastAPI(title="Panorama LLM gateway", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    def gw() -> Gateway:
        return state["gw"]

    def check(token: str | None) -> None:
        if not token or not hmac.compare_digest(token, state["token"] or ""):
            raise HTTPException(status_code=401, detail="bad gateway token")

    def lease_of(turn_id: str) -> Lease:
        lease = gw().leases.get(turn_id)
        if lease is None:
            raise HTTPException(status_code=410, detail="lease closed")
        return lease

    @app.exception_handler(GatewayError)
    async def _gwerr(_r: Request, exc: GatewayError):
        return JSONResponse(status_code=exc.status, content={"error": exc.code, "message": str(exc)})

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/v1/status")
    async def status(x_gateway_token: str | None = Header(default=None)) -> dict:
        check(x_gateway_token)
        return gw().status()

    @app.post("/v1/turn")
    async def turn(body: TurnBody, x_gateway_token: str | None = Header(default=None)):
        check(x_gateway_token)
        res = gw().register(body.user_id, body.turn_id)
        if isinstance(res, Rejection):
            return StreamingResponse(iter([_line({"type": "rejected", "status": res.status, "reason": res.reason,
                                                  "retry_after": round(res.retry_after, 1)})]),
                                     media_type="application/x-ndjson")
        lease = res

        async def stream() -> AsyncIterator[bytes]:
            try:
                yield _line({"type": "registered", "turn_id": lease.turn_id})
                while lease.state != "closed":
                    await asyncio.sleep(PING_S)
                    yield _line({"type": "ping", "state": lease.state})
            finally:
                with anyio.CancelScope(shield=True):
                    await gw().close(lease)

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    @app.post("/v1/turn/{turn_id}/acquire")
    async def acquire(turn_id: str, x_gateway_token: str | None = Header(default=None)):
        check(x_gateway_token)
        lease = lease_of(turn_id)

        async def stream() -> AsyncIterator[bytes]:
            agen = gw().acquire(lease)
            try:
                async for ev in agen:
                    yield _line(ev)
            finally:
                with anyio.CancelScope(shield=True):
                    await agen.aclose()

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    @app.post("/v1/turn/{turn_id}/generate")
    async def generate(turn_id: str, body: GenerateBody, x_gateway_token: str | None = Header(default=None)):
        check(x_gateway_token)
        lease = lease_of(turn_id)
        if body.kind == "plan":
            content, stats = await gw().generate_json(lease, body.messages, body.json_schema or {"type": "object"}, body.options)
            return {"content": content, "endpoint": lease.endpoint.name if lease.endpoint else None,
                    "stats": {"seconds": round(stats.seconds, 2), "output_tokens": stats.output_tokens,
                              "prompt_tokens": stats.prompt_tokens, "tokens_per_s": stats.tokens_per_s}}
        gw()._check_granted(lease)  # fail fast with a real HTTP status

        async def stream() -> AsyncIterator[bytes]:
            try:
                async for ev in gw().generate_stream(lease, body.messages, body.options):
                    yield _line(ev)
            except GatewayError as exc:
                yield _line({"type": "error", "status": exc.status, "code": exc.code})

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    @app.post("/v1/turn/{turn_id}/release_slot")
    async def release_slot(turn_id: str, x_gateway_token: str | None = Header(default=None)) -> dict:
        check(x_gateway_token)
        lease = lease_of(turn_id)
        await gw().release_slot(lease)
        return {"ok": True}

    app.state.panorama = state
    return app


app = create_app()
