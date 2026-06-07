#!/usr/bin/env python3
"""Seed the bar-inventory database with a RICH test dataset.

A larger, more varied dataset than seed.py — useful for exercising
supplier selection, auto-buy, lead-time deliveries and the
predictions/analytics tabs:

  * 9 suppliers across different categories, each with its own pricing and
    minimum-order quantities
  * ~34 products spanning bar + café + restaurant use, each with a
    per-product delivery lead time (lead_time_days)
  * overlapping catalogs generated programmatically, so most products have
    2-3 competing offers at different prices
  * realistic stock levels (several already below their reorder point)
  * 45 days of backdated sale history for forecasting

Requires the backend to be running:
    uvicorn backend.main:app --reload

Then run:
    python seed_test.py

The database must be empty. To reseed:
    1. stop the backend
    2. delete inventory.db
    3. restart the backend
    4. run this script again
"""

import sys
import random
from datetime import datetime, timedelta, timezone
import httpx

BASE = "http://localhost:8000"


def _random_algo_address() -> str:
    try:
        from algosdk.account import generate_account
        _sk, address = generate_account()
        return address
    except ImportError:
        return "XNFT2AMETQIRMODE3BKK4PPYH3HH4OKFPMFIKMSZMOAPIYUJLQJYIFEA4"


def post(path: str, body: dict) -> dict:
    try:
        r = httpx.post(f"{BASE}{path}", json=body, timeout=10)
        r.raise_for_status()
        return r.json()
    except httpx.ConnectError:
        print(f"\n  ERROR: cannot reach backend at {BASE}")
        print("  Make sure to run:  uvicorn backend.main:app --reload\n")
        sys.exit(1)
    except httpx.HTTPStatusError as e:
        print(f"\n  HTTP {e.response.status_code} on POST {path}: {e.response.text}\n")
        sys.exit(1)


def put(path: str, body: dict) -> dict:
    r = httpx.put(f"{BASE}{path}", json=body, timeout=10)
    r.raise_for_status()
    return r.json()


def get(path: str):
    r = httpx.get(f"{BASE}{path}", timeout=10)
    r.raise_for_status()
    return r.json()


def check_empty() -> bool:
    try:
        return len(get("/inventory/stock")) == 0
    except Exception:
        return True


# --- Suppliers: name → {email, coverage{category: price_multiplier}, moq} ---
SUPPLIERS = [
    ("The Gin House",            "orders@ginhouse.example",     {"spirits": 1.15}, 6),
    ("Coastal Spirits Import",   "orders@coastalspirits.example", {"spirits": 1.06}, 6),
    ("Alpine Brewery",           "orders@alpinebrewery.example", {"beer": 1.05}, 12),
    ("Vineyard Direct",          "orders@vineyard.example",      {"wine": 1.00}, 6),
    ("Bean & Leaf Co.",          "orders@beanleaf.example",      {"coffee": 1.00}, 2),
    ("Fresh Farms",              "orders@freshfarms.example",    {"garnish": 1.00, "juice": 0.95, "dairy": 1.00}, 1),
    ("Soda Stream Distribution", "orders@sodastream.example",    {"soft": 1.00, "juice": 1.05}, 12),
    ("Metro Wholesale",          "orders@metro.example",         {"spirits": 0.92, "beer": 0.95, "wine": 0.90, "soft": 0.90, "juice": 0.90}, 24),
    ("City Cash & Carry",        "orders@citycc.example",        {"beer": 1.00, "soft": 0.95, "garnish": 1.10, "dairy": 1.00}, 6),
]

# --- Products: (name, unit, category, base_price, lead_time_days, preferred_supplier) ---
PRODUCTS = [
    # spirits
    ("Hendrick's Gin",     "bottle", "spirits", 0.048, 4, "The Gin House"),
    ("London Dry Gin",     "bottle", "spirits", 0.034, 3, "Metro Wholesale"),
    ("Aperol",             "bottle", "spirits", 0.035, 4, "The Gin House"),
    ("Campari",            "bottle", "spirits", 0.038, 4, "The Gin House"),
    ("Vodka",              "bottle", "spirits", 0.036, 3, "Metro Wholesale"),
    ("Premium Vodka",      "bottle", "spirits", 0.052, 5, "Coastal Spirits Import"),
    ("Single Malt Whisky", "bottle", "spirits", 0.095, 6, "Coastal Spirits Import"),
    ("Bourbon",            "bottle", "spirits", 0.058, 5, "Coastal Spirits Import"),
    ("Tequila Blanco",     "bottle", "spirits", 0.049, 5, "The Gin House"),
    ("White Rum",          "bottle", "spirits", 0.033, 4, "Metro Wholesale"),
    ("Dark Rum",           "bottle", "spirits", 0.041, 5, "Coastal Spirits Import"),
    ("Triple Sec",         "bottle", "spirits", 0.028, 3, "Metro Wholesale"),
    # beer
    ("Pilsner",            "case",   "beer", 0.020, 2, "Alpine Brewery"),
    ("IPA",                "case",   "beer", 0.028, 3, "Alpine Brewery"),
    ("Wheat Beer",         "case",   "beer", 0.026, 3, "Alpine Brewery"),
    ("Lager",              "case",   "beer", 0.022, 2, "Alpine Brewery"),
    ("Stout",              "case",   "beer", 0.030, 3, "Alpine Brewery"),
    # wine
    ("House Red Wine",     "bottle", "wine", 0.030, 4, "Vineyard Direct"),
    ("House White Wine",   "bottle", "wine", 0.030, 4, "Vineyard Direct"),
    ("Rosé Wine",          "bottle", "wine", 0.032, 4, "Vineyard Direct"),
    ("Prosecco",           "bottle", "wine", 0.045, 5, "Vineyard Direct"),
    ("Champagne",          "bottle", "wine", 0.120, 6, "Vineyard Direct"),
    # soft drinks
    ("Tonic Water",        "case",   "soft", 0.013, 2, "Soda Stream Distribution"),
    ("Cola",               "case",   "soft", 0.012, 2, "Soda Stream Distribution"),
    ("Soda Water",         "case",   "soft", 0.011, 2, "Soda Stream Distribution"),
    ("Ginger Beer",        "case",   "soft", 0.016, 3, "Soda Stream Distribution"),
    # juice
    ("Orange Juice",       "carton", "juice", 0.019, 1, "Fresh Farms"),
    ("Cranberry Juice",    "carton", "juice", 0.021, 2, "Soda Stream Distribution"),
    # coffee / tea
    ("Espresso Beans",     "kg",     "coffee", 0.060, 3, "Bean & Leaf Co."),
    ("Black Tea",          "kg",     "coffee", 0.040, 3, "Bean & Leaf Co."),
    # garnish
    ("Fresh Limes",        "kg",     "garnish", 0.025, 1, "Fresh Farms"),
    ("Fresh Lemons",       "kg",     "garnish", 0.024, 1, "Fresh Farms"),
    ("Fresh Mint",         "bunch",  "garnish", 0.018, 1, "Fresh Farms"),
    # dairy
    ("Milk",               "carton", "dairy", 0.015, 1, "Fresh Farms"),
]

# Typical daily consumption per category (units/day), for stock + history.
CATEGORY_RATE = {
    "spirits": 0.9, "beer": 2.2, "wine": 1.3, "soft": 2.6,
    "juice": 1.6, "coffee": 2.2, "garnish": 1.8, "dairy": 2.0,
}


def seed():
    print("🍸  Bar Inventory — seeding RICH test data\n")

    if not check_empty():
        print("  Database already has stock entries. Skipping seed.")
        print("  To reseed: stop the backend, delete inventory.db, restart it, run again.\n")
        return

    # --- Budget ---
    print("  Setting bar budget…")
    put("/inventory/budget", {"total_budget": 1000.0})
    print("    ✓ Budget: 1000.00 ALGO\n")

    # --- Suppliers ---
    print(f"  Creating {len(SUPPLIERS)} suppliers…")
    sup_id = {}
    for name, email, _cov, _moq in SUPPLIERS:
        s = post("/inventory/suppliers", {
            "name": name, "contact_email": email,
            "wallet_address": _random_algo_address(),
        })
        sup_id[name] = s["id"]
        print(f"    ✓ {name} (id={s['id']})")
    sup_cov = {name: cov for name, _e, cov, _m in SUPPLIERS}
    sup_moq = {name: moq for name, _e, _c, moq in SUPPLIERS}

    # --- Products ---
    print(f"\n  Creating {len(PRODUCTS)} products…")
    prod_id = {}
    for name, unit, _cat, _bp, lead, pref in PRODUCTS:
        p = post("/inventory/products", {
            "name": name, "unit": unit,
            "preferred_supplier_id": sup_id[pref],
            "lead_time_days": lead,
        })
        prod_id[name] = p["id"]
    print(f"    ✓ {len(prod_id)} products created (lead times {min(p[4] for p in PRODUCTS)}–{max(p[4] for p in PRODUCTS)} days)")

    # --- Supplier catalogs (generated from category coverage) ---
    print("\n  Building supplier catalogs…")
    catalog_count = 0
    offers_per_product = {}
    for name, unit, cat, base_price, lead, pref in PRODUCTS:
        for sname, cov in sup_cov.items():
            if cat not in cov:
                continue
            price = round(base_price * cov[cat], 4)
            post("/inventory/catalog", {
                "supplier_id":   sup_id[sname],
                "product_id":    prod_id[name],
                "unit_price":    price,
                "min_order_qty": sup_moq[sname],
            })
            catalog_count += 1
            offers_per_product[name] = offers_per_product.get(name, 0) + 1
    multi = sum(1 for n in offers_per_product if offers_per_product[n] >= 2)
    print(f"    ✓ {catalog_count} catalog entries · {multi}/{len(PRODUCTS)} products have ≥2 competing offers")

    # --- Stock ---
    print("\n  Creating stock entries…")
    low = 0
    for name, unit, cat, base_price, lead, pref in PRODUCTS:
        reorder_point = random.randint(5, 11)
        reorder_qty   = reorder_point * 2 + random.choice([0, 6, 12])
        # ~40% start below their reorder point
        if random.random() < 0.4:
            quantity = random.randint(0, reorder_point)
        else:
            quantity = random.randint(reorder_point + 1, reorder_point * 2 + 8)
        post("/inventory/stock", {
            "product_id":    prod_id[name],
            "quantity":      quantity,
            "reorder_point": reorder_point,
            "reorder_qty":   reorder_qty,
            "max_price":     round(base_price * 1.5, 4),
        })
        low += quantity <= reorder_point
    print(f"    ✓ {len(PRODUCTS)} stock entries · {low} below reorder point")

    # --- Historical sale events (for Predictions / Analytics) ---
    print("\n  Seeding 45 days of sale history for forecasting…")
    rates = {}
    for name, unit, cat, base_price, lead, pref in PRODUCTS:
        rates[prod_id[name]] = CATEGORY_RATE.get(cat, 1.0) * random.uniform(0.6, 1.3)
    _seed_sale_history(rates)

    print("\n  Done! Open http://localhost:5173 to see the data.")
    print("\n  Try:")
    print("    • Header → ⏩ 1 Tag überspringen → sales + lead-time deliveries roll in")
    print("    • Orders tab → Auto-buy is ON (AI) by default; funded escrows appear")
    print("    • Deliveries tab → funded orders arrive after each product's lead time")
    print("    • Predictions tab → stockout forecasts; Analytics → spend by supplier\n")


def _seed_sale_history(daily_rates: dict):
    """Insert backdated SaleEvent rows directly into the DB (weekend-weighted)."""
    try:
        import sqlite3, os
        db_path = os.path.join(os.path.dirname(__file__), "inventory.db")
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        now = datetime.now(timezone.utc)
        total = 0
        for product_id, daily_rate in daily_rates.items():
            for days_ago in range(45, 0, -1):
                dow = (now - timedelta(days=days_ago)).weekday()  # 0=Mon
                weekend_boost = 1.6 if dow in (4, 5) else 1.0
                qty = max(0, round(daily_rate * weekend_boost * random.uniform(0.6, 1.4)))
                if qty == 0:
                    continue
                ts = (now - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")
                cur.execute(
                    "INSERT INTO saleevent (product_id, quantity, sold_at) VALUES (?, ?, ?)",
                    (product_id, qty, ts),
                )
                total += 1

        conn.commit()
        conn.close()
        print(f"    ✓ {total} sale events across {len(daily_rates)} products")
    except Exception as e:
        print(f"    ✗ Could not seed sale history: {e}")
        print("      (backend must be stopped while writing directly to DB)")


if __name__ == "__main__":
    seed()
