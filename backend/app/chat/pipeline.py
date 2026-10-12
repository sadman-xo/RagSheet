"""One chat turn.

guard -> register (route) -> memory and entities -> pre-check -> rules | acquire + planner -> policy -> tools
-> answer mode -> [acquire] -> answer -> grounding -> output scan -> save.

All answer modes run the same RBAC steps. The LLM only writes a plan and the answer text; the engine
calculates every number on the user's own scope file.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import AsyncIterator

import anyio
from anyio import to_thread

from app import audit
from app.cache import LRUCache
from app.chat import context, grounding, guard, memory, planner, policy, rule_parser, templates, tools
from app.chat.entities import parse
from app.chat.gateway_client import GenerationError, LeaseClient
from app.chat.plan import NARRATE_INTENTS, QueryPlan
from app.chat.prompts import PROMPT_VERSION
from app.config import get_settings
from app.db import engine as db
from app.rag import render as rag_render
from app.rag.retriever import retrieve
from app.security.deps import ScopedDataset, load_principal
from app.security.leakscan import LeakError, scan_answer, scan_prompt
from app.security.policy import build_scope

ANSWER_OPTIONS = {"temperature": 0.2, "num_predict": 200}
plan_cache = LRUCache(1024)
answer_cache = LRUCache(512)
_cpu = anyio.CapacityLimiter(4)


@dataclass
class TurnRequest:
    message: str
    turn_id: str
    parent_message_id: int | None = None
    explain_of: int | None = None
    session_id: int | None = None
    cache: bool = True


@dataclass
class TurnState:
    mode: str = "template"
    granted: bool = False
    shed_reason: str | None = None
    llm_calls: int = 0
    cache_hit: bool = False
    question_id: int | None = None
    answer_id: int | None = None
    session_id: int | None = None
    timings: dict = field(default_factory=dict)
    answer: str = ""
    finished: bool = False
    plan: QueryPlan | None = None
    sources: list = field(default_factory=list)


def ev(name: str, data) -> dict:
    return {"event": name, "data": json.dumps(data, default=str)}


def cache_key(kind: str, data_version: str, messages: list[dict], extra) -> str:
    s = get_settings()
    blob = json.dumps({"k": kind, "b": s.build_id, "p": PROMPT_VERSION, "d": data_version, "m": s.llm_model,
                       "o": extra, "msgs": messages}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


async def _cpu_call(fn, *args):
    return await to_thread.run_sync(lambda: fn(*args), limiter=_cpu)


async def _recheck(ds: ScopedDataset) -> bool:
    """After a GPU grant, the principal is read again: active, same token version, same scope."""
    p = await db.run_sync(lambda: load_principal(ds.principal.id))
    if p is None or p.token_version != ds.principal.token_version:
        return False
    try:
        return build_scope(p.role, p.region, p.category).fingerprint == ds.scope.fingerprint
    except Exception:
        return False


def _decide_mode(plan: QueryPlan, results: list[dict], explain: bool) -> str:
    if explain:
        return "narrate"
    if plan.intent == "clarify":
        return "template"
    if plan.intent in NARRATE_INTENTS:
        return "narrate"
    big_table = any(r.get("kind") == "table" and r.get("row_count", 0) > 5 and any(c["role"] == "dim" for c in r["columns"])
                    for r in results)
    if plan.intent in ("breakdown", "overview", "metric"):
        return "narrate" if big_table else "template"
    return "template"


async def run_turn(ds: ScopedDataset, req: TurnRequest, lease: LeaseClient | None, gateway_down: bool, flags: list[str],
                   req_info: audit.RequestInfo, state: TurnState) -> AsyncIterator[dict]:
    t0 = time.perf_counter()
    scope = ds.scope
    sf = ds.file
    today = sf.data_max
    audit_kw = {**audit.principal_fields(ds.principal, scope.scope_key), "req": req_info}

    def mark(name: str) -> None:
        state.timings[name] = round((time.perf_counter() - t0) * 1000, 1)

    yield ev("status", {"stage": "understanding"})
    mem = await db.run_sync(lambda: memory.load(ds.principal.id, scope.fingerprint, req.session_id, req.parent_message_id, req.message))
    state.session_id = mem.session_id
    if mem.new_session:
        yield ev("session", {"session_id": mem.session_id, "new": True})
    parsed = await _cpu_call(parse, req.message, scope, today)
    mark("entities")

    # Pre-check: only out-of-scope values or only hidden metrics -> fixed refusal, 0 LLM calls.
    refusal = policy.precheck(parsed, scope)
    if refusal:
        state.mode = "refusal"
        detail = {"out_of_scope": [e.value for e in parsed.out_of_scope_entities], "hidden_metrics": parsed.hidden_metrics,
                  "question": req.message[:300]}
        q, a = await db.run_sync(lambda: memory.save_refusal(ds.principal.id, mem.session_id, req.turn_id, req.message, refusal,
                                                             flags, req.parent_message_id, audit_kw, detail))
        state.question_id, state.answer_id, state.answer = q, a, refusal
        yield ev("token", {"text": refusal})
        mark("total")
        yield ev("done", {"mode": "refusal", "cache_hit": False, "message_id": a, "question_id": q, "session_id": mem.session_id,
                          "timings": state.timings, "llm_calls": 0})
        state.finished = True
        return

    # Plan: explain_of, rules, or the LLM planner.
    plan: QueryPlan
    explain = False
    parent = QueryPlan.model_validate(mem.parent_plan) if mem.parent_plan else None
    if req.explain_of:
        saved = await db.run_sync(lambda: memory.message_plan(ds.principal.id, req.explain_of))
        if saved:
            plan = QueryPlan.model_validate(saved).model_copy(update={"source": "explain"})
            explain = True
        else:
            plan = rule_parser.parse_rules(parsed, scope, today, parent)
    else:
        plan = rule_parser.parse_rules(parsed, scope, today, parent)
    mark("rules")
    # A question with a strong injection pattern never goes to the LLM (no planner, no narration).
    llm_allowed = not guard.blocks_llm(flags)
    if not explain and plan.confidence < 0.85:
        rule_plan = plan
        llm_plan = None
        if lease is not None and not gateway_down and llm_allowed:
            yield ev("status", {"stage": "planning"})
            async for e in lease.acquire():
                if e["type"] == "queued":
                    yield ev("status", {"stage": "queued", "queue_position": e["position"], "eta_s": e["eta_s"]})
                elif e["type"] == "granted":
                    state.granted = True
                elif e["type"] == "shed":
                    state.shed_reason = e.get("reason", "busy")
            if state.granted:
                if not await _recheck(ds):
                    yield ev("error", {"code": "SESSION_CHANGED", "message": "Your access changed. Please sign in again."})
                    state.mode = "error"
                    return
                yield ev("status", {"stage": "planning"})
                try:
                    llm_plan, info = await planner.plan_with_llm(
                        lease, req.message, parsed, scope, today, sf.data_min, mem.history,
                        parent.summary() if parent else None,
                        cache=plan_cache if req.cache else None,
                        cache_key_fn=lambda msgs, schema: cache_key("plan", sf.data_version, msgs, {"schema": schema}))
                    state.llm_calls += info.get("calls", 0)
                except LeakError as exc:
                    await db.run_sync(lambda: audit.record_now("leak_scan", **audit_kw, detail={"reason": exc.reason, "stage": "planner"}))
                    llm_plan = None
                mark("planner")
        if llm_plan is not None:
            plan = llm_plan
        elif rule_plan.confidence >= 0.5:
            plan = rule_plan
        elif rule_plan.intent == "semantic_search":
            plan = rule_plan
        else:
            plan = QueryPlan(intent="clarify", clarify="Can you say which metric, period, and group you mean? For example: "
                                                        "\"revenue by country in 2023\".", confidence=0.5)

    plan, notices = policy.apply(plan, parsed, scope)
    state.plan = plan
    yield ev("plan", {"intent": plan.intent, "summary": plan.summary(), "source": plan.source,
                      "specs": [s.model_dump(mode="json", exclude_none=True) for s in plan.specs]})
    for n in notices:
        yield ev("notice", {"text": n})

    results = await _cpu_call(tools.run, plan, ds)
    mark("tools")
    plan_json = plan.model_dump(mode="json", exclude_none=True)
    state.question_id = await db.run_sync(lambda: memory.save_question(ds.principal.id, mem.session_id, req.turn_id, req.message,
                                                                       plan_json, flags, req.parent_message_id, audit_kw))
    mode = _decide_mode(plan, results, explain) if llm_allowed else "template"
    if plan.intent == "semantic_search" and not results and llm_allowed:
        mode = "narrate"
    if mode == "template" and lease is not None and state.granted:
        await lease.release_slot()  # the planner used a slot; a template answer needs no GPU: free it before the data
        state.granted = False
    yield ev("data", {"results": results, "question_id": state.question_id})

    text = ""
    verification: dict | None = None
    if mode == "template":
        text = templates.answer(plan, results)
        state.mode = "template"
        yield ev("token", {"text": text})
    else:
        # Narrate: retrieval + context, leak scan, cache, then the GPU.
        yield ev("status", {"stage": "retrieving"})
        hits = await db.run_sync(lambda: retrieve(ds.principal.id, req.message, k=6))
        snippets = await _cpu_call(rag_render.render, hits, ds)
        state.sources = [{"ref": s["ref"], "title": s["title"], "kind": s["kind"], "deep_link": s["deep_link"],
                          "text": s["text"][:600]} for s in snippets]
        mark("retrieval")
        messages = context.build(req.message, scope, results, snippets[:4], notices, mem.history)
        kept = context.kept_snippets(messages)
        state.sources = [s for s in state.sources if s["ref"] in kept]
        try:
            scan_prompt(messages, scope)
        except LeakError as exc:
            await db.run_sync(lambda: audit.record_now("leak_scan", **audit_kw, detail={"reason": exc.reason, "stage": "answer"},
                                                       flags=["leak_scan"]))
            text = templates.answer(plan, results)
            state.mode = "template"
            yield ev("notice", {"text": "The AI explanation was stopped by a safety check. This is the direct result."})
            yield ev("token", {"text": text})
            messages = None
        if messages is not None:
            key = cache_key("answer", sf.data_version, messages, ANSWER_OPTIONS)
            cached = answer_cache.get(key) if req.cache else None
            if cached is not None:
                text = scan_answer(cached, scope)
                state.mode, state.cache_hit = "cache", True
                if lease is not None and state.granted:
                    await lease.release_slot()
                yield ev("token", {"text": text})
                verification = {"ok": True, "cached": True}
            else:
                down_reason = "unavailable" if (lease is None or gateway_down) else state.shed_reason
                if down_reason is None and not state.granted:
                    async for e in lease.acquire():
                        if e["type"] == "queued":
                            yield ev("status", {"stage": "queued", "queue_position": e["position"], "eta_s": e["eta_s"]})
                        elif e["type"] == "granted":
                            state.granted = True
                        elif e["type"] == "shed":
                            down_reason = e.get("reason", "busy")
                    if state.granted and not await _recheck(ds):
                        yield ev("error", {"code": "SESSION_CHANGED", "message": "Your access changed. Please sign in again."})
                        state.mode = "error"
                        return
                if down_reason is not None:
                    text, notice = templates.basic_answer(plan, results, down_reason)
                    state.mode = "basic_down" if down_reason in ("unavailable", "closed") else "basic_shed"
                    yield ev("notice", {"text": notice, "kind": "ai_busy" if state.mode == "basic_shed" else "ai_down"})
                    yield ev("token", {"text": text})
                else:
                    yield ev("status", {"stage": "writing"})
                    parts: list[str] = []
                    try:
                        async for e in lease.stream_answer(messages, ANSWER_OPTIONS):
                            if e["type"] == "token":
                                if not parts:
                                    mark("first_token")
                                parts.append(e["text"])
                                yield ev("token", {"text": e["text"]})
                        state.llm_calls += 1
                        text = "".join(parts).strip()
                        context_text = messages[-1]["content"]
                        verification = grounding.check(text, context_text)
                        masked = scan_answer(text, scope)
                        if not verification["ok"]:
                            text = templates.answer(plan, results)
                            state.mode = "ai_replaced"
                            yield ev("replace", {"text": text, "reason": "grounding"})
                        else:
                            state.mode = "ai"
                            if masked != text:
                                text = masked
                                yield ev("replace", {"text": text, "reason": "masking"})
                            if req.cache and text:
                                answer_cache.put(key, text)
                    except GenerationError:
                        text, notice = templates.basic_answer(plan, results, "unavailable")
                        state.mode = "basic_down"
                        yield ev("notice", {"text": notice, "kind": "ai_down"})
                        yield ev("replace", {"text": text, "reason": "llm_error"})
                    mark("answer")
        yield ev("sources", {"sources": state.sources})

    text = scan_answer(text, scope)
    state.answer = text
    if lease is not None:
        await lease.close()
    mark("total")
    state.answer_id = await db.run_sync(lambda: memory.save_answer(
        ds.principal.id, mem.session_id, req.turn_id, text, plan_json, state.sources, verification, state.mode,
        {**state.timings, "total_ms": state.timings.get("total"), "llm_calls": state.llm_calls}, flags, state.question_id))
    state.finished = True
    yield ev("done", {"mode": state.mode, "cache_hit": state.cache_hit, "message_id": state.answer_id,
                      "question_id": state.question_id, "session_id": mem.session_id, "timings": state.timings,
                      "llm_calls": state.llm_calls, "verification": verification})


async def cleanup(ds: ScopedDataset, req: TurnRequest, lease: LeaseClient | None, state: TurnState) -> None:
    """Shielded cleanup (2 s): close the lease; save a cancelled answer if the turn did not finish."""
    with anyio.CancelScope(shield=True), anyio.move_on_after(2.0):
        if lease is not None:
            await lease.close()
        if not state.finished and state.question_id is not None and state.session_id is not None:
            await db.run_sync(lambda: memory.save_answer(ds.principal.id, state.session_id, req.turn_id, state.answer or "(cancelled)",
                                                         state.plan.model_dump(mode="json", exclude_none=True) if state.plan else None,
                                                         state.sources, None, "cancelled", state.timings, [], state.question_id),
                              abandon_on_cancel=True)
