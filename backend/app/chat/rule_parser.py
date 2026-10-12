"""Rule parser: about 15 patterns that turn common questions into a plan without the LLM.

If the confidence is 0.85 or more, the turn skips the LLM planner (no GPU for the plan).
"""

from __future__ import annotations

import re
from datetime import date

from app.analytics.metrics import METRICS
from app.analytics.spec import Filters
from app.chat.entities import Parsed
from app.chat.plan import PlanSpec, QueryPlan
from app.security.policy import Scope

TIME_KEYS = ("years", "quarters", "months", "year_months", "date_from", "date_to")
FOLLOWUP_RE = re.compile(r"^\s*(?:and|what about|how about|same for|same but|now|then|ok,?|also|but)\b|^\s*(?:in|for)\s+\S+\??\s*$", re.I)


def _default_metrics(p: Parsed, scope: Scope) -> list[str]:
    if p.metrics:
        return p.metrics[:4]
    return ["gross_revenue", "orders"]


def _driver_dim(scope: Scope, p: Parsed) -> str:
    """The dimension that explains a change best for this scope."""
    used = {e.field for e in p.in_scope_entities}
    if not scope.all_regions:
        return "country" if "countries" not in used else "category"
    if not scope.all_categories:
        return "sub_category" if "sub_categories" not in used and "products" not in used else "region"
    if "regions" in used or "countries" in used:
        return "category"
    return "region"


def _filters(p: Parsed, extra: dict | None = None, drop_time: bool = False) -> Filters:
    f = p.filters(only_in_scope=True)
    if drop_time:
        for k in TIME_KEYS:
            f.pop(k, None)
    if extra:
        f.update(extra)
    return Filters(**f)


def _limit(p: Parsed, default: int = 10) -> int:
    if p.top_n:
        return min(p.top_n, 50)
    if p.has("superlative"):
        return 5
    return default


def _merge_followup(parent: QueryPlan, p: Parsed) -> QueryPlan | None:
    if not parent.specs:
        return None
    new_f = p.filters(only_in_scope=True)
    specs = []
    for s in parent.specs:
        f = s.filters.model_dump(exclude_none=True)
        if any(k in new_f for k in TIME_KEYS):
            for k in TIME_KEYS:
                f.pop(k, None)
        for k, v in new_f.items():
            f[k] = v
            if k == "regions":
                f.pop("countries", None)
            if k == "categories":
                f.pop("sub_categories", None)
                f.pop("products", None)
            if k == "sub_categories":
                f.pop("products", None)
        metrics = p.metrics[:4] if p.metrics else s.metrics
        group_by = p.dims[:2] if p.dims else s.group_by
        specs.append(s.model_copy(update={"filters": Filters(**f), "metrics": metrics, "group_by": group_by,
                                          "time_grain": p.grain or s.time_grain}))
    return parent.model_copy(update={"specs": specs, "confidence": 0.9, "source": "followup"})


def parse_rules(p: Parsed, scope: Scope, today: date, parent: QueryPlan | None = None) -> QueryPlan:
    words = len(p.text.split())
    # 1. order lookup
    if p.order_ids:
        return QueryPlan(intent="lookup_order", order_id=p.order_ids[0], confidence=0.97)
    # 2. access
    if p.has("access"):
        return QueryPlan(intent="access", confidence=0.95)
    # 3. data quality
    if p.has("data_quality") and not p.metrics:
        return QueryPlan(intent="data_quality", confidence=0.9)
    # 4. definition
    if p.has("definition") and (p.metrics or p.hidden_metrics) and not p.entities and not p.time and not p.dims \
            and re.search(r"\b(mean|means|meaning|defin\w*|calculat\w*|formula|computed|measured|stand for)\b", p.lower):
        return QueryPlan(intent="definition", metric=(p.metrics or p.hidden_metrics)[0], confidence=0.92)
    # 5. follow-up questions ("and in 2022?", "what about Europe?")
    if parent is not None and parent.specs and (FOLLOWUP_RE.search(p.text) or (words <= 5 and not p.metrics)):
        merged = _merge_followup(parent, p)
        if merged is not None:
            return merged
    metrics = _default_metrics(p, scope)
    # 6. order lists
    if p.has("list_orders") and not re.search(r"\b(how many|number of|count)\b", p.lower):
        return QueryPlan(intent="list_orders", order_filters=_filters(p), confidence=0.88)
    # 7. why
    if p.has("why"):
        compare = "prior_year_lfl" if p.time else "none"
        driver = p.dims[0] if p.dims else _driver_dim(scope, p)
        specs = [PlanSpec(title="Total", metrics=metrics[:3], filters=_filters(p), compare=compare)]
        specs.append(PlanSpec(title=f"By {driver.replace('_', ' ')}", metrics=metrics[:2], group_by=[driver], filters=_filters(p),
                              compare=compare, limit=10))
        if not p.time and p.in_scope_entities:
            specs.append(PlanSpec(title="Your whole scope", metrics=metrics[:3], filters=Filters()))
        conf = 0.86 if (p.metrics and (p.time or p.entities)) else 0.6
        return QueryPlan(intent="why", specs=specs, confidence=conf)
    # 8. compare
    if p.has("compare") or (p.has("change") and p.time) or len(p.years) >= 2:
        same_field = {}
        for e in p.in_scope_entities:
            same_field.setdefault(e.field, []).append(e.value)
        multi = {k: v for k, v in same_field.items() if len(v) >= 2}
        if multi:
            fld, values = next(iter(multi.items()))
            dim = {"regions": "region", "countries": "country", "categories": "category", "sub_categories": "sub_category",
                   "products": "product", "segments": "customer_segment", "shipping_methods": "shipping_method",
                   "payment_methods": "payment_method", "statuses": "order_status"}.get(fld)
            if dim:
                return QueryPlan(intent="compare", specs=[PlanSpec(title="Comparison", metrics=metrics, group_by=[dim],
                                                                   time_grain=p.grain, filters=_filters(p), limit=50)], confidence=0.9)
        if len(p.years) >= 2:
            ys = p.years[:2]
            base = _filters(p, drop_time=True).model_dump(exclude_none=True)
            extra = {k: v for k, v in p.time.items() if k in ("quarters", "months")}
            specs = [PlanSpec(title=str(y), metrics=metrics, group_by=p.dims[:1], filters=Filters(**base, **extra, years=[y]), limit=_limit(p))
                     for y in ys]
            return QueryPlan(intent="compare", specs=specs, confidence=0.9)
        if p.time or re.search(r"\blast year\b|\bprevious year\b|\bprior year\b|\byoy\b|\byear over year\b", p.lower):
            f = _filters(p)
            if not p.time:
                f = Filters(**{**f.model_dump(exclude_none=True), "years": [today.year]})
            return QueryPlan(intent="compare", specs=[PlanSpec(title="Change vs last year", metrics=metrics, group_by=p.dims[:1],
                                                               time_grain=p.grain, filters=f, compare="prior_year_lfl", limit=_limit(p))],
                             confidence=0.88)
    # 9. trend
    if p.grain or p.has("trend"):
        return QueryPlan(intent="trend", specs=[PlanSpec(title="Trend", metrics=metrics[:3], group_by=p.dims[:1],
                                                         time_grain=p.grain or "year_month", filters=_filters(p), limit=500)],
                         confidence=0.9)
    # 10. breakdown
    if p.dims:
        sort_by = metrics[0] if (p.sort_dir or p.top_n) else None
        return QueryPlan(intent="breakdown", specs=[PlanSpec(title="Breakdown", metrics=metrics, group_by=p.dims[:2], filters=_filters(p),
                                                             sort_by=sort_by, sort_dir=p.sort_dir if sort_by else None,
                                                             limit=_limit(p))], confidence=0.9)
    # 11. overview
    if p.has("overview") and not p.metrics:
        return QueryPlan(intent="overview", specs=[PlanSpec(title="Overview", metrics=["gross_revenue", "net_revenue", "orders", "aov"],
                                                            filters=_filters(p))], confidence=0.88)
    # 12. a metric for a slice
    if p.metrics:
        conf = 0.9 if (p.time or p.entities or words <= 8) else 0.86
        return QueryPlan(intent="metric", specs=[PlanSpec(title="Result", metrics=metrics, filters=_filters(p))], confidence=conf)
    # 13. values without a metric ("How is Clothing doing in 2023?")
    if p.entities or p.time:
        return QueryPlan(intent="overview", specs=[PlanSpec(title="Overview", metrics=["gross_revenue", "net_revenue", "orders", "aov"],
                                                            filters=_filters(p))], confidence=0.8)
    # 14. hidden metrics only, or nothing known: let the planner or the retrieval answer
    return QueryPlan(intent="semantic_search", confidence=0.3)


def metric_label(mid: str) -> str:
    return METRICS[mid].label
