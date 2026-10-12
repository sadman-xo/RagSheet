"""QuerySpec: the typed query that REST and chat share.

The compiler takes identifiers only from the registries. All values are bound parameters.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.analytics.dimensions import DIMENSIONS, FILTERS, TIME_GRAINS
from app.analytics.metrics import METRICS

CompareMode = Literal["none", "prior_year_lfl", "prior_period"]
YM_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class Filters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    years: list[int] | None = Field(default=None, max_length=50)
    quarters: list[int] | None = Field(default=None, max_length=4)
    months: list[int] | None = Field(default=None, max_length=12)
    year_months: list[str] | None = Field(default=None, max_length=240)
    date_from: date | None = None
    date_to: date | None = None
    regions: list[str] | None = Field(default=None, max_length=10)
    countries: list[str] | None = Field(default=None, max_length=50)
    categories: list[str] | None = Field(default=None, max_length=10)
    sub_categories: list[str] | None = Field(default=None, max_length=50)
    products: list[str] | None = Field(default=None, max_length=100)
    segments: list[str] | None = Field(default=None, max_length=10)
    genders: list[str] | None = Field(default=None, max_length=5)
    statuses: list[str] | None = Field(default=None, max_length=10)
    shipping_methods: list[str] | None = Field(default=None, max_length=10)
    payment_methods: list[str] | None = Field(default=None, max_length=10)
    discount_bands: list[str] | None = Field(default=None, max_length=20)
    price_bands: list[str] | None = Field(default=None, max_length=10)
    shipping_days_bands: list[str] | None = Field(default=None, max_length=10)

    @model_validator(mode="after")
    def _check(self) -> "Filters":
        for name, (_dim, allowed) in FILTERS.items():
            values = getattr(self, name)
            if values is None:
                continue
            if len(values) == 0:
                setattr(self, name, None)
                continue
            if allowed is not None:
                bad = [v for v in values if v not in allowed]
                if bad:
                    raise ValueError(f"unknown value(s) for {name}: {bad[:5]}")
            # canonical order, no duplicates
            setattr(self, name, sorted(set(values), key=lambda v: (str(type(v)), v)))
        if self.years and any(y < 1990 or y > 2100 for y in self.years):
            raise ValueError("years must be between 1990 and 2100")
        if self.year_months and any(not YM_RE.match(v) for v in self.year_months):
            raise ValueError("year_months must use the format YYYY-MM")
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from is after date_to")
        return self

    def active(self) -> dict:
        return self.model_dump(exclude_none=True, mode="json")

    def dims(self) -> set[str]:
        """Dimensions that the (non-date-range) filters use."""
        return {FILTERS[name][0] for name in FILTERS if getattr(self, name) is not None}


class QuerySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metrics: list[str] = Field(min_length=1, max_length=6)
    group_by: list[str] = Field(default_factory=list, max_length=2)
    time_grain: str | None = None
    filters: Filters = Field(default_factory=Filters)
    compare: CompareMode = "none"
    sort_by: str | None = None
    sort_dir: Literal["asc", "desc"] | None = None
    limit: int = Field(default=100, ge=1, le=500)
    include_totals: bool = True

    @field_validator("metrics")
    @classmethod
    def _metrics(cls, v: list[str]) -> list[str]:
        bad = [m for m in v if m not in METRICS]
        if bad:
            raise ValueError(f"unknown metric(s): {bad}")
        if len(set(v)) != len(v):
            raise ValueError("duplicate metrics")
        return v

    @field_validator("group_by")
    @classmethod
    def _group_by(cls, v: list[str]) -> list[str]:
        bad = [d for d in v if d not in DIMENSIONS]
        if bad:
            raise ValueError(f"unknown dimension(s): {bad}")
        if len(set(v)) != len(v):
            raise ValueError("duplicate dimensions")
        return v

    @field_validator("time_grain")
    @classmethod
    def _grain(cls, v: str | None) -> str | None:
        if v is not None and v not in TIME_GRAINS:
            raise ValueError(f"time_grain must be one of {TIME_GRAINS}")
        return v

    @model_validator(mode="after")
    def _check(self) -> "QuerySpec":
        if self.time_grain and self.time_grain in self.group_by:
            raise ValueError("the time grain is also in group_by")
        if self.sort_by and self.sort_by not in self.metrics and self.sort_by not in self.dims():
            raise ValueError("sort_by must be one of the metrics or the grouping dimensions")
        return self

    def dims(self) -> list[str]:
        return ([self.time_grain] if self.time_grain else []) + list(self.group_by)

    def canonical(self) -> str:
        return json.dumps(self.model_dump(mode="json", exclude_none=True), sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.canonical().encode()).hexdigest()[:16]
