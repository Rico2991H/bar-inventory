from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from backend.db.database import get_session
from backend.models.product import Order, OrderStatus
from backend.engine.rules import run_rule_engine
from backend.models.product import Order, OrderStatus, Stock
import hashlib
import json

from backend.db.database import get_session
from backend.models.product import Order, OrderStatus, Supplier
from backend.engine.rules import run_rule_engine
from backend.blockchain import service

router = APIRouter(prefix="/orders", tags=["Orders"])


def _algo_to_microalgos(total_price: float) -> int:
    """Order totals are denominated in ALGO; the escrow works in microalgos."""
    return int(round(total_price * 1_000_000))


@router.post("/generate")
def generate_orders(session: Session = Depends(get_session)):
    """Phases 1-5 — run the rule engine and persist PENDING order drafts."""
    # Step 1 — run the rule engine to get order drafts
    drafts = run_rule_engine(session)

    if not drafts:
        return {"message": "No reorders needed", "orders": []}

    created_orders = []

    for draft in drafts:
        # Step 2 — check if a pending order already exists for this product
        # prevents duplicate orders being created
        existing = session.exec(
            select(Order).where(
                Order.product_id == draft["product_id"],
                Order.status == OrderStatus.PENDING
            )
        ).first()

        if existing:
            created_orders.append(existing)
            continue

        # Step 3 — hash the order for tamper-proof binding to Algorand later
        order_data = {
            "product_id":  draft["product_id"],
            "supplier_id": draft["supplier_id"],
            "quantity":    draft["quantity"],
            "total_price": draft["total_price"],
        }
        order_hash = hashlib.sha256(
            json.dumps(order_data, sort_keys=True).encode()
        ).hexdigest()

        # Step 4 — persist the order to the database
        order = Order(
            product_id   = draft["product_id"],
            supplier_id  = draft["supplier_id"],
            quantity     = draft["quantity"],
            total_price  = draft["total_price"],
            order_hash   = order_hash,
        )

        session.add(order)
        session.commit()
        session.refresh(order)
        created_orders.append(order)

    return {"message": f"{len(created_orders)} order(s) created", "orders": created_orders}


@router.post("/{order_id}/fund")
def fund_order(order_id: int, session: Session = Depends(get_session)):
    """Phase 8 — deploy + fund an on-chain escrow for a PENDING order."""
    order = _get_order(order_id, session)
    if order.status != OrderStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Order must be PENDING to fund (is {order.status.value})",
        )

    supplier = session.get(Supplier, order.supplier_id)
    if not supplier or not supplier.wallet_address:
        raise HTTPException(
            status_code=400, detail="Supplier has no wallet address for payouts"
        )

    amount = _algo_to_microalgos(order.total_price)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Order total must be positive")

    try:
        chain = service.create_and_fund_escrow(supplier.wallet_address, amount)
    except Exception as e:  # surface chain/connectivity errors clearly
        raise HTTPException(status_code=502, detail=f"Escrow funding failed: {e}")

    order.status = OrderStatus.FUNDED
    order.escrow_address = chain["app_address"]
    order.app_id = chain["app_id"]
    order.txn_id = chain["fund_tx"]
    session.add(order)
    session.commit()
    session.refresh(order)
    return order


@router.post("/{order_id}/confirm-delivery")
def confirm_delivery(order_id: int, session: Session = Depends(get_session)):
    """Phase 9 — confirm the goods were delivered for this order."""
    order = _get_funded_order(order_id, session)
    if order.status == OrderStatus.RELEASED:
        raise HTTPException(status_code=400, detail="Order already released")
    if order.status == OrderStatus.DELIVERED:
        raise HTTPException(status_code=400, detail="Delivery already confirmed")
    if order.status != OrderStatus.FUNDED:
        raise HTTPException(status_code=400, detail="Order is not funded")

    try:
        service.confirm_delivery(order.app_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Confirm delivery failed: {e}")

    order.status = OrderStatus.DELIVERED
    session.add(order)
    session.commit()
    session.refresh(order)
    return order


@router.post("/{order_id}/release")
def release(order_id: int, session: Session = Depends(get_session)):
    """Phase 10 — release the escrowed funds to the supplier."""
    order = _get_funded_order(order_id, session)
    if order.status == OrderStatus.RELEASED:
        raise HTTPException(status_code=400, detail="Order already released")
    if order.status != OrderStatus.DELIVERED:
        raise HTTPException(
            status_code=400, detail="Delivery must be confirmed before release"
        )

    try:
        service.release(order.app_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Release failed: {e}")

    order.status = OrderStatus.RELEASED
    session.add(order)
    session.commit()
    session.refresh(order)
    return order


@router.get("/")
def get_orders(session: Session = Depends(get_session)):
    return session.exec(select(Order)).all()


@router.get("/{order_id}")
def get_order(order_id: int, session: Session = Depends(get_session)):
    return _get_order(order_id, session)


def _get_order(order_id: int, session: Session) -> Order:
    order = session.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

def _get_order(order_id: int, session: Session) -> Order:
    order = session.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

def _get_funded_order(order_id: int, session: Session) -> Order:
    order = _get_order(order_id, session)
    if order.app_id is None:
        raise HTTPException(status_code=400, detail="Order has no escrow yet — fund it first")
    return order

@router.post("/{order_id}/confirm-delivery")
def confirm_delivery(order_id: int, session: Session = Depends(get_session)):
    order = session.exec(select(Order).where(Order.id == order_id)).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status not in [OrderStatus.PENDING, OrderStatus.FUNDED]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot confirm delivery for order with status: {order.status}"
        )

    stock = session.exec(
        select(Stock).where(Stock.product_id == order.product_id)
    ).first()

    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found for this product")

    stock.quantity += order.quantity
    session.add(stock)

    order.status = OrderStatus.DELIVERED
    session.add(order)

    session.commit()
    session.refresh(order)
    session.refresh(stock)

    return {
        "message": "Delivery confirmed, stock restored",
        "order": order,
        "updated_stock": stock.model_dump()
    }
