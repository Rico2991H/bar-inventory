from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from backend.db.database import get_session
from backend.models.product import Product, Supplier, Stock
from backend.engine.rules import run_rule_engine
from backend.engine.reorder import check_reorder_needed
from backend.models.product import Product, Supplier, Stock, Order, OrderStatus
import hashlib
import json

# APIRouter is like a mini FastAPI app — we group related endpoints together
# prefix means all routes here start with /inventory
router = APIRouter(prefix="/inventory", tags=["Inventory"])


# --- SUPPLIER ENDPOINTS ---

@router.post("/suppliers")
def create_supplier(supplier: Supplier, session: Session = Depends(get_session)):
    # Depends(get_session) tells FastAPI to inject a db session automatically
    session.add(supplier)
    session.commit()
    session.refresh(supplier)  # gets the auto-generated id back
    return supplier

@router.get("/suppliers")
def get_suppliers(session: Session = Depends(get_session)):
    return session.exec(select(Supplier)).all()


# --- PRODUCT ENDPOINTS ---

@router.post("/products")
def create_product(product: Product, session: Session = Depends(get_session)):
    session.add(product)
    session.commit()
    session.refresh(product)
    return product

@router.get("/products")
def get_products(session: Session = Depends(get_session)):
    return session.exec(select(Product)).all()


# --- STOCK ENDPOINTS ---

@router.post("/stock")
def create_stock(stock: Stock, session: Session = Depends(get_session)):
    session.add(stock)
    session.commit()
    session.refresh(stock)
    return stock

@router.get("/stock")
def get_stock(session: Session = Depends(get_session)):
    return session.exec(select(Stock)).all()

# Decrease stock — this simulates a sale (your fake POS)
@router.post("/stock/{product_id}/sell")
def sell_product(product_id: int, quantity: int, session: Session = Depends(get_session)):
    # Step 1 — find and validate stock
    stock = session.exec(select(Stock).where(Stock.product_id == product_id)).first()

    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")
    if stock.quantity < quantity:
        raise HTTPException(status_code=400, detail="Not enough stock")

    # Step 2 — subtract and save
    stock.quantity -= quantity
    session.add(stock)
    session.commit()
    session.refresh(stock)

    # Step 3 — auto-trigger rule engine after every sale
    auto_orders = []
    drafts = run_rule_engine(session)

    for draft in drafts:
        # Only create if no pending order exists for this product
        existing = session.exec(
            select(Order).where(
                Order.product_id == draft["product_id"],
                Order.status != OrderStatus.RELEASED,
                Order.status != OrderStatus.CANCELLED
            )
        ).first()

        if existing:
            continue

        # Hash the order
        order_data = {
            "product_id":  draft["product_id"],
            "supplier_id": draft["supplier_id"],
            "quantity":    draft["quantity"],
            "total_price": draft["total_price"],
        }
        order_hash = hashlib.sha256(
            json.dumps(order_data, sort_keys=True).encode()
        ).hexdigest()

        order = Order(
            product_id  = draft["product_id"],
            supplier_id = draft["supplier_id"],
            quantity    = draft["quantity"],
            total_price = draft["total_price"],
            order_hash  = order_hash,
        )

        session.add(order)
        session.commit()
        session.refresh(order)
        auto_orders.append(order)

    # Step 4 — return stock update + any auto-generated orders
    return {
        "stock": stock.model_dump(),
        "auto_orders": auto_orders
    }

@router.get("/orders/preview")
def preview_orders(session: Session = Depends(get_session)):
    # Runs the full rule engine and returns order drafts
    # Nothing is committed yet — this is just a preview
    return run_rule_engine(session)

@router.get("/reorder-check")
def reorder_check(session: Session = Depends(get_session)):
    return check_reorder_needed(session)