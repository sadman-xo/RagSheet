"""Chat policy (code, not the prompt).

- Pre-check: a request that names only out-of-scope values, or only hidden metrics, gets a fixed refusal before
  any data is read (0 LLM calls).
- A partly out-of-scope request loses the out-of-scope part and gets a notice.
- Hidden metrics are removed with a notice.
- Every spec goes through authorize() (the same check as the dashboards).
"""

from __future__ import annotations

import re

from app.analytics.metrics import FINANCIAL_METRICS, METRICS
from app.analytics.spec import Filters
from app.chat.entities import Parsed
from app.chat.plan import PlanSpec, QueryPlan
from app.security.policy import PolicyError, Scope, authorize, check_filters

COMPANY_RE = re.compile(r"\b(company|whole business|all regions|all categories|total business|overall business|other regions|other categories|globally|worldwide)\b", re.I)


def scope_phrase(scope: Scope) -> str:
    if not scope.all_regions:
        return f"the {scope.region} region"
    if not scope.all_categories:
        return f"the {scope.category} category"
    return "all data"


def precheck(p: Parsed, scope: Scope) -> str | None:
    """Return a refusal text, or None if the turn can continue."""
    out_scope = p.out_of_scope_entities
    in_scope = p.in_scope_entities
    if out_scope and not in_scope:
        names = ", ".join(sorted({e.value for e in out_scope}))
        return (f"I can't answer that: {names} is outside your data scope. You can see only {scope_phrase(scope)}. "
                f"Ask me about your own data instead.")
    hidden = bool(p.hidden_metrics or p.financial_words)
    if hidden and not p.metrics:
        return ("I can't answer that: your role cannot see cost, profit, or margin data. I can help with revenue, orders, "
                "returns, cancellations, shipping, and payments.")
    return None


def apply(plan: QueryPlan, p: Parsed, scope: Scope) -> tuple[QueryPlan, list[str]]:
    notices: list[str] = []
    if p.out_of_scope_entities:
        names = ", ".join(sorted({e.value for e in p.out_of_scope_entities}))
        notices.append(f"{names} is outside your data scope, so the answer shows only {scope_phrase(scope)}.")
    if p.hidden_metrics or (p.financial_words and not scope.financial):
        notices.append("Your role cannot see cost, profit, or margin. They are not in the answer.")
    if not scope.company_totals and COMPANY_RE.search(p.text):
        notices.append(f"Company totals are not available for your role. The numbers cover only {scope_phrase(scope)}.")
    specs: list[PlanSpec] = []
    for s in plan.specs:
        metrics = [m for m in s.metrics if m in METRICS and (scope.financial or m not in FINANCIAL_METRICS)]
        if len(metrics) < len(s.metrics) and not any("cost, profit, or margin" in n for n in notices):
            notices.append("Your role cannot see cost, profit, or margin. They are not in the answer.")
        if not metrics:
            continue
        f = s.filters.model_dump(exclude_none=True)
        bad = check_filters(s.filters, scope)
        if bad:
            for item in bad:
                name, _, value = item.partition("=")
                if name in f:
                    f[name] = [v for v in f[name] if v != value]
                    if not f[name]:
                        del f[name]
            if not any("outside your data scope" in n for n in notices):
                notices.append(f"Some values are outside your data scope, so the answer shows only {scope_phrase(scope)}.")
        sort_by = s.sort_by if s.sort_by in metrics or s.sort_by in s.group_by or s.sort_by == s.time_grain else None
        new = s.model_copy(update={"metrics": metrics, "filters": Filters(**f), "sort_by": sort_by,
                                   "sort_dir": s.sort_dir if sort_by else None})
        try:
            authorize(new.query_spec(), scope)
        except (PolicyError, ValueError):
            continue
        specs.append(new)
    order_filters = plan.order_filters
    if order_filters is not None and check_filters(order_filters, scope):
        f = order_filters.model_dump(exclude_none=True)
        for item in check_filters(order_filters, scope):
            name, _, value = item.partition("=")
            f[name] = [v for v in f.get(name, []) if v != value]
            if not f[name]:
                del f[name]
        order_filters = Filters(**f)
    metric = plan.metric
    if metric and metric in FINANCIAL_METRICS and not scope.financial:
        metric = None
    out = plan.model_copy(update={"specs": specs, "order_filters": order_filters, "metric": metric})
    data_intents = {"metric", "breakdown", "trend", "compare", "why", "overview"}
    if out.intent in data_intents and not out.specs:
        out = out.model_copy(update={"intent": "clarify", "clarify": "I could not build a query in your data scope for this question. "
                                                                     "Try naming a metric, a period, and a group, for example: "
                                                                     "\"revenue by country in 2023\"."})
    if out.intent == "definition" and not out.metric:
        out = out.model_copy(update={"intent": "clarify", "clarify": "Your role cannot see this metric."})
    return out, list(dict.fromkeys(notices))
