#!/usr/bin/env python3
"""Import Square POS sandbox catalog into bar-inventory.

Prerequisites:
  1. Free Square Developer account at https://developer.squareup.com
  2. Sandbox Access Token from your app's "Sandbox" credentials tab
  3. Some items in your Sandbox Seller Dashboard
  4. bar-inventory backend running: uvicorn backend.main:app --reload

Usage (PowerShell):
  $env:SQUARE_TOKEN = "EAAAl..."
  python square_import.py

Usage (bash):
  SQUARE_TOKEN=EAAAl... python square_import.py
"""

import os
import sys
import httpx

SQUARE_BASE = "https://connect.squareupsandbox.com/v2"
OUR_BASE    = "http://localhost:8000"
TOKEN       = os.getenv("SQUARE_TOKEN", "")

# ── Defaults applied when Square doesn't have inventory data ─────────────────
DEFAULT_REORDER_POINT = 5
DEFAULT_REORDER_QTY   = 12
DEFAULT_MAX_PRICE     = 0.05   # ALGO — upper price limit for the rule engine

# ── Unit inference from category/item name ───────────────────────────────────
BOTTLE_KEYWORDS = {"gin", "vodka", "rum", "whisky", "whiskey", "tequila",
                   "brandy", "liqueur", "wine", "prosecco", "champagne",
                   "aperol", "campari", "vermouth", "spirit"}
CASE_KEYWORDS   = {"beer", "lager", "ale", "stout", "pilsner", "cider",
                   "soda", "tonic", "water", "juice", "mixer"}


def _infer_unit(name: str, category: str = "") -> str:
    text = (name + " " + category).lower()
    if any(k in text for k in BOTTLE_KEYWORDS):
        return "bottle"
    if any(k in text for k in CASE_KEYWORDS):
        return "case"
    return "unit"


# ── Algorand address generator (for supplier placeholder) ────────────────────
def _random_algo_address() -> str:
    try:
        from algosdk.account import generate_account
        _sk, address = generate_account()
        return address
    except ImportError:
        return "XNFT2AMETQIRMODE3BKK4PPYH3HH4OKFPMFIKMSZMOAPIYUJLQJYIFEA4"


# ── Square API helpers ────────────────────────────────────────────────────────
def sq_get(path: str, params: dict = None) -> dict:
    headers = {"Authorization": f"Bearer {TOKEN}", "Square-Version": "2024-01-18"}
    r = httpx.get(f"{SQUARE_BASE}{path}", headers=headers, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def sq_paginate(path: str, list_key: str, params: dict = None) -> list:
    """Collect all pages from a Square list endpoint."""
    params = dict(params or {})
    results = []
    while True:
        data   = sq_get(path, params)
        results.extend(data.get(list_key, []))
        cursor = data.get("cursor")
        if not cursor:
            break
        params["cursor"] = cursor
    return results


# ── Our API helpers ───────────────────────────────────────────────────────────
def our_post(path: str, body: dict) -> dict:
    try:
        r = httpx.post(f"{OUR_BASE}{path}", json=body, timeout=10)
        r.raise_for_status()
        return r.json()
    except httpx.ConnectError:
        print(f"\n  ERROR: cannot reach bar-inventory backend at {OUR_BASE}")
        print("  Start it with:  uvicorn backend.main:app --reload\n")
        sys.exit(1)
    except httpx.HTTPStatusError as e:
        print(f"  HTTP {e.response.status_code} POST {path}: {e.response.text}")
        return None


def our_get(path: str) -> list | dict:
    r = httpx.get(f"{OUR_BASE}{path}", timeout=10)
    r.raise_for_status()
    return r.json()


# ── Main import logic ─────────────────────────────────────────────────────────
def run():
    if not TOKEN:
        print("\n  ERROR: SQUARE_TOKEN environment variable not set.")
        print("  Get your Sandbox Access Token from https://developer.squareup.com")
        print("\n  PowerShell:  $env:SQUARE_TOKEN = 'EAAAl...'")
        print("  bash:        export SQUARE_TOKEN=EAAAl...\n")
        sys.exit(1)

    print("🍸  bar-inventory ← Square POS import\n")

    # ── 1. Verify Square connection ──────────────────────────────────────────
    print("  Connecting to Square sandbox…")
    try:
        locations = sq_get("/locations").get("locations", [])
    except httpx.HTTPStatusError as e:
        print(f"\n  Square API error {e.response.status_code}: {e.response.text}")
        print("  Check your SQUARE_TOKEN.\n")
        sys.exit(1)

    if not locations:
        print("  No locations found in Square sandbox.")
        sys.exit(1)

    location    = locations[0]
    location_id = location["id"]
    print(f"    ✓ Connected — Location: {location['name']} ({location_id})")

    # ── 2. Fetch Square catalog ──────────────────────────────────────────────
    print("\n  Fetching Square catalog…")
    catalog_objects = sq_paginate("/catalog/list", "objects", {"types": "ITEM,CATEGORY"})

    categories = {
        obj["id"]: obj["category_data"]["name"]
        for obj in catalog_objects
        if obj["type"] == "CATEGORY"
    }
    items = [obj for obj in catalog_objects if obj["type"] == "ITEM"]

    if not items:
        print("\n  No items found in your Square sandbox catalog.")
        print("  Add items at: https://squareupsandbox.com/dashboard/items/library")
        sys.exit(1)

    print(f"    ✓ Found {len(items)} item(s) across {len(categories)} category/categories")

    # ── 3. Fetch Square inventory counts ────────────────────────────────────
    print("  Fetching Square inventory…")
    counts_data = sq_paginate(
        "/inventory/counts/batch-retrieve",
        "counts",
    ) if False else []  # batch-retrieve needs POST; use simpler approach below

    # Use the search endpoint instead
    try:
        inv_resp = httpx.post(
            f"{SQUARE_BASE}/inventory/counts/batch-retrieve",
            headers={"Authorization": f"Bearer {TOKEN}", "Square-Version": "2024-01-18"},
            json={"location_ids": [location_id]},
            timeout=15,
        )
        inv_resp.raise_for_status()
        counts_raw = inv_resp.json().get("counts", [])
    except Exception:
        counts_raw = []

    # Map variation_id → quantity
    inventory_map: dict[str, int] = {}
    for c in counts_raw:
        if c.get("state") == "IN_STOCK":
            inventory_map[c["catalog_object_id"]] = int(float(c.get("quantity", "0")))

    print(f"    ✓ Found inventory data for {len(inventory_map)} variation(s)")

    # ── 4. Ensure our backend is reachable ───────────────────────────────────
    print("\n  Connecting to bar-inventory backend…")
    try:
        our_get("/health")
        print("    ✓ Backend reachable")
    except Exception:
        print("    ✗ Cannot reach backend — start it first")
        sys.exit(1)

    # ── 5. Create a "Square POS" supplier placeholder ────────────────────────
    print("\n  Creating supplier placeholder…")
    existing_suppliers = {s["name"]: s for s in our_get("/inventory/suppliers")}
    supplier_name = f"Square POS — {location['name']}"

    if supplier_name in existing_suppliers:
        supplier = existing_suppliers[supplier_name]
        print(f"    → Already exists: {supplier_name} (id={supplier['id']})")
    else:
        supplier = our_post("/inventory/suppliers", {
            "name":           supplier_name,
            "contact_email":  f"pos@{location['name'].lower().replace(' ', '')}.example",
            "wallet_address": _random_algo_address(),
        })
        print(f"    ✓ Created: {supplier_name} (id={supplier['id']})")

    # ── 6. Import items as products + stock + catalog entries ────────────────
    print(f"\n  Importing {len(items)} item(s)…\n")

    existing_products = {p["name"]: p for p in our_get("/inventory/products")}
    existing_stock    = {s["product_id"]: s for s in our_get("/inventory/stock")}
    existing_catalog  = our_get("/inventory/catalog")
    cataloged_pairs   = {(c["supplier_id"], c["product_id"]) for c in existing_catalog}

    created = skipped = 0

    for item in items:
        data       = item.get("item_data", {})
        name       = data.get("name", "Unknown Item").strip()
        cat_id     = data.get("category_id", "")
        cat_name   = categories.get(cat_id, "")
        unit       = _infer_unit(name, cat_name)
        variations = data.get("variations", [])

        # Pick lowest price variation
        unit_price_algo = DEFAULT_MAX_PRICE
        variation_id    = None
        for v in variations:
            vd = v.get("item_variation_data", {})
            pm = vd.get("price_money", {})
            if pm.get("amount"):
                # Convert cents → ALGO (rough: 1 USD ≈ 5 ALGO for demo)
                price_algo = pm["amount"] / 100 / 5
                if price_algo < unit_price_algo or variation_id is None:
                    unit_price_algo = round(price_algo, 4)
                    variation_id    = v["id"]

        # Inventory quantity from Square (or default)
        quantity = inventory_map.get(variation_id, 0) if variation_id else 0

        print(f"  [{name}]")
        print(f"    unit={unit}  price={unit_price_algo:.4f} ALGO  qty={quantity}  category={cat_name or '—'}")

        # Product
        if name in existing_products:
            product = existing_products[name]
            print(f"    → Product already exists (id={product['id']})")
        else:
            product = our_post("/inventory/products", {
                "name":                 name,
                "unit":                 unit,
                "preferred_supplier_id": supplier["id"],
            })
            if not product:
                print("    ✗ Failed to create product, skipping")
                skipped += 1
                continue
            existing_products[name] = product
            print(f"    ✓ Product created (id={product['id']})")

        pid = product["id"]

        # Stock
        if pid in existing_stock:
            print(f"    → Stock already exists (qty={existing_stock[pid]['quantity']})")
        else:
            stock = our_post("/inventory/stock", {
                "product_id":    pid,
                "quantity":      quantity,
                "reorder_point": DEFAULT_REORDER_POINT,
                "reorder_qty":   DEFAULT_REORDER_QTY,
                "max_price":     unit_price_algo * 1.2,  # 20% headroom
            })
            if stock:
                existing_stock[pid] = stock
                status = "LOW ⚠" if quantity <= DEFAULT_REORDER_POINT else "OK ✓"
                print(f"    ✓ Stock created  qty={quantity}  reorder@{DEFAULT_REORDER_POINT}  [{status}]")

        # Catalog entry
        if (supplier["id"], pid) not in cataloged_pairs:
            result = our_post("/inventory/catalog", {
                "supplier_id":   supplier["id"],
                "product_id":    pid,
                "unit_price":    unit_price_algo,
                "min_order_qty": 1,
            })
            if result:
                cataloged_pairs.add((supplier["id"], pid))
                print(f"    ✓ Catalog entry  {unit_price_algo:.4f} ALGO/unit")
        else:
            print(f"    → Catalog entry already exists")

        created += 1
        print()

    # ── 7. Summary ───────────────────────────────────────────────────────────
    print(f"  Done — {created} item(s) imported, {skipped} skipped.\n")
    print("  Next steps:")
    print("    1. Open http://localhost:5173 → Inventory tab")
    print("    2. Items with qty ≤ 5 are already flagged LOW → click 'Generate Orders'")
    print("    3. Orders tab → Fund Escrow → select supplier → confirm\n")


if __name__ == "__main__":
    run()
