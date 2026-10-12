"""Leak scan of every prompt before it goes to the LLM, and of every answer before it goes to the user.

- Analyst: no raw customer ID (CUST-#####) in a prompt.
- Operations: no financial field or financial metric in a prompt ("shipping cost" is public).
A violation stops the turn and writes an audit record.
"""

from __future__ import annotations

import re

from app.analytics.metrics import FINANCIAL_TEXT_RE
from app.security.policy import Scope

RAW_ID = re.compile(r"CUST-\d{5}")


class LeakError(Exception):
    def __init__(self, reason: str, detail: str):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def scan_prompt(messages: list[dict], scope: Scope) -> None:
    text = "\n".join(str(m.get("content", "")) for m in messages)
    if not scope.pii_raw:
        m = RAW_ID.search(text)
        if m:
            raise LeakError("raw_customer_id", m.group(0)[:5] + "…")
    if not scope.financial:
        m = FINANCIAL_TEXT_RE.search(text)
        if m:
            raise LeakError("financial_field", m.group(0))


def scan_answer(text: str, scope: Scope) -> str:
    """Mask a raw customer ID in an answer for roles that see pseudonyms (defense in depth)."""
    if not scope.pii_raw:
        return re.sub(r"CUST-\d{5,7}", "[customer]", text)
    return text
