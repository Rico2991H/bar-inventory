from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from backend.db.database import get_session
from backend.models.product import Supplier
from backend.models.order import Order, OrderCreate
from backend.blockchain import service

router = APIRouter(prefix="/orders", tags=["Orders"])


@router.post("")
def create_order(body: OrderCreate, session: Session = Depends(get_session)):
    """Phase 8 — create an order and back it with a funded on-chain escrow."""
    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="amount must be positive")
    if body.quantity <= 0:
        raise HTTPException(status_code=400, detail="quantity must be positive")

    supplier = session.get(Supplier, body.supplier_id)
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")
    if not supplier.wallet_address:
        raise HTTPException(
            status_code=400, detail="Supplier has no wallet address for payouts"
        )

    try:
        chain = service.create_and_fund_escrow(supplier.wallet_address, body.amount)
    except Exception as e:  # surface chain/connectivity errors clearly
        raise HTTPException(status_code=502, detail=f"Escrow creation failed: {e}")

    order = Order(
        product_id=body.product_id,
        supplier_id=body.supplier_id,
        quantity=body.quantity,
        amount=body.amount,
        status="funded",
        app_id=chain["app_id"],
        app_address=chain["app_address"],
        create_tx=chain["create_tx"],
        fund_tx=chain["fund_tx"],
    )
    session.add(order)
    session.commit()
    session.refresh(order)
    return order


@router.get("")
def list_orders(session: Session = Depends(get_session)):
    return session.exec(select(Order)).all()


@router.get("/{order_id}")
def get_order(order_id: int, session: Session = Depends(get_session)):
    order = session.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.post("/{order_id}/confirm-delivery")
def confirm_delivery(order_id: int, session: Session = Depends(get_session)):
    """Phase 9 — confirm the goods were delivered for this order."""
    order = _get_order_with_escrow(order_id, session)
    if order.status == "released":
        raise HTTPException(status_code=400, detail="Order already released")
    if order.status == "delivered":
        raise HTTPException(status_code=400, detail="Delivery already confirmed")
    if order.status != "funded":
        raise HTTPException(status_code=400, detail="Order is not funded")

    try:
        result = service.confirm_delivery(order.app_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Confirm delivery failed: {e}")

    order.status = "delivered"
    order.delivery_tx = result["tx"]
    session.add(order)
    session.commit()
    session.refresh(order)
    return order


@router.post("/{order_id}/release")
def release(order_id: int, session: Session = Depends(get_session)):
    """Phase 10 — release the escrowed funds to the supplier."""
    order = _get_order_with_escrow(order_id, session)
    if order.status == "released":
        raise HTTPException(status_code=400, detail="Order already released")
    if order.status != "delivered":
        raise HTTPException(
            status_code=400, detail="Delivery must be confirmed before release"
        )

    try:
        result = service.release(order.app_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Release failed: {e}")

    order.status = "released"
    order.release_tx = result["tx"]
    session.add(order)
    session.commit()
    session.refresh(order)
    return order


def _get_order_with_escrow(order_id: int, session: Session) -> Order:
    order = session.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.app_id is None:
        raise HTTPException(status_code=400, detail="Order has no escrow app")
    return order
