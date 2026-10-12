"""Number formatting for template answers, insight text, and exports."""

from __future__ import annotations

import math

from app.analytics.metrics import METRICS


def money(v: float | None, compact: bool = False) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "n/a"
    if compact:
        return compact_number(v)
    return f"{v:,.2f}"


def compact_number(v: float) -> str:
    a = abs(v)
    sign = "-" if v < 0 else ""
    if a >= 1e9:
        return f"{sign}{a / 1e9:.2f}B"
    if a >= 1e6:
        return f"{sign}{a / 1e6:.2f}M"
    if a >= 1e3:
        return f"{sign}{a / 1e3:.1f}K"
    return f"{sign}{a:.2f}"


def count(v: float | None) -> str:
    if v is None:
        return "n/a"
    return f"{int(round(v)):,}"


def pct(v: float | None, digits: int = 2) -> str:
    if v is None:
        return "n/a"
    return f"{v:.{digits}f}%"


def days(v: float | None) -> str:
    if v is None:
        return "n/a"
    return f"{v:.1f} days"


def metric_value(metric_id: str, v: float | None) -> str:
    kind = METRICS[metric_id].kind
    if kind == "money":
        return money(v)
    if kind == "count":
        return count(v)
    if kind == "pct":
        return pct(v)
    if kind == "days":
        return days(v)
    return "n/a" if v is None else f"{v:,.2f}"


def delta_text(metric_id: str, cur: float | None, prior: float | None) -> str:
    if cur is None or prior is None:
        return "no comparison value"
    kind = METRICS[metric_id].kind
    if kind == "pct":
        return f"{cur - prior:+.2f} points"
    if prior == 0:
        return "n/a (prior is 0)"
    return f"{(cur - prior) / abs(prior) * 100:+.2f}%"


def number_forms(v: float) -> list[str]:
    """Different text forms of one amount (for the forbidden-number tests)."""
    return [f"{v:,.2f}", f"{v:.2f}", f"{v:,.0f}", compact_number(v), f"{v / 1e6:.2f} million"]
