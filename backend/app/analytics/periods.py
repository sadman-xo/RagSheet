"""Periods: presets, like-for-like comparison windows, and caveats.

"Today" is the last date in the dataset (2024-12-24 for the sample).
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

from app.analytics.spec import Filters

PRESETS: dict[str, str] = {
    "all": "All time",
    "last_12m": "Last 12 months",
    "ytd": "Year to date",
    "last_year": "Last full year",
    "this_quarter": "Quarter to date",
    "last_quarter": "Last full quarter",
    "last_6m": "Last 6 months",
    "last_3m": "Last 3 months",
}

TIME_FIELDS = ("years", "quarters", "months", "year_months", "date_from", "date_to")


@dataclass(frozen=True)
class Window:
    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def _month_start(d: date, back: int = 0) -> date:
    y, m = d.year, d.month - back
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


def _month_end(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def _quarter_start(d: date) -> date:
    return date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)


def resolve_preset(preset: str, data_min: date, data_max: date) -> tuple[date | None, date | None, str]:
    if preset not in PRESETS:
        raise ValueError(f"unknown period preset {preset}")
    label = PRESETS[preset]
    if preset == "all":
        return None, None, label
    if preset == "last_12m":
        return _month_start(data_max, 11), data_max, label
    if preset == "last_6m":
        return _month_start(data_max, 5), data_max, label
    if preset == "last_3m":
        return _month_start(data_max, 2), data_max, label
    if preset == "ytd":
        return date(data_max.year, 1, 1), data_max, label
    if preset == "last_year":
        y = data_max.year - 1
        return date(y, 1, 1), date(y, 12, 31), f"{label} ({y})"
    if preset == "this_quarter":
        return _quarter_start(data_max), data_max, label
    if preset == "last_quarter":
        qs = _quarter_start(data_max)
        prev_end = qs - timedelta(days=1)
        return _quarter_start(prev_end), prev_end, label
    raise AssertionError(preset)


def shift_year(d: date, years: int = -1) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 February
        return d.replace(year=d.year + years, day=28)


def time_window(f: Filters, data_min: date, data_max: date) -> Window | None:
    """A contiguous date window for simple time filters, clipped to the data range."""
    has = {k for k in TIME_FIELDS if getattr(f, k) is not None}
    if not has:
        return None
    start: date | None = None
    end: date | None = None
    if has <= {"date_from", "date_to"}:
        start = f.date_from or data_min
        end = f.date_to or data_max
    elif has == {"years"} and len(f.years) == 1:
        y = f.years[0]
        start, end = date(y, 1, 1), date(y, 12, 31)
    elif has == {"years", "quarters"} and len(f.years) == 1 and len(f.quarters) == 1:
        y, q = f.years[0], f.quarters[0]
        start, end = date(y, 3 * q - 2, 1), _month_end(y, 3 * q)
    elif has == {"years", "months"} and len(f.years) == 1 and len(f.months) == 1:
        y, m = f.years[0], f.months[0]
        start, end = date(y, m, 1), _month_end(y, m)
    elif has == {"year_months"} and len(f.year_months) == 1:
        y, m = map(int, f.year_months[0].split("-"))
        start, end = date(y, m, 1), _month_end(y, m)
    elif has == {"years"} and f.years == list(range(min(f.years), max(f.years) + 1)):
        start, end = date(min(f.years), 1, 1), date(max(f.years), 12, 31)
    else:
        return None
    start = max(start, data_min)
    end = min(end, data_max)
    if start > end:
        return Window(start, start)  # empty period on this data
    return Window(start, end)


def _without_time(f: Filters) -> dict:
    d = f.model_dump(exclude_none=True)
    for k in TIME_FIELDS:
        d.pop(k, None)
    return d


def prior_filters(f: Filters, mode: str, data_min: date, data_max: date) -> tuple[Filters, str]:
    """Filters of the comparison period and a label. Raises ValueError if there is no period to compare."""
    base = _without_time(f)
    w = time_window(f, data_min, data_max)
    if mode == "prior_year_lfl":
        if w is not None:
            ps, pe = shift_year(w.start), shift_year(w.end)
            return Filters(**base, date_from=ps, date_to=pe), f"Same period last year ({ps:%d %b %Y} – {pe:%d %b %Y})"
        if f.years or f.year_months:
            d = dict(base)
            if f.years:
                d["years"] = [y - 1 for y in f.years]
            if f.quarters:
                d["quarters"] = f.quarters
            if f.months:
                d["months"] = f.months
            if f.year_months:
                d["year_months"] = [f"{int(ym[:4]) - 1:04d}{ym[4:]}" for ym in f.year_months]
            return Filters(**d), "Same periods one year earlier"
        raise ValueError("select a period to compare with the prior year")
    if mode == "prior_period":
        has = {k for k in TIME_FIELDS if getattr(f, k) is not None}
        if has == {"years"} and len(f.years) == 1:
            return Filters(**base, years=[f.years[0] - 1]), f"Prior year ({f.years[0] - 1})"
        if has == {"years", "quarters"} and len(f.years) == 1 and len(f.quarters) == 1:
            y, q = f.years[0], f.quarters[0] - 1
            if q == 0:
                y, q = y - 1, 4
            return Filters(**base, years=[y], quarters=[q]), f"Prior quarter (Q{q} {y})"
        if has == {"years", "months"} and len(f.years) == 1 and len(f.months) == 1:
            y, m = f.years[0], f.months[0] - 1
            if m == 0:
                y, m = y - 1, 12
            return Filters(**base, years=[y], months=[m]), f"Prior month ({y}-{m:02d})"
        if w is not None:
            pe = w.start - timedelta(days=1)
            ps = pe - timedelta(days=w.days - 1)
            return Filters(**base, date_from=ps, date_to=pe), f"Prior period ({ps:%d %b %Y} – {pe:%d %b %Y})"
        raise ValueError("select one period to compare with the prior period")
    raise ValueError(f"unknown compare mode {mode}")


def shift_time_key(dim: str, value, mode: str, offset_days: int = 0):
    """Map a prior-period time key forward, so that prior rows join current rows."""
    if value is None:
        return None
    if mode == "prior_year_lfl":
        if dim == "year":
            return int(value) + 1
        if dim == "year_month":
            return f"{int(value[:4]) + 1:04d}{value[4:]}"
        if dim == "year_quarter":
            return f"{int(value[:4]) + 1:04d}{value[4:]}"
        if dim in ("order_date", "week"):
            return shift_year(value if isinstance(value, date) else date.fromisoformat(str(value)), 1)
    if mode == "prior_period" and dim in ("order_date", "week") and offset_days:
        d = value if isinstance(value, date) else date.fromisoformat(str(value))
        return d + timedelta(days=offset_days)
    return value


def caveats(f: Filters, data_min: date, data_max: date, monthly_orders: dict[str, int]) -> list[str]:
    """Warn when the period has months with low order volume (2021 ramp-up, decline from 2024-Q2)."""
    if not monthly_orders:
        return []
    counts = sorted(monthly_orders.values())
    median = counts[len(counts) // 2]
    w = time_window(f, data_min, data_max)
    if w is None:  # all time, or a time filter that is not one window: no caveat
        return []
    start_ym, end_ym = f"{w.start:%Y-%m}", f"{w.end:%Y-%m}"
    low = sorted(ym for ym, n in monthly_orders.items() if start_ym <= ym <= end_ym and n < 0.6 * median)
    if not low:
        return []
    shown = ", ".join(low[:4]) + (f" and {len(low) - 4} more" if len(low) > 4 else "")
    return [f"This period includes months with low order volume ({shown}): the 2021 ramp-up or the decline from 2024-Q2. Compare with care."]
