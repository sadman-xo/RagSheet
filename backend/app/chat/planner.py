"""LLM planner: the model writes a JSON plan (temperature 0, schema-constrained); code validates it.

If validation fails: one repair, then the rule plan, then a clarification question. Detected entities replace the
LLM slot values, and values that the question does not name are removed (no invented filters).
"""

from __future__ import annotations

import json
from datetime import date

from pydantic import ValidationError

from app.analytics.dimensions import DIMENSIONS
from app.analytics.metrics import METRICS
from app.analytics.spec import Filters
from app.chat import prompts
from app.chat.entities import Parsed
from app.chat.gateway_client import GenerationError, LeaseClient
from app.chat.plan import PlanSpec, QueryPlan, planner_schema
from app.security.leakscan import scan_prompt
from app.security.policy import Scope

PLANNER_OPTIONS = {"temperature": 0, "num_predict": 300}
VOCAB_FIELDS = ("regions", "countries", "categories", "sub_categories", "products", "segments", "genders", "statuses",
                "shipping_methods", "payment_methods", "discount_bands")
TIME_FIELDS = ("years", "quarters", "months", "date_from", "date_to", "year_months")


def _clean_filters(raw: dict | None, p: Parsed) -> Filters:
    raw = dict(raw or {})
    named = p.filters(only_in_scope=False)
    out: dict = {}
    for k in VOCAB_FIELDS:
        if k in named:
            out[k] = named[k]  # detected entities replace the LLM values
        elif raw.get(k) and k in ("discount_bands",) and any(str(v).rstrip("%") in p.lower for v in raw[k]):
            out[k] = raw[k]
    # Time filters come only from the question (the code parses them); the LLM cannot invent a period.
    for k in TIME_FIELDS:
        if k in p.time:
            out[k] = p.time[k]
    try:
        return Filters(**out)
    except ValidationError:
        return Filters()


def to_plan(data: dict, p: Parsed, scope: Scope) -> QueryPlan:
    intent = data.get("intent", "semantic_search")
    if intent == "clarify":
        return QueryPlan(intent="clarify", clarify=(data.get("clarify_question") or "Can you say more precisely what you need?")[:300],
                         confidence=0.6, source="llm")
    metrics = [m for m in data.get("metrics") or [] if m in METRICS and m in scope.allowed_metrics()]
    if p.metrics:  # metrics named in the question win
        metrics = p.metrics[:4]
    if not metrics and intent not in ("definition", "data_quality", "semantic_search", "list_orders"):
        metrics = ["gross_revenue", "orders"]
    group_by = [d for d in (data.get("group_by") or []) if d in DIMENSIONS and not DIMENSIONS[d].time_grain][:2]
    if p.dims:
        group_by = p.dims[:2]
    grain = data.get("time_grain") if data.get("time_grain") in DIMENSIONS else None
    grain = p.grain or grain
    if intent == "trend" and not grain:
        grain = "year_month"
    filters = _clean_filters(data.get("filters"), p)
    sort = data.get("sort") if data.get("sort") in ("asc", "desc") else None
    limit = int(data.get("limit") or 10)
    limit = max(1, min(limit, 50))
    compare = data.get("compare", "none")
    if intent == "definition":
        mid = (metrics or p.metrics or [None])[0]
        return QueryPlan(intent="definition", metric=mid, confidence=0.8, source="llm")
    if intent in ("data_quality", "semantic_search", "overview") and not metrics:
        return QueryPlan(intent=intent, confidence=0.8, source="llm")
    if intent == "list_orders":
        return QueryPlan(intent="list_orders", order_filters=filters, confidence=0.8, source="llm")
    specs: list[PlanSpec] = []
    sort_by = metrics[0] if sort else None
    if compare == "two_periods":
        f2 = _clean_filters(data.get("compare_filters"), p)
        if len(p.years) >= 2:
            base = filters.model_dump(exclude_none=True)
            for k in TIME_FIELDS:
                base.pop(k, None)
            specs = [PlanSpec(title=str(y), metrics=metrics, group_by=group_by, filters=Filters(**base, years=[y])) for y in p.years[:2]]
        else:
            specs = [PlanSpec(title="Period A", metrics=metrics, group_by=group_by, filters=filters),
                     PlanSpec(title="Period B", metrics=metrics, group_by=group_by, filters=f2)]
    else:
        cmp = compare if compare in ("prior_year_lfl", "prior_period") else "none"
        specs = [PlanSpec(title="Result", metrics=metrics, group_by=group_by, time_grain=grain, filters=filters, compare=cmp,
                          sort_by=sort_by, sort_dir=sort, limit=500 if grain else limit)]
        if intent == "why" and group_by and cmp != "none":
            specs.insert(0, PlanSpec(title="Total", metrics=metrics, filters=filters, compare=cmp))
    mapped = {"metric": "metric", "breakdown": "breakdown", "trend": "trend", "compare": "compare", "why": "why",
              "overview": "overview", "semantic_search": "semantic_search"}.get(intent, "metric")
    if mapped == "metric" and group_by:
        mapped = "breakdown"
    return QueryPlan(intent=mapped, specs=specs, confidence=0.8, source="llm")


async def plan_with_llm(lease: LeaseClient, question: str, p: Parsed, scope: Scope, today: date, data_min: date,
                        history: list[str], parent_summary: str | None, cache=None, cache_key_fn=None) -> tuple[QueryPlan | None, dict]:
    """Return (plan or None, info). info has timings and the raw content for the audit."""
    messages = prompts.planner_messages(question, scope, today, data_min, history, parent_summary)
    scan_prompt(messages, scope)
    schema = planner_schema(scope)
    info: dict = {"calls": 0}
    key = cache_key_fn(messages, schema) if cache_key_fn else None
    if cache is not None and key is not None:
        hit = cache.get(key)
        if hit is not None:
            info["cache"] = True
            try:
                return to_plan(json.loads(hit), p, scope), info
            except (ValueError, ValidationError):
                pass
    for attempt in (1, 2):
        try:
            resp = await lease.plan(messages, schema, PLANNER_OPTIONS)
        except GenerationError as exc:
            info["error"] = str(exc)
            return None, info
        info["calls"] += 1
        info["seconds"] = info.get("seconds", 0) + (resp.get("stats") or {}).get("seconds", 0)
        content = resp.get("content", "")
        try:
            data = json.loads(content)
            plan = to_plan(data, p, scope)
            if cache is not None and key is not None:
                cache.put(key, content)
            return plan, info
        except (ValueError, ValidationError, TypeError) as exc:
            info["invalid"] = str(exc)[:200]
            messages = messages + [{"role": "assistant", "content": content[:2000]}, prompts.repair_message(str(exc))]
    return None, info
