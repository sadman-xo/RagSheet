"""Grounding check: every number in the AI text must agree with a number in the context (0.5 % tolerance).

If a currency number, or two or more numbers, do not agree, the text is replaced by the template answer
(mode ai_replaced). One wrong number that is not a currency number does not cause a replacement.
"""

from __future__ import annotations

import re

TOLERANCE = 0.005
NUM_RE = re.compile(
    r"(?<![\w.])(?P<sign>[-+−])?(?P<cur>\$)?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"\s?(?P<suf>%|percent|pts|points|k\b|K\b|M\b|million\b|B\b|billion\b|x\b|×)?"
)
MULT = {"k": 1e3, "K": 1e3, "M": 1e6, "million": 1e6, "B": 1e9, "billion": 1e9}


def _parse(m: re.Match) -> tuple[float, bool, str]:
    raw = m.group(0)
    num = float(m.group("num").replace(",", ""))
    suf = m.group("suf") or ""
    num *= MULT.get(suf, 1.0)
    if m.group("sign") in ("-", "−"):
        num = -num
    currency = bool(m.group("cur")) or ("," in m.group("num")) or bool(re.search(r"\.\d{2}$", m.group("num")) and suf == "") \
        or suf in MULT
    return num, currency, raw.strip()


def numbers(text: str) -> list[tuple[float, bool, str]]:
    return [_parse(m) for m in NUM_RE.finditer(text or "")]


def _ignorable(value: float, raw: str, currency: bool) -> bool:
    if currency:
        return False
    if value.is_integer() and 1990 <= value <= 2100:  # a year
        return True
    if value.is_integer() and 0 <= abs(value) <= 12 and "%" not in raw:  # ranks, months, quarters, small counts
        return True
    return False


def _agrees(v: float, pool: list[float]) -> bool:
    for c in pool:
        if c == v:
            return True
        if c != 0 and abs(v - c) / abs(c) <= TOLERANCE:
            return True
        if abs(v - c) <= 0.0051:
            return True
        if c != 0 and abs(abs(v) - abs(c)) / abs(c) <= TOLERANCE:  # "-14.5%" written as "14.5% lower"
            return True
    return False


def check(answer: str, context: str) -> dict:
    pool = [n for n, _c, _r in numbers(context)]
    bad, checked = [], 0
    for value, currency, raw in numbers(answer):
        if _ignorable(value, raw, currency):
            continue
        checked += 1
        if not _agrees(value, pool):
            bad.append({"text": raw, "currency": currency})
    replace = any(b["currency"] for b in bad) or len(bad) >= 2
    return {"ok": not replace, "checked": checked, "unsupported": bad, "replaced": replace}
