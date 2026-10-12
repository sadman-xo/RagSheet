"""Synonyms and aliases for the closed vocabulary (chat entity matching and RAG entity documents)."""

from __future__ import annotations

import re

from app.data import vocab

REGION_ALIASES: dict[str, tuple[str, ...]] = {
    "Asia": ("asia", "asian", "apac", "asia pacific"),
    "Europe": ("europe", "european", "eu", "emea europe"),
    "Middle East": ("middle east", "mideast", "mid east", "mena", "gulf", "middle-east"),
    "North America": ("north america", "north american", "na region", "americas"),
}

COUNTRY_ALIASES: dict[str, tuple[str, ...]] = {
    "USA": ("usa", "u.s.", "u.s.a.", "united states", "the states"),
    "UK": ("uk", "u.k.", "united kingdom", "britain", "great britain", "england"),
    "UAE": ("uae", "emirates", "united arab emirates", "dubai", "abu dhabi"),
    "Saudi Arabia": ("saudi", "saudi arabia", "ksa"),
    "South Korea": ("south korea", "korea"),
    "China": ("china", "chinese", "prc"),
    "India": ("india", "indian"),
    "Japan": ("japan", "japanese"),
    "Singapore": ("singapore",),
    "France": ("france", "french"),
    "Germany": ("germany", "german"),
    "Italy": ("italy", "italian"),
    "Spain": ("spain", "spanish"),
    "Egypt": ("egypt", "egyptian"),
    "Jordan": ("jordan",),
    "Kuwait": ("kuwait",),
    "Canada": ("canada", "canadian"),
    "Mexico": ("mexico", "mexican"),
}

CATEGORY_ALIASES: dict[str, tuple[str, ...]] = {
    "Electronics": ("electronics", "electronic", "tech", "gadgets", "devices"),
    "Clothing": ("clothing", "clothes", "apparel", "fashion", "garments"),
    "Home & Kitchen": ("home & kitchen", "home and kitchen", "home", "kitchen", "household", "homeware"),
    "Books & Media": ("books & media", "books and media", "media"),
    "Beauty & Health": ("beauty & health", "beauty and health", "beauty", "health", "cosmetics", "wellness"),
}

SUB_CATEGORY_ALIASES: dict[str, tuple[str, ...]] = {
    "Smartphones": ("smartphones", "smartphone", "phones", "phone", "mobiles", "mobile phones"),
    "Laptops": ("laptops", "laptop", "notebooks", "notebook computers"),
    "Headphones": ("headphones", "headphone", "earbuds", "headsets", "earphones"),
    "Tablets": ("tablets", "tablet", "ipads"),
    "Footwear": ("footwear", "shoes", "sneakers", "trainers"),
    "Men's Wear": ("men's wear", "mens wear", "menswear", "men's clothing"),
    "Women's Wear": ("women's wear", "womens wear", "womenswear", "women's clothing"),
    "Appliances": ("appliances", "appliance", "kitchen appliances"),
    "Furniture": ("furniture",),
    "Kitchen Tools": ("kitchen tools", "cookware", "kitchenware", "utensils"),
    "Books": ("books", "book"),
    "Software": ("software", "apps", "subscriptions"),
    "Skincare": ("skincare", "skin care", "skin-care"),
    "Supplements": ("supplements", "supplement", "vitamins"),
}

PRODUCT_ALIASES: dict[str, tuple[str, ...]] = {
    "MacBook Air M2": ("macbook", "macbook air", "apple laptop", "mba m2"),
    "Lenovo ThinkPad X1": ("thinkpad", "thinkpad x1", "lenovo laptop"),
    "Dell XPS 15": ("dell xps", "xps 15", "xps"),
    "HP Spectre x360": ("hp spectre", "spectre x360", "spectre"),
    "ASUS ZenBook": ("zenbook", "asus laptop"),
    "iPhone 14": ("iphone", "iphone 14", "apple phone"),
    "Samsung Galaxy S23": ("galaxy s23", "s23", "samsung phone"),
    "Google Pixel 7": ("pixel", "pixel 7", "google phone"),
    "OnePlus 11": ("oneplus",),
    "Xiaomi 13": ("xiaomi",),
    "AirPods Pro": ("airpods", "air pods"),
    "Sony WH-1000XM5": ("sony headphones", "wh-1000xm5", "xm5"),
    "Bose QC45": ("bose", "qc45", "quietcomfort"),
    "JBL Tune 760NC": ("jbl", "tune 760nc"),
    "Samsung Galaxy Buds": ("galaxy buds", "samsung buds"),
    "iPad Pro 12.9": ("ipad", "ipad pro"),
    "Samsung Galaxy Tab S9": ("galaxy tab", "tab s9", "samsung tablet"),
    "Amazon Fire HD 10": ("fire hd", "kindle fire", "amazon tablet"),
    "Lenovo Tab P12": ("lenovo tab", "tab p12"),
    "Huawei MatePad 11": ("matepad", "huawei tablet"),
    "Nike Air Max": ("nike", "air max"),
    "Adidas Ultraboost": ("adidas", "ultraboost"),
    "Converse Chuck Taylor": ("converse", "chuck taylor"),
    "Puma Running Shoes": ("puma",),
    "Vans Old Skool": ("vans", "old skool"),
    "Microsoft Office 365": ("office 365", "microsoft office", "ms office"),
    "Adobe Creative Cloud": ("adobe", "creative cloud"),
    "VPN Premium 1Y": ("vpn",),
    "Antivirus Pro": ("antivirus",),
    "Photo Editing Suite": ("photo editing", "photo editor"),
    "Whey Protein 2kg": ("whey", "protein powder", "whey protein"),
    "Omega-3 Fish Oil": ("omega 3", "omega-3", "fish oil"),
    "Vitamin C Serum": ("vitamin c", "c serum"),
    "Sunscreen SPF50": ("sunscreen", "spf50", "sun cream"),
    "Air Fryer 5.5L": ("air fryer", "airfryer"),
    "Office Chair": ("office chair", "desk chair"),
}

STATUS_ALIASES: dict[str, tuple[str, ...]] = {
    "Delivered": ("delivered",), "Processing": ("processing", "pending"),
    "Returned": ("returned",), "Cancelled": ("cancelled", "canceled"),
}
SEGMENT_ALIASES: dict[str, tuple[str, ...]] = {
    "VIP": ("vip",), "Premium": ("premium",), "Regular": ("regular",), "New": ("new segment", "segment new"),
}
SHIPPING_ALIASES: dict[str, tuple[str, ...]] = {
    "Overnight": ("overnight", "next day"), "Express": ("express",), "Standard": ("standard shipping", "standard method"),
    "Economy": ("economy", "cheapest shipping"),
}
PAYMENT_ALIASES: dict[str, tuple[str, ...]] = {
    "Credit Card": ("credit card", "credit cards"), "Debit Card": ("debit card", "debit cards"), "PayPal": ("paypal",),
    "Apple Pay": ("apple pay",), "Google Pay": ("google pay", "gpay"), "Bank Transfer": ("bank transfer", "wire transfer"),
    "Cash on Delivery": ("cash on delivery", "cod", "cash"),
}


def default_product_aliases(name: str) -> tuple[str, ...]:
    low = name.lower()
    out = {low}
    words = re.sub(r"[^a-z0-9 ]+", " ", low).split()
    if len(words) > 1:
        out.add(" ".join(w for w in words if not any(ch.isdigit() for ch in w)).strip())
    return tuple(sorted(a for a in out if len(a) >= 3))  # sorted: the same order in every process


def product_aliases(name: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(default_product_aliases(name) + PRODUCT_ALIASES.get(name, ())))


def all_aliases() -> dict[str, dict[str, tuple[str, ...]]]:
    """field -> canonical value -> aliases (lower case)."""
    return {
        "regions": {r: tuple(dict.fromkeys((r.lower(),) + REGION_ALIASES.get(r, ()))) for r in vocab.REGIONS},
        "countries": {c: tuple(dict.fromkeys((c.lower(),) + COUNTRY_ALIASES.get(c, ()))) for c in vocab.COUNTRIES},
        "categories": {c: tuple(dict.fromkeys((c.lower(),) + CATEGORY_ALIASES.get(c, ()))) for c in vocab.CATEGORIES},
        "sub_categories": {s: tuple(dict.fromkeys((s.lower(),) + SUB_CATEGORY_ALIASES.get(s, ()))) for s in vocab.SUB_CATEGORIES},
        "products": {p: product_aliases(p) for p in vocab.PRODUCTS},
        "statuses": STATUS_ALIASES,
        "segments": SEGMENT_ALIASES,
        "shipping_methods": SHIPPING_ALIASES,
        "payment_methods": PAYMENT_ALIASES,
    }
