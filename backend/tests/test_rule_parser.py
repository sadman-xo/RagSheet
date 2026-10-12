"""Rule parser: questions that the eval found hard for small models get a rule plan (no LLM planner)."""

from __future__ import annotations

from datetime import date

import pytest

from app.chat.entities import parse
from app.chat.rule_parser import parse_rules
from app.security.policy import build_scope

TODAY = date(2024, 12, 31)


def _plan(question: str, role: str = "executive"):
    scope = build_scope(role, None, None)
    p = parse(question, scope, TODAY)
    return p, parse_rules(p, scope, TODAY)


@pytest.mark.parametrize("question", ["Is overnight shipping faster than economy?", "Is economy slower than express shipping?"])
def test_shipping_speed_compare(question):
    p, plan = _plan(question, "operations")
    assert p.metrics == ["avg_shipping_days"]
    assert plan.intent == "compare" and plan.confidence >= 0.85
    assert plan.specs[0].group_by == ["shipping_method"]
    assert plan.specs[0].metrics == ["avg_shipping_days"]


def test_speed_words_without_shipping_keep_the_default_metrics():
    p, _ = _plan("Is Electronics growing faster than Books & Media?")
    assert "avg_shipping_days" not in p.metrics
    assert "compare" in p.flags
