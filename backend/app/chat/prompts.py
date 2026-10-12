"""Prompts. The static system blocks come first (prefix reuse); all prompts pass the leak scan.

Prompts for the operations role contain no financial words.
"""

from __future__ import annotations

import json
from datetime import date

from app.analytics.dimensions import DIMENSIONS
from app.analytics.metrics import METRICS
from app.security.policy import Scope

PROMPT_VERSION = "4"

ANSWER_SYSTEM = (
    "You are Panorama, an analytics assistant for an e-commerce sales dataset. "
    "Answer the QUESTION in at most 80 words of plain English. "
    "Use only numbers that appear in RESULTS or SNIPPETS and copy them exactly as they are written. "
    "Never calculate new numbers: no sums, differences, averages, or percentages that are not given. "
    "After each number, cite its source tag, for example [R1] or [S2]. "
    "Name the most important facts first. If the results do not answer the question, say so in one sentence. "
    "Talk only about the data in SCOPE. Do not invent causes that the data does not show; say 'the data suggests' for possible reasons."
)

PLANNER_SYSTEM = (
    "You turn a business question about e-commerce sales data into a JSON query plan. "
    "Use only the metric ids, dimension ids, and filter values that are listed. "
    "Put a value in filters only if the question names it. Do not add filters for things the question does not say. "
    "Intents: metric = one number or a few numbers; breakdown = numbers by a dimension; trend = over time (set time_grain); "
    "compare = two periods or two groups (use compare=prior_year_lfl for 'vs last year', or compare=two_periods with "
    "compare_filters for the second period); why = explain a change (use compare=prior_year_lfl and one group_by); "
    "list_orders = show individual orders; overview = a general summary; definition = what a metric means; "
    "data_quality = data problems; semantic_search = a general question about the data; clarify = the question is unclear "
    "(write clarify_question). Use sort=desc with a limit for 'top' and 'highest' questions, sort=asc for 'lowest'."
)


def scope_line(scope: Scope) -> str:
    if not scope.all_regions:
        s = f"The user is a regional manager. Only data of the {scope.region} region is available."
    elif not scope.all_categories:
        s = f"The user is a category manager. Only data of the {scope.category} category is available."
    elif not scope.financial:
        s = "The user works in operations and support. Data of all regions is available."
    elif not scope.pii_raw:
        s = "The user is a sales analyst. All data is available; customer IDs are pseudonyms (C-...)."
    elif scope.role == "admin":
        s = "The user is an administrator and can see all data of the company."
    else:
        s = "The user is an executive and can see all data of the company."
    return s


def _examples(scope: Scope) -> list[tuple[str, dict]]:
    region = scope.region or "Asia"
    country = scope.countries[0]
    cat = scope.category or "Electronics"
    ex = [
        (f"What was the revenue of {cat} in Q3 2023?",
         {"intent": "metric", "metrics": ["gross_revenue", "orders"], "group_by": [], "time_grain": None,
          "filters": {"categories": [cat], "years": [2023], "quarters": [3]}, "compare": "none", "sort": "none", "limit": 10}),
        (f"Which countries in {region} had the highest return rate?",
         {"intent": "breakdown", "metrics": ["return_rate"], "group_by": ["country"], "time_grain": None,
          "filters": {"regions": [region]} if scope.all_regions or scope.region == region else {}, "compare": "none", "sort": "desc", "limit": 5}),
        ("How did orders develop month by month in 2023?",
         {"intent": "trend", "metrics": ["orders"], "group_by": [], "time_grain": "year_month",
          "filters": {"years": [2023]}, "compare": "none", "sort": "none", "limit": 50}),
        (f"Why did sales in {country} drop in 2024?",
         {"intent": "why", "metrics": ["gross_revenue"], "group_by": ["category" if scope.all_categories else "sub_category"],
          "time_grain": None, "filters": {"countries": [country], "years": [2024]}, "compare": "prior_year_lfl", "sort": "none", "limit": 10}),
        ("Compare the average order value of 2022 and 2023",
         {"intent": "compare", "metrics": ["aov"], "group_by": [], "time_grain": None, "filters": {"years": [2022]},
          "compare": "two_periods", "compare_filters": {"years": [2023]}, "sort": "none", "limit": 10}),
    ]
    return ex


def planner_messages(question: str, scope: Scope, today: date, data_min: date, history: list[str], parent_summary: str | None) -> list[dict]:
    metrics = "; ".join(f"{m}={METRICS[m].label}" for m in scope.allowed_metrics())
    dims = ", ".join(d for d in DIMENSIONS if not DIMENSIONS[d].time_grain and d != "customer_id")
    lines = [
        scope_line(scope),
        f"Data from {data_min.isoformat()} to {today.isoformat()} (today = {today.isoformat()}).",
        f"Metric ids: {metrics}.",
        f"Dimension ids: {dims}. Time grains: year, year_quarter, year_month, week, order_date.",
        f"Regions: {', '.join(scope.regions)}. Categories: {', '.join(scope.categories)}.",
        "Examples:",
    ]
    for q, plan in _examples(scope):
        lines.append(f"Q: {q}\nA: {json.dumps(plan)}")
    if history:
        lines.append("Earlier questions in this conversation: " + " | ".join(history[-3:]))
    if parent_summary:
        lines.append(f"The previous plan was: {parent_summary}. A short follow-up question changes only what it names.")
    return [
        {"role": "system", "content": PLANNER_SYSTEM},
        {"role": "user", "content": "\n".join(lines) + f"\nQ: {question}\nA:"},
    ]


def repair_message(error: str) -> dict:
    return {"role": "user", "content": f"The plan was not valid ({error[:200]}). Return a corrected JSON plan only."}
