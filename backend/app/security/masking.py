"""Masking of raw customer IDs (defense in depth; the analyst's scope file has only pseudonyms)."""

from __future__ import annotations

import re

RAW_CUSTOMER_ID = re.compile(r"CUST-\d{5,7}")
PSEUDONYM = re.compile(r"\bC-[A-Z2-7]{8}\b")


def contains_raw_customer_id(text: str) -> bool:
    return bool(RAW_CUSTOMER_ID.search(text or ""))


def mask_customer_ids(text: str) -> str:
    return RAW_CUSTOMER_ID.sub("[customer]", text or "")


def mask_value(value, pii_raw: bool):
    """Mask a raw ID in a response value when the role sees pseudonyms only."""
    if pii_raw or not isinstance(value, str):
        return value
    return mask_customer_ids(value)
