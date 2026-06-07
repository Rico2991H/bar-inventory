#!/usr/bin/env python3
"""Seed the bar-inventory database with demo data.

Requires the backend to be running:
    uvicorn backend.main:app --reload

Then run:
    python seed.py
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
        stock = get("/inventory/stock")
        return len(stock) == 0
    except Exception:
        return True


def seed():
    print("🍸  Bar Inventory — seeding demo data\n")

    if not check_empty():
        print("  Database already has stock entries. Skipping seed.")
        print("  To reseed: delete inventory.db and restart the backend.\n")
        return

    # --- Budget ---
    print("  Setting bar budget…")
    put("/inventory/budget", {"total_budget": 100.0})
    print("    ✓ Budget: 100.00 ALGO\n")

    # --- Suppliers ---
    print("  Creating suppliers…")
    sup1 = post("/inventory/suppliers", {
        "name": "The Gin House",
        "contact_email": "orders@ginhouse.example",
        "wallet_address": _random_algo_address(),
    })
    sup2 = post("/inventory/suppliers", {
        "name": "Alpine Brewery",
        "contact_email": "orders@alpinebrewery.example",
        "wallet_address": _random_algo_address(),
    })
    sup3 = post("/inventory/suppliers", {
        "name": "Metro Wholesale",
        "contact_email": "orders@metro.example",
        "wallet_address": _random_algo_address(),
    })
    print(f"    ✓ {sup1['name']} (id={sup1['id']})")
    print(f"    ✓ {sup2['name']} (id={sup2['id']})")
    print(f"    ✓ {sup3['name']} (id={sup3['id']})")

    # --- Products ---
    print("\n  Creating products…")
    gin = post("/inventory/products", {
        "name": "Hendrick's Gin",
        "unit": "bottle",
        "preferred_supplier_id": sup1["id"],
    })
    aperol = post("/inventory/products", {
        "name": "Aperol",
        "unit": "bottle",
        "preferred_supplier_id": sup1["id"],
    })
    pilsner = post("/inventory/products", {
        "name": "Pilsner",
        "unit": "case",
        "preferred_supplier_id": sup2["id"],
    })
    tonic = post("/inventory/products", {
        "name": "Tonic Water",
        "unit": "case",
        "preferred_supplier_id": sup2["id"],
    })
    print(f"    ✓ {gin['name']} (id={gin['id']})")
    print(f"    ✓ {aperol['name']} (id={aperol['id']})")
    print(f"    ✓ {pilsner['name']} (id={pilsner['id']})")
    print(f"    ✓ {tonic['name']} (id={tonic['id']})")

    # --- Supplier Catalog ---
    # Multiple suppliers can offer the same product at different prices
    print("\n  Building supplier catalogs…")
    catalog = [
        # Gin House: spirits specialist, premium prices
        {"supplier_id": sup1["id"], "product_id": gin["id"],     "unit_price": 0.0480, "min_order_qty": 6},
        {"supplier_id": sup1["id"], "product_id": aperol["id"],  "unit_price": 0.0350, "min_order_qty": 6},
        {"supplier_id": sup1["id"], "product_id": tonic["id"],   "unit_price": 0.0150, "min_order_qty": 1},
        # Alpine Brewery: beer + mixers
        {"supplier_id": sup2["id"], "product_id": pilsner["id"], "unit_price": 0.0220, "min_order_qty": 12},
        {"supplier_id": sup2["id"], "product_id": tonic["id"],   "unit_price": 0.0140, "min_order_qty": 12},
        # Metro Wholesale: everything cheaper but higher minimums
        {"supplier_id": sup3["id"], "product_id": gin["id"],     "unit_price": 0.0440, "min_order_qty": 12},
        {"supplier_id": sup3["id"], "product_id": aperol["id"],  "unit_price": 0.0310, "min_order_qty": 12},
        {"supplier_id": sup3["id"], "product_id": pilsner["id"], "unit_price": 0.0200, "min_order_qty": 24},
        {"supplier_id": sup3["id"], "product_id": tonic["id"],   "unit_price": 0.0120, "min_order_qty": 24},
    ]
    for entry in catalog:
        post("/inventory/catalog", entry)

    product_names = {gin["id"]: gin["name"], aperol["id"]: aperol["name"],
                     pilsner["id"]: pilsner["name"], tonic["id"]: tonic["name"]}
    supplier_names = {sup1["id"]: sup1["name"], sup2["id"]: sup2["name"], sup3["id"]: sup3["name"]}
    for e in catalog:
        print(f"    ✓ {supplier_names[e['supplier_id']]:18} → {product_names[e['product_id']]:16} @ {e['unit_price']:.4f} ALGO/unit")

    # --- Stock ---
    print("\n  Creating stock entries…")
    stocks = [
        {"product_id": gin["id"],     "quantity": 2,  "reorder_point": 5,  "reorder_qty": 12, "max_price": 0.05},
        {"product_id": aperol["id"],  "quantity": 18, "reorder_point": 6,  "reorder_qty": 12, "max_price": 0.04},
        {"product_id": pilsner["id"], "quantity": 3,  "reorder_point": 10, "reorder_qty": 24, "max_price": 0.03},
        {"product_id": tonic["id"],   "quantity": 20, "reorder_point": 8,  "reorder_qty": 24, "max_price": 0.02},
    ]
    for s in stocks:
        post("/inventory/stock", s)
        name   = product_names[s["product_id"]]
        status = "LOW  ⚠" if s["quantity"] <= s["reorder_point"] else "OK   ✓"
        print(f"    {status}  {name}: {s['quantity']} / {s['reorder_point']} (reorder {s['reorder_qty']})")

    # --- Historical sale events (for Predictions tab) ---
    # Written directly to DB so we can backdate timestamps
    print("\n  Seeding 30 days of sale history for predictions…")
    _seed_sale_history({
        gin["id"]:     1.2,   # avg units sold per day
        aperol["id"]:  0.4,
        pilsner["id"]: 1.8,
        tonic["id"]:   0.6,
    }, product_names)

    print("\n  Done! Open http://localhost:5173 to see the data.")
    print("\n  Demo flow:")
    print("    1. Predictions tab → stockout forecasts already visible")
    print("    2. Suppliers tab → review catalogs (3 suppliers, different prices)")
    print("    3. Inventory tab → 'Sell 1' on Gin or Pilsner → order auto-generates")
    print("    4. Orders tab → click 'Fund Escrow' → pick cheapest supplier → confirm")
    print("    5. Orders tab → Confirm Delivery → Release Payment\n")


def _seed_sale_history(daily_rates: dict[int, float], product_names: dict):
    """Insert backdated SaleEvent rows directly into the DB."""
    try:
        import sqlite3, os
        db_path = os.path.join(os.path.dirname(__file__), "inventory.db")
        conn = sqlite3.connect(db_path)
        cur  = conn.cursor()

        now = datetime.now(timezone.utc)
        total = 0
        for product_id, daily_rate in daily_rates.items():
            for days_ago in range(30, 0, -1):
                # Random variation ±40% around daily rate
                qty = max(0, round(daily_rate * random.uniform(0.6, 1.4)))
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
        names = [product_names[pid] for pid in daily_rates]
        print(f"    ✓ {total} sale events for: {', '.join(names)}")
    except Exception as e:
        print(f"    ✗ Could not seed sale history: {e}")
        print("      (backend must be stopped while writing directly to DB)")


if __name__ == "__main__":
    seed()
