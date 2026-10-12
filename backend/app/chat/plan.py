"""QueryPlan: what the turn does. The rule parser or the LLM planner writes it; code checks and runs it.

The LLM never writes SQL and never sees data while it plans. The JSON schema allows only the metrics of
the user's role and only known dimensions and values.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.analytics.dimensions import DIMENSIONS, FILTERS, TIME_GRAINS
from app.analytics.metrics import METRICS
from app.analytics.spec import CompareMode, Filters, QuerySpec
from app.security.policy import Scope

Intent = Literal["metric", "breakdown", "trend", "compare", "why", "list_orders", "lookup_order", "overview",
                 "definition", "data_quality", "access", "semantic_search", "clarify"]
TEMPLATE_INTENTS = {"metric", "lookup_order", "definition", "access", "data_quality", "list_orders", "overview"}
NARRATE_INTENTS = {"compare", "trend", "why", "semantic_search"}


class PlanSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = ""
    metrics: list[str] = Field(min_length=1, max_length=6)
    group_by: list[str] = Field(default_factory=list, max_length=2)
    time_grain: str | None = None
    filters: Filters = Field(default_factory=Filters)
    compare: CompareMode = "none"
    sort_by: str | None = None
    sort_dir: Literal["asc", "desc"] | None = None
    limit: int = Field(default=10, ge=1, le=500)

    def query_spec(self) -> QuerySpec:
        return QuerySpec(metrics=self.metrics, group_by=self.group_by, time_grain=self.time_grain, filters=self.filters,
                         compare=self.compare, sort_by=self.sort_by, sort_dir=self.sort_dir, limit=self.limit)


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Intent
    specs: list[PlanSpec] = Field(default_factory=list, max_length=3)
    order_id: str | None = None
    order_filters: Filters | None = None
    metric: str | None = None
    topic: str | None = None
    clarify: str | None = None
    confidence: float = 0.0
    source: str = "rule"

    def summary(self) -> str:
        parts = [self.intent]
        for s in self.specs:
            bits = [", ".join(METRICS[m].label for m in s.metrics)]
            if s.time_grain:
                bits.append(f"by {DIMENSIONS[s.time_grain].label.lower()}")
            if s.group_by:
                bits.append("by " + ", ".join(DIMENSIONS[d].label.lower() for d in s.group_by))
            f = s.filters.active()
            if f:
                bits.append("for " + "; ".join(f"{k}={','.join(map(str, v)) if isinstance(v, list) else v}" for k, v in f.items()))
            if s.compare != "none":
                bits.append({"prior_year_lfl": "vs same period last year", "prior_period": "vs prior period"}[s.compare])
            parts.append(" ".join(bits))
        if self.order_id:
            parts.append(self.order_id)
        if self.metric:
            parts.append(self.metric)
        return " · ".join(parts)


def _filter_schema(scope: Scope) -> dict:
    allowed = {"regions": list(scope.regions), "countries": list(scope.countries), "categories": list(scope.categories),
               "sub_categories": list(scope.sub_categories), "products": list(scope.products)}
    props: dict = {}
    for name, (_dim, values) in FILTERS.items():
        if name in ("price_bands", "shipping_days_bands", "year_months"):
            continue
        vals = allowed.get(name, list(values) if values else None)
        item = {"type": "integer"} if name in ("years", "quarters", "months") else {"type": "string"}
        if vals is not None and item["type"] == "string":
            item["enum"] = vals
        if name == "years":
            item = {"type": "integer", "minimum": 2000, "maximum": 2100}
        props[name] = {"type": "array", "items": item}
    return {"type": "object", "properties": props, "additionalProperties": False}


def planner_schema(scope: Scope) -> dict:
    """Compact JSON schema for the LLM planner (role-limited metrics, in-scope values)."""
    metric_ids = scope.allowed_metrics()
    dims = [d for d in DIMENSIONS if not DIMENSIONS[d].time_grain and d != "customer_id"]
    flt = _filter_schema(scope)
    return {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": ["metric", "breakdown", "trend", "compare", "why", "list_orders",
                                                  "overview", "definition", "data_quality", "semantic_search", "clarify"]},
            "metrics": {"type": "array", "items": {"type": "string", "enum": metric_ids}, "maxItems": 4},
            "group_by": {"type": "array", "items": {"type": "string", "enum": dims}, "maxItems": 2},
            "time_grain": {"type": ["string", "null"], "enum": [*TIME_GRAINS, None]},
            "filters": flt,
            "compare": {"type": "string", "enum": ["none", "prior_year_lfl", "prior_period", "two_periods"]},
            "compare_filters": flt,
            "sort": {"type": "string", "enum": ["desc", "asc", "none"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            "clarify_question": {"type": ["string", "null"]},
        },
        "required": ["intent", "metrics", "group_by", "time_grain", "filters", "compare", "sort", "limit"],
        "additionalProperties": False,
    }
