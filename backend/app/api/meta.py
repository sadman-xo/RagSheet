"""Catalog of in-scope values, metric registry, columns, and data notes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.analytics import dimensions, periods, quality
from app.analytics.metrics import describe as describe_metrics
from app.data import vocab
from app.data.schema import FLAT_COLUMNS
from app.security.deps import ScopedDataset, get_scope, get_scoped_dataset
from app.security.policy import Scope

router = APIRouter(prefix="/api/meta", tags=["meta"])


@router.get("/catalog")
def catalog(ds: ScopedDataset = Depends(get_scoped_dataset)) -> dict:
    sc, sf = ds.scope, ds.file
    years = sorted({int(ym[:4]) for ym in sf.monthly_orders})
    presets = []
    for pid, label in periods.PRESETS.items():
        f, t, lab = periods.resolve_preset(pid, sf.data_min, sf.data_max)
        presets.append({"id": pid, "label": lab, "date_from": f.isoformat() if f else None, "date_to": t.isoformat() if t else None})
    return {
        "regions": [{"name": r, "countries": [c for c in vocab.REGION_COUNTRIES[r]]} for r in sc.regions],
        "countries": list(sc.countries),
        "categories": [{"name": c, "sub_categories": [{"name": s, "products": list(ps)} for s, ps in vocab.CATALOG[c].items()]}
                       for c in sc.categories],
        "sub_categories": list(sc.sub_categories),
        "products": list(sc.products),
        "segments": list(vocab.SEGMENTS),
        "genders": list(vocab.GENDERS),
        "statuses": list(vocab.STATUSES),
        "shipping_methods": list(vocab.SHIPPING_METHODS),
        "payment_methods": list(vocab.PAYMENT_METHODS),
        "discount_bands": list(vocab.DISCOUNT_BANDS),
        "price_bands": list(vocab.PRICE_BANDS),
        "shipping_days_bands": list(vocab.SHIPPING_DAYS_BANDS),
        "years": years,
        "date_range": {"min": sf.data_min.isoformat(), "max": sf.data_max.isoformat()},
        "today": sf.data_max.isoformat(),
        "periods": presets,
        "locked": sc.locked_filters(),
        "rows": sf.rows,
        "dataset": ds.principal.dataset,
        "data_version": sf.data_version,
    }


@router.get("/metrics")
def metrics(scope: Scope = Depends(get_scope)) -> dict:
    return {"metrics": describe_metrics(scope.financial), "dimensions": dimensions.describe()}


@router.get("/columns")
def columns(scope: Scope = Depends(get_scope)) -> dict:
    out = []
    for c in FLAT_COLUMNS:
        visible = scope.financial or c.sensitivity != "financial"
        out.append({"name": c.name, "label": c.label, "kind": c.kind, "sensitivity": c.sensitivity,
                    "description": c.description, "visible": visible, "in_table": c.in_table,
                    "note": ("Pseudonym (C-…) for your role" if c.sensitivity == "pii" and not scope.pii_raw else
                             "Hidden for your role" if not visible else None)})
    return {"columns": out}


@router.get("/data-notes")
def data_notes(ds: ScopedDataset = Depends(get_scoped_dataset)) -> dict:
    formulas = [
        {"name": "Revenue", "formula": "round(Unit_Price × Quantity × (1 − Discount), 2)", "financial": False},
        {"name": "Profit", "formula": "Revenue − Cost (without the shipping cost)", "financial": True},
        {"name": "List value", "formula": "Unit_Price × Quantity", "financial": False},
        {"name": "Discount amount", "formula": "List value − Revenue", "financial": False},
        {"name": "Weighted margin", "formula": "SUM(Profit) / SUM(Revenue) × 100", "financial": True},
        {"name": "Return rate", "formula": "Returned / (Delivered + Returned) × 100", "financial": False},
    ]
    return {"notes": quality.data_notes(ds.file, ds.scope.scope_key), "scope": ds.scope.describe(),
            "formulas": [f for f in formulas if ds.scope.financial or not f["financial"]]}
