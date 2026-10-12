"""The RAG corpus. Its size depends on the entities, not on the orders (about 550 documents).

1. Knowledge documents: chunks of the knowledge files, the metric glossary, and the column dictionary.
2. Insight documents: the insight definitions (text only; the numbers come from the user's scope at retrieval).
3. Entity documents: products with aliases, sub-categories, categories, countries, regions.
4. Summary documents: a QuerySpec for a slice (for example region x year), never numbers.

No document contains customer IDs, costs, profits, or amounts. There is no document for each order.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlencode

from app.analytics.insights import INSIGHTS
from app.analytics.metrics import METRICS_LIST, mentions_financial
from app.data import synonyms, vocab
from app.data.schema import FLAT_COLUMNS

KNOWLEDGE_DIR = Path(__file__).with_name("knowledge")
GENERATOR_VERSION = "3"
YEARS = (2021, 2022, 2023, 2024)


@dataclass
class Doc:
    doc_key: str
    kind: str
    title: str
    body: str
    embed_text: str
    coverage_region: str | None = None
    coverage_category: str | None = None
    is_financial: bool = False
    spec: dict | None = None
    deep_link: str | None = None
    meta: dict = field(default_factory=dict)

    def row(self) -> dict:
        return asdict(self)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def explorer_link(metrics: list[str], dims: list[str], grain: str | None, filters: dict) -> str:
    params = {"m": "|".join(metrics)}
    if dims:
        params["g"] = "|".join(dims)
    if grain:
        params["t"] = grain
    names = {"regions": "region", "countries": "country", "categories": "category", "sub_categories": "sub",
             "products": "product", "segments": "segment", "shipping_methods": "ship", "payment_methods": "pay",
             "discount_bands": "disc"}
    for k, v in filters.items():
        if k == "years" and len(v) == 1:
            params["period"] = f"y{v[0]}"
        elif k in names:
            params[names[k]] = "|".join(v)
    return "/explorer?" + urlencode(params, safe="|")


# ---------------------------------------------------------------------------
# 1. Knowledge
# ---------------------------------------------------------------------------
def knowledge_files() -> list[Path]:
    return sorted(KNOWLEDGE_DIR.glob("*.md"))


def knowledge_docs() -> list[Doc]:
    out: list[Doc] = []
    for path in knowledge_files():
        text = path.read_text(encoding="utf-8")
        doc_title = text.splitlines()[0].lstrip("# ").strip()
        for section in re.split(r"\n(?=## )", text)[1:]:
            lines = section.strip().splitlines()
            heading = lines[0].lstrip("# ").strip()
            body = " ".join(line.strip() for line in lines[1:] if line.strip())
            fin = mentions_financial(heading + " " + body)
            out.append(Doc(doc_key=f"k:{path.stem}:{_slug(heading)}", kind="knowledge", title=f"{doc_title}: {heading}",
                           body=body, embed_text=f"{heading}. {body}", is_financial=fin,
                           deep_link="/data-notes", meta={"source": path.name}))
    for m in METRICS_LIST:
        body = f"{m.label}: {m.description} Formula: {m.formula}. Other words: {', '.join(m.synonyms)}."
        out.append(Doc(doc_key=f"k:metric:{m.id}", kind="knowledge", title=f"Metric: {m.label}", body=body,
                       embed_text=body, is_financial=m.financial, deep_link=f"/explorer?m={m.id}",
                       meta={"metric": m.id}))
    groups: dict[str, list] = {}
    for c in FLAT_COLUMNS:
        groups.setdefault({"financial": "Financial columns", "pii": "Customer columns"}.get(c.sensitivity, "Order columns"), []).append(c)
    for title, cols in groups.items():
        for i in range(0, len(cols), 8):
            part = cols[i:i + 8]
            body = " ".join(f"{c.label} ({c.name}): {c.description}" for c in part)
            out.append(Doc(doc_key=f"k:columns:{_slug(title)}:{i // 8}", kind="knowledge", title=f"Column dictionary: {title}",
                           body=body, embed_text=body, is_financial=title == "Financial columns", deep_link="/data-notes"))
    return out


# ---------------------------------------------------------------------------
# 2. Insights
# ---------------------------------------------------------------------------
def insight_docs() -> list[Doc]:
    return [Doc(doc_key=f"i:{d.id}", kind="insight", title=f"Insight: {d.title}", body=d.about,
                embed_text=f"{d.title}. {d.about}", is_financial=d.financial, meta={"insight": d.id})
            for d in INSIGHTS]


# ---------------------------------------------------------------------------
# 3. Entities
# ---------------------------------------------------------------------------
def entity_docs() -> list[Doc]:
    out: list[Doc] = []
    for p in vocab.PRODUCTS:
        sub, cat = vocab.PRODUCT_SUB_CATEGORY[p], vocab.PRODUCT_CATEGORY[p]
        aliases = synonyms.product_aliases(p)
        body = f"{p} is a product in the sub-category {sub} of the category {cat}. Other names: {', '.join(aliases)}."
        out.append(Doc(doc_key=f"e:product:{_slug(p)}", kind="entity", title=f"Product: {p}", body=body, embed_text=body,
                       coverage_category=cat, spec={"metrics": ["gross_revenue", "orders", "units"], "filters": {"products": [p]}},
                       deep_link=explorer_link(["gross_revenue", "orders"], [], "year", {"products": [p]}),
                       meta={"entity": "product", "value": p}))
    for s in vocab.SUB_CATEGORIES:
        cat = vocab.SUB_CATEGORY_CATEGORY[s]
        prods = vocab.CATALOG[cat][s]
        body = f"{s} is a sub-category of {cat} with the products {', '.join(prods)}. Other names: {', '.join(synonyms.SUB_CATEGORY_ALIASES.get(s, ()))}."
        out.append(Doc(doc_key=f"e:sub:{_slug(s)}", kind="entity", title=f"Sub-category: {s}", body=body, embed_text=body,
                       coverage_category=cat, spec={"metrics": ["gross_revenue", "orders"], "filters": {"sub_categories": [s]}},
                       deep_link=explorer_link(["gross_revenue", "orders"], ["product"], None, {"sub_categories": [s]}),
                       meta={"entity": "sub_category", "value": s}))
    for c in vocab.CATEGORIES:
        body = f"{c} is a product category with the sub-categories {', '.join(vocab.CATALOG[c])}. Other names: {', '.join(synonyms.CATEGORY_ALIASES.get(c, ()))}."
        out.append(Doc(doc_key=f"e:cat:{_slug(c)}", kind="entity", title=f"Category: {c}", body=body, embed_text=body,
                       coverage_category=c, spec={"metrics": ["gross_revenue", "orders"], "filters": {"categories": [c]}},
                       deep_link=explorer_link(["gross_revenue", "orders"], ["sub_category"], None, {"categories": [c]}),
                       meta={"entity": "category", "value": c}))
    for country in vocab.COUNTRIES:
        r = vocab.COUNTRY_REGION[country]
        body = f"{country} is a country in the region {r}. Other names: {', '.join(synonyms.COUNTRY_ALIASES.get(country, ()))}."
        out.append(Doc(doc_key=f"e:country:{_slug(country)}", kind="entity", title=f"Country: {country}", body=body, embed_text=body,
                       coverage_region=r, spec={"metrics": ["gross_revenue", "orders"], "filters": {"countries": [country]}},
                       deep_link=explorer_link(["gross_revenue", "orders"], ["category"], None, {"countries": [country]}),
                       meta={"entity": "country", "value": country}))
    for r in vocab.REGIONS:
        body = f"{r} is a sales region with the countries {', '.join(vocab.REGION_COUNTRIES[r])}. Other names: {', '.join(synonyms.REGION_ALIASES.get(r, ()))}."
        out.append(Doc(doc_key=f"e:region:{_slug(r)}", kind="entity", title=f"Region: {r}", body=body, embed_text=body,
                       coverage_region=r, spec={"metrics": ["gross_revenue", "orders"], "filters": {"regions": [r]}},
                       deep_link=explorer_link(["gross_revenue", "orders"], ["country"], None, {"regions": [r]}),
                       meta={"entity": "region", "value": r}))
    return out


# ---------------------------------------------------------------------------
# 4. Summaries (a spec, never numbers)
# ---------------------------------------------------------------------------
BASE = ["gross_revenue", "orders", "aov", "return_rate"]


def _summary(key: str, title: str, about: str, filters: dict, dims: list[str], region: str | None, category: str | None,
             metrics: list[str] | None = None, financial: bool = False, grain: str | None = None) -> Doc:
    m = metrics or BASE
    spec = {"metrics": m, "filters": filters}
    if dims:
        spec["group_by"] = dims
        spec["limit"] = 5
    if grain:
        spec["time_grain"] = grain
    return Doc(doc_key=f"s:{key}", kind="summary", title=title, body=about, embed_text=f"{title}. {about}",
               coverage_region=region, coverage_category=category, is_financial=financial, spec=spec,
               deep_link=explorer_link(m[:2], dims, grain, filters), meta={"summary": key.split(":")[0]})


def summary_docs() -> list[Doc]:
    out: list[Doc] = []
    for y in YEARS:
        out.append(_summary(f"year:{y}", f"Company summary {y}", f"Sales of the whole company in {y}: revenue, orders, average order value, return rate, and the top regions.",
                            {"years": [y]}, ["region"], None, None))
        for r in vocab.REGIONS:
            out.append(_summary(f"region-year:{_slug(r)}:{y}", f"{r} in {y}", f"Sales of the region {r} in {y}: revenue, orders, average order value, return rate, and the top countries.",
                                {"regions": [r], "years": [y]}, ["country"], r, None))
        for c in vocab.CATEGORIES:
            out.append(_summary(f"category-year:{_slug(c)}:{y}", f"{c} in {y}", f"Sales of the category {c} in {y}: revenue, orders, average order value, return rate, and the top sub-categories.",
                                {"categories": [c], "years": [y]}, ["sub_category"], None, c))
        for country in vocab.COUNTRIES:
            r = vocab.COUNTRY_REGION[country]
            out.append(_summary(f"country-year:{_slug(country)}:{y}", f"{country} in {y}", f"Sales in {country} ({r}) in {y}: revenue, orders, average order value, return rate, and the top categories.",
                                {"countries": [country], "years": [y]}, ["category"], r, None))
        for s in vocab.SUB_CATEGORIES:
            c = vocab.SUB_CATEGORY_CATEGORY[s]
            out.append(_summary(f"sub-year:{_slug(s)}:{y}", f"{s} in {y}", f"Sales of the sub-category {s} ({c}) in {y}: revenue, orders, average order value, return rate, and the top products.",
                                {"sub_categories": [s], "years": [y]}, ["product"], None, c))
    for r in vocab.REGIONS:
        for c in vocab.CATEGORIES:
            out.append(_summary(f"region-category:{_slug(r)}:{_slug(c)}", f"{c} in {r}", f"Sales of {c} in the region {r} by year: revenue, orders, average order value, and return rate.",
                                {"regions": [r], "categories": [c]}, [], r, c, grain="year"))
        out.append(_summary(f"shipping-region:{_slug(r)}", f"Shipping in {r}", f"Shipping methods in {r}: orders, average shipping days, average shipping cost, and return rate by method.",
                            {"regions": [r]}, ["shipping_method"], r, None, metrics=["orders", "avg_shipping_days", "avg_shipping_cost", "return_rate"]))
        out.append(_summary(f"payment-region:{_slug(r)}", f"Payment methods in {r}", f"Payment methods in {r}: orders and cancellation rate by payment method.",
                            {"regions": [r]}, ["payment_method"], r, None, metrics=["orders", "cancellation_rate", "gross_revenue"]))
    for c in vocab.CATEGORIES:
        out.append(_summary(f"discount:{_slug(c)}", f"Discounts and margin in {c}", f"Discount levels in {c}: orders, weighted margin, and the share of loss orders for each discount level.",
                            {"categories": [c]}, ["discount_band"], None, c, metrics=["orders", "margin_pct", "loss_order_pct", "gross_revenue"], financial=True))
        out.append(_summary(f"segment-category:{_slug(c)}", f"Customer segments in {c}", f"Customer segments in {c}: revenue, orders, and average order value for each segment.",
                            {"categories": [c]}, ["customer_segment"], None, c, metrics=["gross_revenue", "orders", "aov"]))
        out.append(_summary(f"status-category:{_slug(c)}", f"Order statuses in {c}", f"Order statuses in {c}: orders by status, return rate, and cancellation rate.",
                            {"categories": [c]}, ["order_status"], None, c, metrics=["orders", "gross_revenue"]))
    for p in vocab.PRODUCTS:
        c = vocab.PRODUCT_CATEGORY[p]
        out.append(_summary(f"product:{_slug(p)}", f"{p} by year", f"Sales of the product {p} by year: revenue, orders, units, and return rate.",
                            {"products": [p]}, [], None, c, metrics=["gross_revenue", "orders", "units", "return_rate"], grain="year"))
    return out


def build_documents() -> list[Doc]:
    docs = knowledge_docs() + insight_docs() + entity_docs() + summary_docs()
    keys = [d.doc_key for d in docs]
    assert len(keys) == len(set(keys)), "duplicate doc_key"
    return docs


def content_hash() -> str:
    h = hashlib.sha256(GENERATOR_VERSION.encode())
    for p in knowledge_files():
        h.update(p.name.encode())
        h.update(p.read_bytes())
    for d in build_documents():
        h.update(d.doc_key.encode())
        h.update(d.embed_text.encode())
    return h.hexdigest()
