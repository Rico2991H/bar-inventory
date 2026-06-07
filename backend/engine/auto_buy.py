"""Auto-buy engine: automatically funds escrow for a PENDING order.

Two modes:
  fixed  – use the supplier configured in AutoBuyConfig
  ai     – call Claude (Haiku) to compare all catalog offers and pick the best one

Called after a new PENDING order is created (sell endpoint, simulation skip-day).
If anything fails the order stays PENDING so the user can fund it manually.
"""

import hashlib
import json
import os
from datetime import datetime, timezone

from sqlmodel import Session, select

from backend.blockchain import service
from backend.models.product import (
    AutoBuyConfig, Budget, Order, OrderStatus,
    SupplierProduct, Supplier, Product,
)


# ---------------------------------------------------------------------------
# Budget helpers (duplicated from orders.py to avoid circular import)
# ---------------------------------------------------------------------------

def _algo_to_microalgos(total_price: float) -> int:
    return int(round(total_price * 1_000_000))


def _get_budget_row(session: Session) -> Budget:
    row = session.get(Budget, 1)
    if not row:
        row = Budget(id=1, total_budget=0.0)
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def _budget_spent(session: Session) -> float:
    orders = session.exec(
        select(Order).where(
            Order.status.in_([OrderStatus.FUNDED, OrderStatus.DELIVERED, OrderStatus.RELEASED])
        )
    ).all()
    return sum(o.total_price for o in orders if o.total_price is not None)


# ---------------------------------------------------------------------------
# AI supplier selection
# ---------------------------------------------------------------------------

def _ai_pick_supplier(
    product: Product,
    entries: list,
    suppliers: dict,
    ratings: dict,
    budget_remaining: float,
) -> tuple:
    """Ask Claude Haiku to pick the best supplier. Returns (supplier_id, reasoning)."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        cheapest = min(entries, key=lambda e: e.unit_price)
        return cheapest.supplier_id, "ANTHROPIC_API_KEY not set — chose cheapest option"

    try:
        import anthropic

        options = []
        for e in entries:
            sup = suppliers.get(e.supplier_id)
            if not sup:
                continue
            r = ratings.get(e.supplier_id, {})
            options.append({
                "supplier_id":    e.supplier_id,
                "name":           sup.name,
                "unit_price_algo": e.unit_price,
                "min_order_qty":  e.min_order_qty,
                "avg_rating":     r.get("avg"),
                "rating_count":   r.get("count", 0),
            })

        if not options:
            return None, "No supplier options available"

        prompt = (
            f"You are a procurement agent for a bar. Select the best supplier for a reorder.\n\n"
            f"Product: {product.name} ({product.unit})\n"
            f"Remaining procurement budget: {budget_remaining:.4f} ALGO\n\n"
            f"Supplier options:\n{json.dumps(options, indent=2)}\n\n"
            "Consider: unit price (lower is better), ratings (5 = best, prefer rated suppliers), "
            "and minimum order quantities. Return the supplier_id and a brief one-sentence reason."
        )

        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            tools=[{
                "name": "select_supplier",
                "description": "Select the best supplier for the reorder",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "supplier_id": {
                            "type": "integer",
                            "description": "ID of the chosen supplier"
                        },
                        "reasoning": {
                            "type": "string",
                            "description": "One sentence explaining the choice"
                        },
                    },
                    "required": ["supplier_id", "reasoning"],
                },
            }],
            tool_choice={"type": "any"},
            messages=[{"role": "user", "content": prompt}],
        )

        for block in response.content:
            if block.type == "tool_use" and block.name == "select_supplier":
                sid       = block.input.get("supplier_id")
                reasoning = block.input.get("reasoning", "")
                valid_ids = {o["supplier_id"] for o in options}
                if sid in valid_ids:
                    return sid, reasoning

        # Claude returned something unexpected — fall back to cheapest
        cheapest = min(options, key=lambda o: o["unit_price_algo"])
        return cheapest["supplier_id"], "AI response unclear — chose cheapest option"

    except Exception as exc:
        # Any error (network, import, etc.) → cheapest fallback
        cheapest = min(entries, key=lambda e: e.unit_price)
        return cheapest.supplier_id, f"AI error ({exc}) — chose cheapest option"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def try_auto_fund_order(order_id: int, session: Session) -> dict:
    """
    Try to automatically fund a PENDING order based on its product's AutoBuyConfig.
    Returns {"funded": bool, "supplier": str|None, "reason": str}.
    Safe to call unconditionally — returns immediately if auto-buy is not configured.
    """
    order = session.get(Order, order_id)
    if not order or order.status != OrderStatus.PENDING:
        return {"funded": False, "supplier": None, "reason": "not pending"}

    config = session.exec(
        select(AutoBuyConfig).where(AutoBuyConfig.product_id == order.product_id)
    ).first()

    if not config or not config.enabled:
        return {"funded": False, "supplier": None, "reason": "auto-buy disabled"}

    entries  = session.exec(
        select(SupplierProduct).where(SupplierProduct.product_id == order.product_id)
    ).all()
    if not entries:
        return {"funded": False, "supplier": None, "reason": "no catalog entries"}

    suppliers = {s.id: s for s in session.exec(select(Supplier)).all()}
    product   = session.get(Product, order.product_id)

    # --- Determine supplier ---
    if config.mode == "fixed":
        if not config.supplier_id:
            return {"funded": False, "supplier": None, "reason": "fixed mode but no supplier set"}
        entry = next((e for e in entries if e.supplier_id == config.supplier_id), None)
        if not entry:
            return {"funded": False, "supplier": None, "reason": "configured supplier not in catalog"}
        supplier_id = config.supplier_id
        reasoning   = "Vorgegebener Lieferant"

    else:  # ai mode
        budget    = _get_budget_row(session)
        spent     = _budget_spent(session)
        remaining = budget.total_budget - spent

        # Collect ratings per supplier
        ratings: dict = {}
        for e in entries:
            rated = session.exec(
                select(Order).where(
                    Order.supplier_id == e.supplier_id,
                    Order.rating.isnot(None),
                )
            ).all()
            if rated:
                ratings[e.supplier_id] = {
                    "avg":   round(sum(o.rating for o in rated) / len(rated), 1),
                    "count": len(rated),
                }

        supplier_id, reasoning = _ai_pick_supplier(product, entries, suppliers, ratings, remaining)
        if not supplier_id:
            return {"funded": False, "supplier": None, "reason": reasoning}

        entry = next((e for e in entries if e.supplier_id == supplier_id), None)
        if not entry:
            return {"funded": False, "supplier": None, "reason": "AI chose supplier not in catalog"}

        # Persist the AI reasoning so the frontend can display it
        sup_name = suppliers.get(supplier_id)
        config.last_ai_choice = json.dumps({
            "supplier_id":   supplier_id,
            "supplier_name": sup_name.name if sup_name else str(supplier_id),
            "reasoning":     reasoning,
            "at":            datetime.now(timezone.utc).isoformat(),
        })
        session.add(config)

    supplier = suppliers.get(supplier_id)
    if not supplier or not supplier.wallet_address:
        return {"funded": False, "supplier": None, "reason": "supplier has no wallet"}

    unit_price  = entry.unit_price
    total_price = round(unit_price * order.quantity, 6)
    amount      = _algo_to_microalgos(total_price)

    if amount <= 0:
        return {"funded": False, "supplier": None, "reason": "order total is zero"}

    # Budget guard
    budget    = _get_budget_row(session)
    if budget.total_budget > 0:
        spent     = _budget_spent(session)
        remaining = budget.total_budget - spent
        if total_price > remaining:
            return {
                "funded":   False,
                "supplier": supplier.name,
                "reason":   f"budget zu niedrig ({total_price:.4f} > {remaining:.4f} ALGO)",
            }

    # Hash
    order_hash = hashlib.sha256(json.dumps({
        "product_id":  order.product_id,
        "supplier_id": supplier_id,
        "quantity":    order.quantity,
        "total_price": total_price,
    }, sort_keys=True).encode()).hexdigest()

    # Blockchain
    try:
        chain = service.create_and_fund_escrow(supplier.wallet_address, amount, order_hash)
    except Exception as exc:
        return {"funded": False, "supplier": supplier.name, "reason": f"Blockchain-Fehler: {exc}"}

    # Persist funded order
    order.supplier_id    = supplier_id
    order.unit_price     = unit_price
    order.total_price    = total_price
    order.order_hash     = order_hash
    order.status         = OrderStatus.FUNDED
    order.escrow_address = chain["app_address"]
    order.app_id         = chain["app_id"]
    order.create_txn_id  = chain["create_tx"]
    order.txn_id         = chain["fund_tx"]
    session.add(order)
    session.commit()

    return {"funded": True, "supplier": supplier.name, "reason": reasoning}
