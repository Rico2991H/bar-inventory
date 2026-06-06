from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from backend.db.database import get_session
from backend.models.product import Order, OrderStatus
from backend.engine.rules import run_rule_engine
import hashlib
import json

router = APIRouter(prefix="/orders", tags=["Orders"])


@router.post("/generate")
def generate_orders(session: Session = Depends(get_session)):
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


@router.get("/")
def get_orders(session: Session = Depends(get_session)):
    return session.exec(select(Order)).all()


@router.get("/{order_id}")
def get_order(order_id: int, session: Session = Depends(get_session)):
    order = session.exec(select(Order).where(Order.id == order_id)).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order