"""Closed vocabulary of the sales dataset.

The values come from the original CSV. The loader rejects rows with other values,
and the 1M generator uses only these values. Thus the set of data scopes stays closed.
"""

from __future__ import annotations

REGION_COUNTRIES: dict[str, tuple[str, ...]] = {
    "Asia": ("China", "India", "Japan", "Singapore", "South Korea"),
    "Europe": ("France", "Germany", "Italy", "Spain", "UK"),
    "Middle East": ("Egypt", "Jordan", "Kuwait", "Saudi Arabia", "UAE"),
    "North America": ("Canada", "Mexico", "USA"),
}

CATALOG: dict[str, dict[str, tuple[str, ...]]] = {
    "Beauty & Health": {
        "Skincare": ("Hyaluronic Acid", "Moisturizing Cream", "Retinol Night Cream", "Sunscreen SPF50", "Vitamin C Serum"),
        "Supplements": ("Collagen Peptides", "Multivitamin Pack", "Omega-3 Fish Oil", "Vitamin D3", "Whey Protein 2kg"),
    },
    "Books & Media": {
        "Books": ("Atomic Habits", "Deep Work", "Rich Dad Poor Dad", "The Psychology of Money", "Thinking Fast and Slow"),
        "Software": ("Adobe Creative Cloud", "Antivirus Pro", "Microsoft Office 365", "Photo Editing Suite", "VPN Premium 1Y"),
    },
    "Clothing": {
        "Footwear": ("Adidas Ultraboost", "Converse Chuck Taylor", "Nike Air Max", "Puma Running Shoes", "Vans Old Skool"),
        "Men's Wear": ("Chino Pants", "Classic T-Shirt", "Formal Shirt", "Hoodie Sweatshirt", "Slim Fit Jeans"),
        "Women's Wear": ("Blouse Top", "High-Waist Jeans", "Maxi Skirt", "Summer Dress", "Yoga Pants"),
    },
    "Electronics": {
        "Headphones": ("AirPods Pro", "Bose QC45", "JBL Tune 760NC", "Samsung Galaxy Buds", "Sony WH-1000XM5"),
        "Laptops": ("ASUS ZenBook", "Dell XPS 15", "HP Spectre x360", "Lenovo ThinkPad X1", "MacBook Air M2"),
        "Smartphones": ("Google Pixel 7", "iPhone 14", "OnePlus 11", "Samsung Galaxy S23", "Xiaomi 13"),
        "Tablets": ("Amazon Fire HD 10", "Huawei MatePad 11", "iPad Pro 12.9", "Lenovo Tab P12", "Samsung Galaxy Tab S9"),
    },
    "Home & Kitchen": {
        "Appliances": ("Air Fryer 5.5L", "Blender Pro", "Coffee Maker", "Microwave Oven", "Rice Cooker"),
        "Furniture": ("Bedside Table", "Bookshelf 5-Tier", "Office Chair", "Study Desk", "TV Stand"),
        "Kitchen Tools": ("Cutting Board Set", "Knife Block Set", "Mixing Bowl Set", "Non-stick Pan Set", "Storage Container Set"),
    },
}

REGIONS: tuple[str, ...] = tuple(REGION_COUNTRIES)
COUNTRIES: tuple[str, ...] = tuple(c for cs in REGION_COUNTRIES.values() for c in cs)
COUNTRY_REGION: dict[str, str] = {c: r for r, cs in REGION_COUNTRIES.items() for c in cs}

CATEGORIES: tuple[str, ...] = tuple(CATALOG)
SUB_CATEGORIES: tuple[str, ...] = tuple(s for subs in CATALOG.values() for s in subs)
SUB_CATEGORY_CATEGORY: dict[str, str] = {s: c for c, subs in CATALOG.items() for s in subs}
PRODUCTS: tuple[str, ...] = tuple(p for subs in CATALOG.values() for ps in subs.values() for p in ps)
PRODUCT_SUB_CATEGORY: dict[str, str] = {p: s for subs in CATALOG.values() for s, ps in subs.items() for p in ps}
PRODUCT_CATEGORY: dict[str, str] = {p: SUB_CATEGORY_CATEGORY[s] for p, s in PRODUCT_SUB_CATEGORY.items()}

STATUSES: tuple[str, ...] = ("Delivered", "Processing", "Returned", "Cancelled")
NET_EXCLUDED_STATUSES: tuple[str, ...] = ("Cancelled", "Returned")
FULFILLED_STATUSES: tuple[str, ...] = ("Delivered", "Returned")
OPEN_STATUSES: tuple[str, ...] = ("Processing",)
SEGMENTS: tuple[str, ...] = ("New", "Regular", "Premium", "VIP")
GENDERS: tuple[str, ...] = ("Female", "Male")
SHIPPING_METHODS: tuple[str, ...] = ("Economy", "Standard", "Express", "Overnight")
PAYMENT_METHODS: tuple[str, ...] = (
    "Apple Pay", "Bank Transfer", "Cash on Delivery", "Credit Card", "Debit Card", "Google Pay", "PayPal",
)
SEASONS: tuple[str, ...] = ("Winter", "Spring", "Summer", "Fall")
DISCOUNTS: tuple[float, ...] = (0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50)

# Bands. The SQL in the database view and the scope files uses the same edges.
DISCOUNT_BANDS: tuple[str, ...] = tuple(f"{int(round(d * 100))}%" for d in DISCOUNTS)
PRICE_BANDS: tuple[str, ...] = ("<25", "25-100", "100-250", "250-500", "500-1000", "1000+")
PRICE_BAND_EDGES: tuple[float, ...] = (25, 100, 250, 500, 1000)
SHIPPING_DAYS_BANDS: tuple[str, ...] = ("<=5", "6-9", "10-14", "15-19", "20+")
SHIPPING_DAYS_EDGES: tuple[int, ...] = (5, 9, 14, 19)
DAYS_OF_WEEK: tuple[str, ...] = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def price_band(price: float) -> str:
    for edge, label in zip(PRICE_BAND_EDGES, PRICE_BANDS):
        if price < edge:
            return label
    return PRICE_BANDS[-1]


def shipping_days_band(days: int) -> str:
    for edge, label in zip(SHIPPING_DAYS_EDGES, SHIPPING_DAYS_BANDS):
        if days <= edge:
            return label
    return SHIPPING_DAYS_BANDS[-1]


def discount_band(discount: float) -> str:
    return f"{int(round(float(discount) * 100))}%"


def price_band_sql(col: str) -> str:
    whens = " ".join(f"WHEN {col} < {e} THEN '{l}'" for e, l in zip(PRICE_BAND_EDGES, PRICE_BANDS))
    return f"CASE {whens} ELSE '{PRICE_BANDS[-1]}' END"


def shipping_days_band_sql(col: str) -> str:
    whens = " ".join(f"WHEN {col} <= {e} THEN '{l}'" for e, l in zip(SHIPPING_DAYS_EDGES, SHIPPING_DAYS_BANDS))
    return f"CASE {whens} ELSE '{SHIPPING_DAYS_BANDS[-1]}' END"

MONTH_SEASON: dict[int, str] = {
    12: "Winter", 1: "Winter", 2: "Winter",
    3: "Spring", 4: "Spring", 5: "Spring",
    6: "Summer", 7: "Summer", 8: "Summer",
    9: "Fall", 10: "Fall", 11: "Fall",
}

ROLES: tuple[str, ...] = ("admin", "executive", "regional_manager", "category_manager", "analyst", "operations")


def sql_in_list(values: tuple[str, ...]) -> str:
    """Return a SQL literal list for CHECK constraints (values are from this closed module only)."""
    return ", ".join("'" + v.replace("'", "''") + "'" for v in values)
