"""Entity extraction from a question: vocabulary values (with aliases and fuzzy matching), order IDs, time
expressions, metrics, group-by dimensions, and intent words. Each value is marked in scope or out of scope.
Words for metrics that the role cannot see (margin, profit, cost for operations) are also marked.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache

from rapidfuzz import fuzz, process

from app.analytics.metrics import FINANCIAL_METRICS, METRICS_LIST, mentions_financial
from app.data import synonyms, vocab
from app.security.policy import Scope

ORDER_ID_RE = re.compile(r"\bORD-\d{6,7}\b", re.I)
SCOPED_FIELDS = ("regions", "countries", "categories", "sub_categories", "products")

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
MONTHS.pop("may", None)
MONTHS["may"] = 5
ORDINALS = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4, "last": 4}

DIM_WORDS: list[tuple[str, str]] = [
    (r"sub[- ]?categor(?:y|ies)", "sub_category"),
    (r"categor(?:y|ies)", "category"),
    (r"regions?", "region"),
    (r"countr(?:y|ies)|markets?", "country"),
    (r"products?|items?|skus?", "product"),
    (r"(?:customer )?segments?", "customer_segment"),
    (r"genders?", "customer_gender"),
    (r"payment(?: methods?| types?)?", "payment_method"),
    (r"(?:shipping|delivery|shipment)(?: methods?| modes?| options?)?", "shipping_method"),
    (r"(?:order )?status(?:es)?", "order_status"),
    (r"discount(?: levels?| bands?| rates?)?", "discount_band"),
    (r"price(?: bands?| ranges?| levels?)", "price_band"),
    (r"seasons?", "season"),
    (r"weekdays?|days? of (?:the )?week", "day_of_week"),
    (r"customers?|buyers?|clients?", "customer_id"),
    (r"months?|monthly", "@year_month"),
    (r"quarters?|quarterly", "@year_quarter"),
    (r"years?|yearly|annual(?:ly)?", "@year"),
    (r"weeks?|weekly", "@week"),
    (r"days?|daily", "@order_date"),
]


@dataclass
class Entity:
    field: str
    value: str
    text: str
    in_scope: bool
    fuzzy: bool = False


@dataclass
class Parsed:
    text: str
    lower: str
    entities: list[Entity] = field(default_factory=list)
    time: dict = field(default_factory=dict)          # Filters fields
    time_label: str | None = None
    years: list[int] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    hidden_metrics: list[str] = field(default_factory=list)
    financial_words: bool = False
    dims: list[str] = field(default_factory=list)
    grain: str | None = None
    order_ids: list[str] = field(default_factory=list)
    top_n: int | None = None
    sort_dir: str | None = None
    flags: set[str] = field(default_factory=set)

    @property
    def in_scope_entities(self) -> list[Entity]:
        return [e for e in self.entities if e.in_scope]

    @property
    def out_of_scope_entities(self) -> list[Entity]:
        return [e for e in self.entities if not e.in_scope]

    def filters(self, only_in_scope: bool = True) -> dict:
        out: dict = dict(self.time)
        for e in self.entities:
            if only_in_scope and not e.in_scope:
                continue
            out.setdefault(e.field, [])
            if e.value not in out[e.field]:
                out[e.field].append(e.value)
        return out

    def has(self, flag: str) -> bool:
        return flag in self.flags


@lru_cache(maxsize=1)
def _alias_index() -> list[tuple[str, str, str, re.Pattern]]:
    idx = []
    for fld, values in synonyms.all_aliases().items():
        for value, aliases in values.items():
            for a in aliases:
                a = a.lower().strip()
                if len(a) < 2:
                    continue
                idx.append((a, fld, value, re.compile(r"(?<![a-z0-9])" + re.escape(a) + r"(?![a-z0-9])")))
    idx.sort(key=lambda x: -len(x[0]))
    return idx


@lru_cache(maxsize=1)
def _fuzzy_choices() -> dict[str, tuple[str, str]]:
    out = {}
    for fld in ("countries", "categories", "sub_categories", "products", "regions"):
        for value, aliases in synonyms.all_aliases()[fld].items():
            for a in aliases:
                if len(a) >= 5:
                    out[a] = (fld, value)
    return out


@lru_cache(maxsize=1)
def _metric_index() -> list[tuple[str, str, re.Pattern]]:
    idx = []
    for m in METRICS_LIST:
        for syn in set(m.synonyms) | {m.label.lower()}:
            s = syn.lower()
            idx.append((s, m.id, re.compile(r"(?<![a-z0-9])" + re.escape(s) + r"(?![a-z0-9])")))
    idx.sort(key=lambda x: -len(x[0]))
    return idx


def _allowed(scope: Scope, fld: str) -> tuple[str, ...] | None:
    return {"regions": scope.regions, "countries": scope.countries, "categories": scope.categories,
            "sub_categories": scope.sub_categories, "products": scope.products}.get(fld)


def _mask(text: str, start: int, end: int) -> str:
    return text[:start] + " " * (end - start) + text[end:]


def _parse_time(lower: str, today: date, p: Parsed) -> str:
    """Fill p.time and return the text with the time words masked."""
    t: dict = {}
    years = [int(y) for y in re.findall(r"(?<!\d)(20[0-4]\d)(?!\d)", lower)]
    p.years = sorted(set(years))
    m = re.search(r"\bh([12])\b|\b(first|second) half\b", lower)
    if m:
        half = int(m.group(1)) if m.group(1) else (1 if m.group(2) == "first" else 2)
        t["months"] = list(range(1, 7)) if half == 1 else list(range(7, 13))
        p.time_label = f"H{half}"
    q = re.findall(r"\bq([1-4])\b", lower) + [str(ORDINALS[w]) for w in re.findall(r"\b(first|second|third|fourth|1st|2nd|3rd|4th) quarter\b", lower)]
    if q and "last quarter" not in lower:
        t["quarters"] = sorted({int(x) for x in q})
    months = []
    for word, num in MONTHS.items():
        if re.search(rf"\b{word}\b", lower) and not (word == "may" and re.search(r"\bmay (i|we|you)\b", lower)):
            months.append(num)
    if months and "months" not in t:
        t["months"] = sorted(set(months))
    rel = re.search(r"\b(?:last|past|previous|recent)\s+(\d{1,2})\s+months?\b", lower)
    if rel:
        n = int(rel.group(1))
        y, mth = today.year, today.month - (n - 1)
        while mth <= 0:
            mth += 12
            y -= 1
        t = {"date_from": date(y, mth, 1).isoformat(), "date_to": today.isoformat()}
        p.time_label = f"last {n} months"
    elif re.search(r"\b(this year|ytd|year to date|current year)\b", lower):
        t["years"] = [today.year]
        p.time_label = str(today.year)
    elif re.search(r"\blast year\b|\bprevious year\b|\bprior year\b", lower) and not years and not p.has("compare"):
        t["years"] = [today.year - 1]
        p.time_label = str(today.year - 1)
    elif re.search(r"\blast quarter\b|\bprevious quarter\b", lower):
        qs = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
        prev_end = qs - timedelta(days=1)
        t = {"years": [prev_end.year], "quarters": [(prev_end.month - 1) // 3 + 1]}
        p.time_label = f"Q{t['quarters'][0]} {prev_end.year}"
    since = re.search(r"\b(?:since|from)\s+(20[0-4]\d)\b(?!\s*(?:to|-|and|until|through))", lower)
    if since and "date_from" not in t:
        t = {"date_from": f"{since.group(1)}-01-01", "date_to": today.isoformat()}
        p.time_label = f"since {since.group(1)}"
    elif years and "date_from" not in t:
        rng = re.search(r"\b(?:from|between)\s+(20[0-4]\d)\s*(?:to|-|and|until|through)\s*(20[0-4]\d)\b", lower)
        if rng:
            a, b = sorted((int(rng.group(1)), int(rng.group(2))))
            t["years"] = list(range(a, b + 1))
        elif not p.has("compare") or len(set(years)) == 1:
            t["years"] = sorted(set(years))
    p.time = {k: v for k, v in t.items() if v}
    if not p.time_label and p.time:
        parts = []
        if "quarters" in p.time:
            parts.append("/".join(f"Q{x}" for x in p.time["quarters"]))
        if "months" in p.time and len(p.time["months"]) <= 3:
            parts.append("/".join(calendar.month_abbr[x] for x in p.time["months"]))
        if "years" in p.time:
            parts.append("/".join(str(y) for y in p.time["years"]))
        p.time_label = " ".join(parts) or None
    masked = re.sub(r"(?<!\d)20[0-4]\d(?!\d)|\bq[1-4]\b|\bh[12]\b", "    ", lower)
    return masked


def parse(text: str, scope: Scope, today: date) -> Parsed:
    lower = " " + text.lower().replace("’", "'") + " "
    p = Parsed(text=text, lower=lower)
    # intent words
    flag_patterns = {
        "why": r"\bwhy\b|\breasons?\b|\bdrivers?\b|\bwhat (?:caused|drove|explains)\b|\bexplain\b",
        "compare": r"\bvs\.?\b|\bversus\b|\bcompar(?:e|ed|ison|ing)\b|\bagainst\b|\bdifference between\b|\brelative to\b"
                   r"|\b(?:faster|slower|quicker|cheaper|better|worse)\s+than\b",
        "change": r"\b(?:change[sd]?|growth|grow|grew|increase[sd]?|decrease[sd]?|drop(?:ped)?|declin(?:e|ed)|rise|rose|fell|fall|up or down|yoy|year over year|year-on-year)\b",
        "trend": r"\btrends?\b|\bover time\b|\bmonth by month\b|\bevolution\b|\bhistory\b|\bdevelop(?:ed|ment)\b|\btrajectory\b",
        "list_orders": r"\b(?:list|show|find|display|give)\b(?:\s+me)?(?:\s+the)?(?:\s+(?:last|latest|recent|\d+))?\s+(?:\w+\s+){0,3}orders\b(?!\s+(?:count|number))|\bwhich orders\b",
        "definition": r"^\s*(?:what (?:is|are|does)|what's|define|definition of|meaning of|how (?:is|are|do you) (?:\w+\s){0,3}(?:calculated|computed|defined|measured))\b",
        "overview": r"\boverview\b|\bsummar(?:y|ise|ize)\b|\bhow (?:are|am|is) (?:we|i|my|our|the business|business|it) doing\b|\bkpis?\b|\bhow (?:is|are) (?:\w+\s){0,2}(?:doing|performing)\b|\bperformance\b",
        "data_quality": r"\bdata quality\b|\bdata (?:issues?|problems?|caveats?|notes?)\b|\bcan i trust\b|\banomal(?:y|ies)\b|\bquirks?\b",
        "access": r"\bwhat can i see\b|\bmy access\b|\bmy (?:role|permissions?|scope)\b|\bwhat (?:data|am i allowed|can i access)\b|\bwho am i\b",
        "share": r"\bshare\b|\bproportion\b|\bpercentage of (?:total|revenue|sales)\b|\bcontribution\b|\bmix\b",
    }
    for name, pat in flag_patterns.items():
        if re.search(pat, lower):
            p.flags.add(name)
    # order IDs
    p.order_ids = sorted({m.upper() for m in ORDER_ID_RE.findall(text)})
    work = ORDER_ID_RE.sub(lambda m: " " * len(m.group(0)), lower)
    # time
    work = _parse_time(work, today, p)
    # top / bottom
    m = re.search(r"\b(?:top|best|leading|highest|largest|biggest)\s+(\d{1,2})\b", work)
    m2 = re.search(r"\b(?:bottom|worst|lowest|smallest|least)\s+(\d{1,2})\b", work)
    if m:
        p.top_n, p.sort_dir = int(m.group(1)), "desc"
    elif m2:
        p.top_n, p.sort_dir = int(m2.group(1)), "asc"
    elif re.search(r"\b(?:top|best|most|highest|largest|biggest|leading|best[- ]selling|maximum|max)\b", work):
        p.sort_dir = "desc"
        p.flags.add("superlative")
    elif re.search(r"\b(?:worst|lowest|least|smallest|bottom|minimum|min|weakest)\b", work):
        p.sort_dir = "asc"
        p.flags.add("superlative")
    # dimensions ("by country", "per region", "which product", "top 5 products", "each month")
    for pat, dim in DIM_WORDS:
        rx = re.compile(rf"\b(?:by|per|each|every|across|for each|for every|which|what|top\s*\d*|bottom\s*\d*|best|worst|leading|split by|broken down by|breakdown by)\s+(?:the\s+)?(?:\w+\s+)?(?:{pat})\b")
        mm = rx.search(work)
        if mm is None and dim.startswith("@"):
            mm = re.search(rf"\b(?:{pat})\b", work) if re.search(r"\b(monthly|quarterly|yearly|annual|weekly|daily)\b", work) else None
        if mm:
            if dim.startswith("@"):
                p.grain = p.grain or dim[1:]
            elif dim not in p.dims:
                if dim == "customer_id" and not re.search(r"\b(?:top|best|biggest|largest|which|most valuable)\b", work):
                    continue
                p.dims.append(dim)
            work = _mask(work, mm.start(), mm.end())
    if p.has("trend") and not p.grain:
        p.grain = "year_month"
    # metrics (longest synonym first)
    for syn, mid, rx in _metric_index():
        mm = rx.search(work)
        if mm:
            if mid in FINANCIAL_METRICS and not scope.financial:
                if mid not in p.hidden_metrics:
                    p.hidden_metrics.append(mid)
            elif mid not in p.metrics:
                p.metrics.append(mid)
            work = _mask(work, mm.start(), mm.end())
    if not scope.financial and mentions_financial(text):
        p.financial_words = True
    # vocabulary values
    for alias, fld, value, rx in _alias_index():
        for mm in rx.finditer(work):
            allowed = _allowed(scope, fld)
            in_scope = allowed is None or value in allowed
            if not any(e.field == fld and e.value == value for e in p.entities):
                p.entities.append(Entity(fld, value, mm.group(0).strip(), in_scope))
            work = _mask(work, mm.start(), mm.end())
    # speed words about shipping methods ("Is overnight faster than economy?") mean shipping days
    if not p.metrics and re.search(r"\b(?:fast|faster|fastest|slow|slower|slowest|quick|quicker|quickest|speed)\b", lower) \
            and (any(e.field == "shipping_methods" for e in p.entities) or "shipping_method" in p.dims):
        p.metrics.append("avg_shipping_days")
    # fuzzy matching for typos (words of 5+ letters that matched nothing)
    choices = _fuzzy_choices()
    tokens = re.findall(r"[a-z][a-z&'\-]{4,}(?: [a-z][a-z&'\-]{2,})?", work)
    for tok in tokens:
        for cand in {tok, tok.split(" ")[0]}:
            if len(cand) < 5 or cand in STOPWORDS:
                continue
            best = process.extractOne(cand, list(choices), scorer=fuzz.ratio, score_cutoff=88)
            if best:
                fld, value = choices[best[0]]
                if not any(e.field == fld and e.value == value for e in p.entities):
                    allowed = _allowed(scope, fld)
                    p.entities.append(Entity(fld, value, cand, allowed is None or value in allowed, fuzzy=True))
                break
    # a product implies nothing else; a country in a region the user cannot see is out of scope (already marked)
    return p


STOPWORDS = {
    "which", "where", "there", "their", "about", "orders", "order", "sales", "revenue", "rates", "returns", "between",
    "compare", "compared", "trend", "trends", "month", "months", "quarter", "years", "should", "would", "could", "these",
    "those", "other", "every", "total", "average", "numbers", "number", "value", "values", "highest", "lowest", "change",
    "changed", "growth", "explain", "doing", "performing", "products", "product", "countries", "country", "regions",
    "region", "categories", "category", "customers", "customer", "shipping", "payment", "status", "discount",
    "discounts", "margin", "profit", "costs", "units", "please", "thanks", "summary", "overview", "biggest", "largest",
    "smallest", "during", "since", "until", "before", "after", "first", "second", "third", "fourth", "show", "list",
    "level", "levels", "method", "methods", "segment", "segments", "gender", "season", "weekly", "monthly", "quarterly",
    "yearly", "annual", "share", "percent", "percentage", "delivered", "cancelled", "canceled", "processing",
    "returned", "people", "users", "things", "money", "think", "today", "store", "stores", "market", "markets",
}
