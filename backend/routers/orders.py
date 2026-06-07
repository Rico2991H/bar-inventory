from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select
import hashlib
import json

from backend.db.database import get_session
from backend.models.product import (
    Budget, Order, OrderStatus, Stock, StockLog, Supplier, SupplierProduct,
)
from backend.engine.rules import run_rule_engine
from backend.blockchain import service

router = APIRouter(prefix="/orders", tags=["Orders"])


class FundRequest(BaseModel):
    supplier_id: int

class RateRequest(BaseModel):
    stars: int        # 1–5
    note:  str = ""


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


@router.post("/generate")
def generate_orders(session: Session = Depends(get_session)):
    """Run the rule engine and persist PENDING order drafts for low-stock products."""
    drafts = run_rule_engine(session)

    if not drafts:
        return {"message": "No reorders needed", "orders": []}

    created_orders = []

    for draft in drafts:
        existing = session.exec(
            select(Order).where(
                Order.product_id == draft["product_id"],
                Order.status == OrderStatus.PENDING,
            )
        ).first()

        if existing:
            continue

        order = Order(
            product_id=draft["product_id"],
            quantity=draft["quantity"],
        )
        session.add(order)
        session.commit()
        session.refresh(order)
        created_orders.append(order)

    return {"message": f"{len(created_orders)} order(s) created", "orders": created_orders}


@router.post("/{order_id}/fund")
def fund_order(order_id: int, body: FundRequest, session: Session = Depends(get_session)):
    """Select a supplier, check budget, deploy + fund an on-chain escrow."""
    order = _get_order(order_id, session)
    if order.status != OrderStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Order must be PENDING to fund (is {order.status.value})",
        )

    # Resolve supplier and catalog price
    supplier = session.get(Supplier, body.supplier_id)
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")
    if not supplier.wallet_address:
        raise HTTPException(status_code=400, detail="Supplier has no wallet address")

    catalog_entry = session.exec(
        select(SupplierProduct).where(
            SupplierProduct.supplier_id == body.supplier_id,
            SupplierProduct.product_id == order.product_id,
        )
    ).first()

    if not catalog_entry:
        raise HTTPException(
            status_code=400,
            detail=f"Supplier {supplier.name} does not offer this product in their catalog",
        )

    unit_price  = catalog_entry.unit_price
    total_price = round(unit_price * order.quantity, 6)

    # Check budget
    budget = _get_budget_row(session)
    if budget.total_budget > 0:
        spent     = _budget_spent(session)
        remaining = budget.total_budget - spent
        if total_price > remaining:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Insufficient budget: order costs {total_price:.4f} ALGO "
                    f"but only {remaining:.4f} ALGO remaining "
                    f"(total {budget.total_budget:.4f}, spent {spent:.4f})"
                ),
            )

    amount = _algo_to_microalgos(total_price)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Order total must be positive")

    # Compute order_hash now that all fields are known
    order_data = {
        "product_id":  order.product_id,
        "supplier_id": body.supplier_id,
        "quantity":    order.quantity,
        "total_price": total_price,
    }
    order_hash = hashlib.sha256(
        json.dumps(order_data, sort_keys=True).encode()
    ).hexdigest()

    try:
        chain = service.create_and_fund_escrow(supplier.wallet_address, amount, order_hash)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Escrow funding failed: {e}")

    order.supplier_id    = body.supplier_id
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
    session.refresh(order)
    return order


@router.post("/{order_id}/confirm-delivery")
def confirm_delivery(order_id: int, session: Session = Depends(get_session)):
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

    stock = session.exec(select(Stock).where(Stock.product_id == order.product_id)).first()
    if stock:
        stock.quantity += order.quantity
        session.add(stock)
        session.add(StockLog(
            product_id=order.product_id,
            change=order.quantity,
            reason="restock",
            note=f"Order #{order.id}",
        ))

    session.commit()
    session.refresh(order)
    return order


@router.post("/{order_id}/release")
def release(order_id: int, session: Session = Depends(get_session)):
    order = _get_funded_order(order_id, session)
    if order.status == OrderStatus.RELEASED:
        raise HTTPException(status_code=400, detail="Order already released")
    if order.status != OrderStatus.DELIVERED:
        raise HTTPException(status_code=400, detail="Delivery must be confirmed before release")

    try:
        service.release(order.app_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Release failed: {e}")

    order.status = OrderStatus.RELEASED
    session.add(order)
    session.commit()
    session.refresh(order)
    return order


@router.post("/{order_id}/cancel")
def cancel_order(order_id: int, session: Session = Depends(get_session)):
    order = _get_order(order_id, session)
    if order.status == OrderStatus.CANCELLED:
        raise HTTPException(status_code=400, detail="Order is already cancelled")
    if order.status == OrderStatus.RELEASED:
        raise HTTPException(status_code=400, detail="Cannot cancel a released order")
    if order.status in (OrderStatus.FUNDED, OrderStatus.DELIVERED):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Order is {order.status.value} — escrow is funded on-chain. "
                "A contract refund() method is required to recover the ALGO (not yet implemented)."
            ),
        )

    order.status = OrderStatus.CANCELLED
    session.add(order)
    session.commit()
    session.refresh(order)
    return order


@router.post("/{order_id}/rate")
def rate_order(order_id: int, body: RateRequest, session: Session = Depends(get_session)):
    """Rate a supplier after payment has been released."""
    if not 1 <= body.stars <= 5:
        raise HTTPException(status_code=422, detail="stars must be between 1 and 5")

    order = _get_order(order_id, session)
    if order.status != OrderStatus.RELEASED:
        raise HTTPException(status_code=400, detail="Only released orders can be rated")

    order.rating      = body.stars
    order.rating_note = body.note.strip() or None
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


def _get_funded_order(order_id: int, session: Session) -> Order:
    order = _get_order(order_id, session)
    if order.app_id is None:
        raise HTTPException(status_code=400, detail="Order has no escrow yet — fund it first")
    return order
