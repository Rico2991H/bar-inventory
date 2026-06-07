"""Square POS webhook receiver.

Square fires events at this endpoint when things happen in the POS
(order completed, inventory updated, etc.). We map those events to
stock decrements and auto-trigger the rule engine.

Setup:
  1. Run ngrok:           ngrok http 8000
  2. Copy the public URL: https://abc123.ngrok-free.app
  3. In Square Developer Dashboard → Webhooks → Add endpoint:
       URL:    https://abc123.ngrok-free.app/webhooks/square
       Events: order.updated
  4. Copy the Webhook Signature Key and set:
       $env:SQUARE_WEBHOOK_KEY = "V0..."
  5. Set your token too (needed to fetch order details):
       $env:SQUARE_TOKEN = "EAAAl..."
"""

import base64
import hashlib
import hmac
import json
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session, select

from backend.db.database import get_session
from backend.engine.rules import run_rule_engine
from backend.models.product import Order, OrderStatus, Product, SaleEvent, Stock

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

SQUARE_BASE = "https://connect.squareupsandbox.com/v2"

# In-memory log of the last 20 webhook events — readable via GET /webhooks/events
_event_log: list[dict] = []


def _verify_signature(body: bytes, signature: str, url: str) -> bool:
    key = os.getenv("SQUARE_WEBHOOK_KEY", "")
    if not key:
        return True  # dev mode: skip verification when key not configured
    payload  = (url + body.decode("utf-8")).encode("utf-8")
    expected = base64.b64encode(
        hmac.new(key.encode("utf-8"), payload, hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(expected, signature)


def _fetch_square_order(order_id: str) -> dict | None:
    token = os.getenv("SQUARE_TOKEN", "")
    if not token:
        return None
    try:
        r = httpx.get(
            f"{SQUARE_BASE}/orders/{order_id}",
            headers={"Authorization": f"Bearer {token}", "Square-Version": "2024-01-18"},
            timeout=10,
        )
        r.raise_for_status()
        return r.json().get("order")
    except Exception:
        return None


def _handle_completed_order(square_order_id: str, session: Session) -> list[str]:
    """Decrement stock for each sold item and run the rule engine."""
    order = _fetch_square_order(square_order_id)
    if not order:
        return ["Could not fetch order from Square"]

    line_items = order.get("line_items", [])
    if not line_items:
        return ["Order has no line items"]

    products_by_name = {
        p.name.lower(): p
        for p in session.exec(select(Product)).all()
    }

    log = []
    for item in line_items:
        name     = item.get("name", "").strip()
        quantity = int(float(item.get("quantity", "0")))
        if quantity <= 0:
            continue

        product = products_by_name.get(name.lower())
        if not product:
            log.append(f"  skip '{name}' — not in our DB")
            continue

        stock = session.exec(
            select(Stock).where(Stock.product_id == product.id)
        ).first()
        if not stock:
            log.append(f"  skip '{name}' — no stock entry")
            continue

        before = stock.quantity
        stock.quantity = max(0, stock.quantity - quantity)
        session.add(stock)
        session.add(SaleEvent(product_id=product.id, quantity=quantity))
        log.append(f"  '{name}': {before} → {stock.quantity} (sold {quantity})")

    session.commit()

    # Auto-generate orders for anything that dropped below reorder point
    drafts = run_rule_engine(session)
    for draft in drafts:
        existing = session.exec(
            select(Order).where(
                Order.product_id == draft["product_id"],
                Order.status == OrderStatus.PENDING,
            )
        ).first()
        if existing:
            continue
        session.add(Order(product_id=draft["product_id"], quantity=draft["quantity"]))
        log.append(f"  → reorder triggered for product #{draft['product_id']}")
    session.commit()

    return log


@router.post("/square")
async def square_webhook(request: Request, session: Session = Depends(get_session)):
    body = await request.body()
    sig  = request.headers.get("x-square-hmacsha256-signature", "")

    if not _verify_signature(body, sig, str(request.url)):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    event      = json.loads(body)
    event_type = event.get("type", "unknown")
    entry      = {"type": event_type, "log": []}

    if event_type == "order.updated":
        obj   = event.get("data", {}).get("object", {}).get("order_updated", {})
        state = obj.get("state")
        oid   = obj.get("order_id")

        entry["order_id"] = oid
        entry["state"]    = state

        if state == "COMPLETED" and oid:
            entry["log"] = _handle_completed_order(oid, session)
        else:
            entry["log"] = [f"Ignored — state={state}"]

    # Keep last 20 events in memory
    _event_log.insert(0, entry)
    del _event_log[20:]

    return {"ok": True}


@router.get("/events")
def get_events():
    """Last 20 webhook events — useful for debugging."""
    return _event_log
