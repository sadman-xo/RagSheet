"""Role policy: build_scope(user) and authorize(spec, scope).

build_scope uses the users row from the principal read (never the token claims). It returns the row
filters, the allowed columns, the PII mode, the capabilities, the scope_key, and a fingerprint.
The database calculates the same scope key independently (app.current_scope_key()); deps.py compares them.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from app.analytics.dimensions import DIMENSIONS
from app.analytics.metrics import FINANCIAL_METRICS, METRICS
from app.analytics.spec import Filters, QuerySpec
from app.data import vocab
from app.data.schema import visible_columns

ALL_PAGES = (
    "overview", "trends", "geography", "products", "profitability", "customers", "operations",
    "compare", "explorer", "orders", "assistant", "data-notes",
)
ROLE_LABELS = {
    "admin": "Admin", "executive": "Executive", "regional_manager": "Regional Manager",
    "category_manager": "Category Manager", "analyst": "Sales Analyst", "operations": "Operations / Support",
}


class PolicyError(Exception):
    def __init__(self, status: int, code: str, message: str, detail: dict | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail or {}


@dataclass(frozen=True)
class Scope:
    role: str
    scope_key: str
    all_regions: bool
    region: str | None
    all_categories: bool
    category: str | None
    financial: bool
    pii_raw: bool
    capabilities: frozenset[str]
    pages: tuple[str, ...]
    landing: str
    fingerprint: str
    label: str
    badges: tuple[str, ...] = field(default_factory=tuple)

    @property
    def company_totals(self) -> bool:
        return self.all_regions and self.all_categories

    @property
    def regions(self) -> tuple[str, ...]:
        return vocab.REGIONS if self.all_regions else (self.region,)

    @property
    def categories(self) -> tuple[str, ...]:
        return vocab.CATEGORIES if self.all_categories else (self.category,)

    @property
    def countries(self) -> tuple[str, ...]:
        return tuple(c for c in vocab.COUNTRIES if vocab.COUNTRY_REGION[c] in self.regions)

    @property
    def sub_categories(self) -> tuple[str, ...]:
        return tuple(s for s in vocab.SUB_CATEGORIES if vocab.SUB_CATEGORY_CATEGORY[s] in self.categories)

    @property
    def products(self) -> tuple[str, ...]:
        return tuple(p for p in vocab.PRODUCTS if vocab.PRODUCT_CATEGORY[p] in self.categories)

    def allowed_metrics(self) -> list[str]:
        return [m for m in METRICS if self.financial or m not in FINANCIAL_METRICS]

    def visible_columns(self) -> list[str]:
        return [c.name for c in visible_columns(self.financial)]

    def locked_filters(self) -> dict:
        out: dict = {}
        if not self.all_regions:
            out["regions"] = [self.region]
        if not self.all_categories:
            out["categories"] = [self.category]
        return out

    def describe(self) -> dict:
        return {
            "scope_key": self.scope_key, "label": self.label, "badges": list(self.badges),
            "financial": self.financial, "pii": "raw" if self.pii_raw else "pseudonym",
            "company_totals": self.company_totals, "locked_filters": self.locked_filters(),
            "regions": list(self.regions), "categories": list(self.categories),
        }


def _fingerprint(*parts: object) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


def build_scope(role: str, region: str | None, category: str | None) -> Scope:
    """Fail closed: an unknown role or a manager without a region/category gives 403."""
    if role not in vocab.ROLES:
        raise PolicyError(403, "UNKNOWN_ROLE", "Your role is not known. Contact an administrator.")
    all_regions = role != "regional_manager"
    all_categories = role != "category_manager"
    if not all_regions and region not in vocab.REGIONS:
        raise PolicyError(403, "SCOPE_INCOMPLETE", "Your account has no region. Contact an administrator.")
    if not all_categories and category not in vocab.CATEGORIES:
        raise PolicyError(403, "SCOPE_INCOMPLETE", "Your account has no category. Contact an administrator.")
    financial = role != "operations"
    pii_raw = role != "analyst"
    if role in ("admin", "executive"):
        key = "all:full"
    elif role == "analyst":
        key = "all:pseudo"
    elif role == "operations":
        key = "all:nofin"
    elif role == "regional_manager":
        key = f"region:{region}"
    else:
        key = f"category:{category}"

    pages = [p for p in ALL_PAGES if financial or p not in ("profitability", "customers")]
    if role == "admin":
        pages.append("admin")
    caps = {"dashboard", "orders", "export", "chat"}
    if role == "admin":
        caps.add("admin")
    landing = {"analyst": "/explorer", "operations": "/operations"}.get(role, "/overview")

    if role == "regional_manager":
        label = f"Region: {region}"
    elif role == "category_manager":
        label = f"Category: {category}"
    else:
        label = "All data"
    badges = [label]
    if not financial:
        badges.append("Profit hidden")
    if not pii_raw:
        badges.append("Customer IDs masked")
    if not (all_regions and all_categories):
        badges.append("No company totals")
    return Scope(
        role=role, scope_key=key, all_regions=all_regions, region=None if all_regions else region,
        all_categories=all_categories, category=None if all_categories else category, financial=financial,
        pii_raw=pii_raw, capabilities=frozenset(caps), pages=tuple(pages), landing=landing,
        fingerprint=_fingerprint(role, key, financial, pii_raw), label=label, badges=tuple(badges),
    )


def check_filters(filters: Filters, scope: Scope) -> list[str]:
    """Return the out-of-scope filter values (empty list: all values are in scope)."""
    bad: list[str] = []
    checks = (
        ("regions", scope.regions), ("countries", scope.countries), ("categories", scope.categories),
        ("sub_categories", scope.sub_categories), ("products", scope.products),
    )
    for name, allowed in checks:
        for v in getattr(filters, name) or []:
            if v not in allowed:
                bad.append(f"{name}={v}")
    return bad


def authorize(spec: QuerySpec, scope: Scope) -> None:
    """Reject metrics, dimensions, and filters that are not in the scope (fail closed)."""
    hidden = [m for m in spec.metrics if m in FINANCIAL_METRICS and not scope.financial]
    if hidden or (spec.sort_by in FINANCIAL_METRICS and not scope.financial):
        raise PolicyError(403, "FORBIDDEN_METRIC", "Your role cannot see financial metrics (cost, profit, margin).",
                          {"metrics": hidden})
    for d in spec.dims():
        if d not in DIMENSIONS:
            raise PolicyError(422, "UNKNOWN_DIMENSION", f"Unknown dimension {d}.")
    bad = check_filters(spec.filters, scope)
    if bad:
        raise PolicyError(403, "OUT_OF_SCOPE", "The request contains values outside your data scope.", {"values": bad})


def authorize_filters(filters: Filters, scope: Scope) -> None:
    bad = check_filters(filters, scope)
    if bad:
        raise PolicyError(403, "OUT_OF_SCOPE", "The request contains values outside your data scope.", {"values": bad})
