from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select
from backend.db.database import get_session
from backend.models.product import AutoBuyConfig, Budget, Order, OrderStatus, Product, SaleEvent, Stock, StockLog, Supplier, SupplierProduct
from backend.engine.rules import run_rule_engine
from backend.engine.reorder import check_reorder_needed
from backend.engine.auto_buy import try_auto_fund_order

router = APIRouter(prefix="/inventory", tags=["Inventory"])


# --- SUPPLIERS ---

@router.post("/suppliers")
def create_supplier(supplier: Supplier, session: Session = Depends(get_session)):
    session.add(supplier)
    session.commit()
    session.refresh(supplier)
    return supplier

@router.get("/suppliers")
def get_suppliers(session: Session = Depends(get_session)):
    return session.exec(select(Supplier)).all()

@router.get("/suppliers/ratings")
def get_supplier_ratings(session: Session = Depends(get_session)):
    """Returns each supplier with aggregated rating stats and recent reviews."""
    suppliers = session.exec(select(Supplier)).all()
    rated_orders = session.exec(
        select(Order).where(Order.rating != None)
    ).all()

    # Group by supplier
    from collections import defaultdict
    by_supplier: dict[int, list] = defaultdict(list)
    for o in rated_orders:
        if o.supplier_id:
            by_supplier[o.supplier_id].append(o)

    result = []
    for sup in suppliers:
        orders = by_supplier.get(sup.id, [])
        ratings = [o.rating for o in orders]
        avg = round(sum(ratings) / len(ratings), 1) if ratings else None
        result.append({
            "id":             sup.id,
            "name":           sup.name,
            "contact_email":  sup.contact_email,
            "wallet_address": sup.wallet_address,
            "avg_rating":     avg,
            "rating_count":   len(ratings),
            "reviews": [
                {
                    "order_id":    o.id,
                    "stars":       o.rating,
                    "note":        o.rating_note,
                    "total_price": o.total_price,
                }
                for o in sorted(orders, key=lambda x: x.id, reverse=True)[:5]
            ],
        })
    return result


# --- PRODUCTS ---

@router.post("/products")
def create_product(product: Product, session: Session = Depends(get_session)):
    session.add(product)
    session.commit()
    session.refresh(product)
    return product

@router.get("/products")
def get_products(session: Session = Depends(get_session)):
    return session.exec(select(Product)).all()


# --- STOCK ---

@router.post("/stock")
def create_stock(stock: Stock, session: Session = Depends(get_session)):
    session.add(stock)
    session.commit()
    session.refresh(stock)
    return stock

@router.get("/stock")
def get_stock(session: Session = Depends(get_session)):
    return session.exec(select(Stock)).all()

@router.post("/stock/{product_id}/sell")
def sell_product(product_id: int, quantity: int, session: Session = Depends(get_session)):
    stock = session.exec(select(Stock).where(Stock.product_id == product_id)).first()
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")
    if stock.quantity < quantity:
        raise HTTPException(status_code=400, detail="Not enough stock")

    stock.quantity -= quantity
    session.add(stock)
    session.add(SaleEvent(product_id=product_id, quantity=quantity))
    session.add(StockLog(product_id=product_id, change=-quantity, reason="sale"))
    session.commit()
    session.refresh(stock)

    auto_orders = []
    drafts = run_rule_engine(session)

    for draft in drafts:
        existing = session.exec(
            select(Order).where(
                Order.product_id == draft["product_id"],
                Order.status == OrderStatus.PENDING,
            )
        ).first()
        if existing:
            # Order already exists — still try auto-buy in case it wasn't active before
            try_auto_fund_order(existing.id, session)
            continue

        order = Order(
            product_id=draft["product_id"],
            quantity=draft["quantity"],
        )
        session.add(order)
        session.commit()
        session.refresh(order)
        auto_orders.append(order)
        try_auto_fund_order(order.id, session)

    return {
        "stock": {
            "id": stock.id,
            "product_id": stock.product_id,
            "quantity": stock.quantity,
            "reorder_point": stock.reorder_point,
            "reorder_qty": stock.reorder_qty,
            "max_price": stock.max_price,
        },
        "auto_orders": [
            {"id": o.id, "product_id": o.product_id, "quantity": o.quantity, "status": o.status}
            for o in auto_orders
        ],
    }


# --- ACTIVITY LOG ---

@router.get("/activity")
def get_activity(limit: int = 40, session: Session = Depends(get_session)):
    """Recent stock movements (ins and outs) for the Inventory tab log."""
    products = {p.id: p for p in session.exec(select(Product)).all()}
    logs = session.exec(
        select(StockLog).order_by(StockLog.logged_at.desc()).limit(limit)
    ).all()
    return [
        {
            "id":           l.id,
            "product_id":   l.product_id,
            "product_name": products[l.product_id].name if l.product_id in products else f"#{l.product_id}",
            "unit":         products[l.product_id].unit  if l.product_id in products else "",
            "change":       l.change,
            "reason":       l.reason,
            "note":         l.note,
            "logged_at":    l.logged_at.isoformat(),
        }
        for l in logs
    ]


# --- SUPPLIER CATALOG ---

class CatalogEntry(BaseModel):
    supplier_id:   int
    product_id:    int
    unit_price:    float
    min_order_qty: int = 1

@router.post("/catalog")
def add_catalog_entry(entry: CatalogEntry, session: Session = Depends(get_session)):
    existing = session.exec(
        select(SupplierProduct).where(
            SupplierProduct.supplier_id == entry.supplier_id,
            SupplierProduct.product_id  == entry.product_id,
        )
    ).first()
    if existing:
        existing.unit_price    = entry.unit_price
        existing.min_order_qty = entry.min_order_qty
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing

    row = SupplierProduct(**entry.model_dump())
    session.add(row)
    session.commit()
    session.refresh(row)
    return row

@router.get("/catalog")
def get_catalog(session: Session = Depends(get_session)):
    return session.exec(select(SupplierProduct)).all()

@router.get("/catalog/product/{product_id}")
def get_catalog_for_product(product_id: int, session: Session = Depends(get_session)):
    """All suppliers offering a specific product, with prices."""
    entries = session.exec(
        select(SupplierProduct).where(SupplierProduct.product_id == product_id)
    ).all()
    result = []
    for e in entries:
        supplier = session.get(Supplier, e.supplier_id)
        result.append({
            "catalog_id":    e.id,
            "supplier_id":   e.supplier_id,
            "supplier_name": supplier.name if supplier else "?",
            "unit_price":    e.unit_price,
            "min_order_qty": e.min_order_qty,
        })
    return result

@router.delete("/catalog/{catalog_id}")
def delete_catalog_entry(catalog_id: int, session: Session = Depends(get_session)):
    entry = session.get(SupplierProduct, catalog_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Catalog entry not found")
    session.delete(entry)
    session.commit()
    return {"ok": True}


# --- BUDGET ---

class BudgetUpdate(BaseModel):
    total_budget: float

@router.get("/budget")
def get_budget(session: Session = Depends(get_session)):
    row = session.get(Budget, 1)
    if not row:
        row = Budget(id=1, total_budget=0.0)
        session.add(row)
        session.commit()
        session.refresh(row)

    funded_orders = session.exec(
        select(Order).where(
            Order.status.in_([OrderStatus.FUNDED, OrderStatus.DELIVERED, OrderStatus.RELEASED])
        )
    ).all()
    spent     = sum(o.total_price for o in funded_orders if o.total_price is not None)
    remaining = row.total_budget - spent
    return {
        "total_budget": row.total_budget,
        "spent":        round(spent, 6),
        "remaining":    round(remaining, 6),
    }

@router.put("/budget")
def set_budget(body: BudgetUpdate, session: Session = Depends(get_session)):
    row = session.get(Budget, 1)
    if not row:
        row = Budget(id=1, total_budget=body.total_budget)
    else:
        row.total_budget = body.total_budget
    session.add(row)
    session.commit()
    session.refresh(row)
    return {"total_budget": row.total_budget}


# --- MISC ---

@router.get("/orders/preview")
def preview_orders(session: Session = Depends(get_session)):
    return run_rule_engine(session)

@router.get("/reorder-check")
def reorder_check(session: Session = Depends(get_session)):
    return check_reorder_needed(session)


# --- AUTO-BUY CONFIG ---

class AutoBuyUpdate(BaseModel):
    enabled:     bool
    mode:        str        # "fixed" | "ai"
    supplier_id: int | None = None


@router.get("/auto-buy")
def get_auto_buy_configs(session: Session = Depends(get_session)):
    """Return auto-buy status for every product (row is created on first PUT)."""
    products  = session.exec(select(Product)).all()
    configs   = {c.product_id: c for c in session.exec(select(AutoBuyConfig)).all()}
    suppliers = {s.id: s.name for s in session.exec(select(Supplier)).all()}

    result = []
    for p in products:
        cfg = configs.get(p.id)
        import json as _json
        last_choice = None
        if cfg and cfg.last_ai_choice:
            try:
                last_choice = _json.loads(cfg.last_ai_choice)
            except Exception:
                pass
        result.append({
            "product_id":    p.id,
            "product_name":  p.name,
            "unit":          p.unit,
            "enabled":       cfg.enabled      if cfg else False,
            "mode":          cfg.mode         if cfg else "fixed",
            "supplier_id":   cfg.supplier_id  if cfg else None,
            "supplier_name": suppliers.get(cfg.supplier_id) if cfg and cfg.supplier_id else None,
            "last_ai_choice": last_choice,
        })
    return result


@router.put("/auto-buy/{product_id}")
def set_auto_buy_config(product_id: int, body: AutoBuyUpdate, session: Session = Depends(get_session)):
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    cfg = session.exec(
        select(AutoBuyConfig).where(AutoBuyConfig.product_id == product_id)
    ).first()

    if not cfg:
        cfg = AutoBuyConfig(product_id=product_id)
        session.add(cfg)

    cfg.enabled     = body.enabled
    cfg.mode        = body.mode
    cfg.supplier_id = body.supplier_id if body.mode == "fixed" else cfg.supplier_id
    session.add(cfg)
    session.commit()
    session.refresh(cfg)
    return cfg
