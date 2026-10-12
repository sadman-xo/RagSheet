"""Chat routes. The turn registers with the gateway before the SSE response starts, so 409 and 429 are real
HTTP statuses. If the gateway cannot be reached, the turn runs in basic mode (1 turn in flight per user and process)."""

from __future__ import annotations

import json
import threading
import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.api.errors import ApiError
from app.chat import gateway_client, guard, memory, pipeline
from app.config import get_settings
from app.db import engine as db
from app.security.deps import Principal, ScopedDataset, get_principal, get_scoped_dataset, request_info, require
from app.security.policy import Scope

router = APIRouter(prefix="/api/chat", tags=["chat"])
require_chat = require("chat")

_basic_lock = threading.Lock()
_basic_inflight: set[int] = set()


class ChatBody(BaseModel):
    message: str = Field(max_length=4000)
    turn_id: str = Field(default_factory=lambda: str(uuid.uuid4()), max_length=64)
    parent_message_id: int | None = None
    explain_of: int | None = None
    session_id: int | None = None
    cache: bool = True


class FeedbackBody(BaseModel):
    rating: int = Field(ge=-1, le=1)
    comment: str | None = Field(default=None, max_length=1000)


async def _prepare(body: ChatBody, request: Request, ds: ScopedDataset):
    try:
        text, flags = guard.check(body.message)
    except guard.GuardError as exc:
        raise ApiError(exc.status, exc.code, str(exc))
    try:
        uuid.UUID(body.turn_id)
    except ValueError:
        raise ApiError(422, "INVALID_TURN_ID", "turn_id must be a UUID.")
    # cache=false is allowed only for the admin or in DEMO_MODE (the eval uses it).
    allow_no_cache = ds.principal.role == "admin" or get_settings().demo_mode
    req = pipeline.TurnRequest(message=text, turn_id=body.turn_id, parent_message_id=body.parent_message_id,
                               explain_of=body.explain_of, session_id=body.session_id, cache=body.cache or not allow_no_cache)
    lease = None
    down = False
    try:
        lease = await gateway_client.register(ds.principal.id, body.turn_id)
    except gateway_client.GatewayRejected as exc:
        code = "TURN_IN_FLIGHT" if exc.status == 409 else "TOO_MANY_TURNS"
        msg = ("A question is still running. Wait for its answer." if exc.status == 409
               else "Too many questions. Wait a moment and try again.")
        raise ApiError(exc.status, code, msg, {"reason": exc.reason}, headers={"Retry-After": str(max(1, int(exc.retry_after + 0.99)))})
    except gateway_client.GatewayDown:
        down = True
        with _basic_lock:
            if ds.principal.id in _basic_inflight:
                raise ApiError(409, "TURN_IN_FLIGHT", "A question is still running. Wait for its answer.", headers={"Retry-After": "1"})
            _basic_inflight.add(ds.principal.id)
    return req, lease, down, flags


def _release_basic(user_id: int, down: bool) -> None:
    if down:
        with _basic_lock:
            _basic_inflight.discard(user_id)


@router.post("/stream")
async def stream(body: ChatBody, request: Request, ds: ScopedDataset = Depends(get_scoped_dataset),
                 _scope: Scope = Depends(require_chat)):
    req, lease, down, flags = await _prepare(body, request, ds)
    state = pipeline.TurnState()
    info = request_info(request)

    async def gen():
        try:
            async for e in pipeline.run_turn(ds, req, lease, down, flags, info, state):
                yield e
        except Exception as exc:  # never leak details
            print(f"chat turn error: {type(exc).__name__}: {exc}", flush=True)
            yield pipeline.ev("error", {"code": "TURN_FAILED", "message": "The answer could not be completed. Please try again."})
        finally:
            await pipeline.cleanup(ds, req, lease, state)
            _release_basic(ds.principal.id, down)

    return EventSourceResponse(gen(), ping=15, headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/ask")
async def ask(body: ChatBody, request: Request, ds: ScopedDataset = Depends(get_scoped_dataset),
              _scope: Scope = Depends(require_chat)) -> dict:
    req, lease, down, flags = await _prepare(body, request, ds)
    state = pipeline.TurnState()
    out: dict = {"answer": "", "notices": [], "results": [], "sources": [], "plan": None, "statuses": [], "replaced": False}
    try:
        async for e in pipeline.run_turn(ds, req, lease, down, flags, request_info(request), state):
            data = json.loads(e["data"])
            name = e["event"]
            if name == "token":
                out["answer"] += data["text"]
            elif name == "replace":
                out["answer"] = data["text"]
                out["replaced"] = True
            elif name == "notice":
                out["notices"].append(data["text"])
            elif name == "data":
                out["results"] = data["results"]
            elif name == "sources":
                out["sources"] = data["sources"]
            elif name == "plan":
                out["plan"] = data
            elif name == "status":
                out["statuses"].append(data)
            elif name in ("done", "error"):
                out[name] = data
    finally:
        await pipeline.cleanup(ds, req, lease, state)
        _release_basic(ds.principal.id, down)
    out["mode"] = (out.get("done") or {}).get("mode", state.mode)
    return out


LABELS = {"ready": "AI ready", "busy": "AI busy", "downloading": "AI model downloading", "loading": "AI model loading",
          "unavailable": "AI not available (basic answers)", "basic": "AI not available (basic answers)"}


@router.get("/status")
async def status(_p: Principal = Depends(get_principal), _scope: Scope = Depends(require_chat)) -> dict:
    st = await gateway_client.status()
    if not st.get("available"):
        return {"state": "basic", "label": LABELS["basic"], "progress": None, "queue": 0}
    state = st.get("state", "unavailable")
    return {"state": state if state in LABELS else "basic", "label": LABELS.get(state, LABELS["basic"]),
            "progress": st.get("pull_progress"), "queue": st.get("queue_length", 0), "eta_s": st.get("ewma_s"),
            "model": st.get("model")}


def suggestions_for(scope: Scope, role: str) -> list[str]:
    if not scope.all_regions:
        r = scope.region
        return [f"Which countries in {r} had the highest revenue in 2023?", "How did my revenue develop by month in 2024?",
                "What is the return rate by country?", "Electronics revenue in Q3 2023", "Why did revenue drop in 2024?",
                "Top 5 products by profit", "What can I see?"]
    if not scope.all_categories:
        return [f"Top 5 products in {scope.category} by profit", "At which discount level do orders lose money?",
                "Revenue by sub-category in 2023", "How did revenue change in 2024 vs 2023?", "Return rate by sub-category",
                "Which region buys the most?", "What can I see?"]
    if not scope.financial:
        return ["What is the return rate by shipping method?", "Is overnight shipping faster than economy?",
                "How many orders are still processing?", "Cancellation rate by payment method", "Show me the latest cancelled orders",
                "Average shipping days by region", "What can I see?"]
    if not scope.pii_raw:
        return ["Repeat customer rate by segment", "Average order value by year", "Which country had the highest return rate?",
                "Top 10 customers by revenue", "Compare the margin of 2022 and 2023", "Revenue by payment method"]
    return ["What was the gross revenue in 2023?", "Which region had the highest revenue in 2024?", "Why did revenue drop in 2024?",
            "Compare the margin of 2022 and 2023", "Top 5 products by profit", "What does net revenue mean?",
            "What are the known data quality problems?"]


@router.get("/suggestions")
def suggestions(principal: Principal = Depends(get_principal), scope: Scope = Depends(require_chat)) -> dict:
    return {"suggestions": suggestions_for(scope, principal.role)}


@router.get("/sessions")
async def sessions(principal: Principal = Depends(get_principal), _scope: Scope = Depends(require_chat)) -> dict:
    return {"sessions": await db.run_sync(lambda: memory.sessions(principal.id))}


@router.get("/sessions/{session_id}")
async def session(session_id: int, principal: Principal = Depends(get_principal), scope: Scope = Depends(require_chat)) -> dict:
    s = await db.run_sync(lambda: memory.session_messages(principal.id, session_id, scope.fingerprint))
    if s is None:
        raise ApiError(404, "NOT_FOUND", "Session not found.")
    return s


@router.post("/messages/{message_id}/feedback")
async def feedback(message_id: int, body: FeedbackBody, principal: Principal = Depends(get_principal),
                   _scope: Scope = Depends(require_chat)) -> dict:
    if body.rating == 0:
        raise ApiError(422, "INVALID_RATING", "Rating must be -1 or 1.")
    ok = await db.run_sync(lambda: memory.feedback(principal.id, message_id, body.rating, body.comment))
    if not ok:
        raise ApiError(404, "NOT_FOUND", "Message not found.")
    return {"ok": True}
