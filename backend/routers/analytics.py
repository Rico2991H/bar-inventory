from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from datetime import datetime, timedelta, timezone
import math

from backend.db.database import get_session
from backend.models.product import Budget, Order, OrderStatus, Product, SaleEvent, Stock, Supplier, SupplierProduct

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/summary")
def summary(session: Session = Depends(get_session)):
    orders  = session.exec(select(Order)).all()
    suppliers = {s.id: s for s in session.exec(select(Supplier)).all()}
    products  = {p.id: p for p in session.exec(select(Product)).all()}
    stocks    = {s.product_id: s for s in session.exec(select(Stock)).all()}

    # --- Budget ---
    budget_row = session.get(Budget, 1)
    total_budget = budget_row.total_budget if budget_row else 0.0
    active_statuses = {OrderStatus.FUNDED, OrderStatus.DELIVERED, OrderStatus.RELEASED}
    spent = sum(o.total_price for o in orders if o.status in active_statuses and o.total_price)
    budget = {
        "total":     total_budget,
        "spent":     round(spent, 4),
        "remaining": round(total_budget - spent, 4),
        "pct_used":  round((spent / total_budget * 100) if total_budget > 0 else 0, 1),
    }

    # --- Orders by status ---
    status_counts = {s.value: 0 for s in OrderStatus}
    for o in orders:
        status_counts[o.status.value] += 1

    # --- Spending per supplier ---
    supplier_spend: dict[int, float] = {}
    for o in orders:
        if o.status in active_statuses and o.total_price and o.supplier_id:
            supplier_spend[o.supplier_id] = supplier_spend.get(o.supplier_id, 0) + o.total_price
    spending_by_supplier = [
        {"name": suppliers[sid].name if sid in suppliers else f"Supplier {sid}",
         "spent": round(val, 4)}
        for sid, val in sorted(supplier_spend.items(), key=lambda x: -x[1])
    ]

    # --- Top products by order count ---
    product_orders: dict[int, dict] = {}
    for o in orders:
        if o.product_id not in product_orders:
            product_orders[o.product_id] = {"count": 0, "units": 0, "spent": 0.0}
        product_orders[o.product_id]["count"] += 1
        product_orders[o.product_id]["units"] += o.quantity
        if o.total_price and o.status in active_statuses:
            product_orders[o.product_id]["spent"] += o.total_price
    top_products = sorted(
        [
            {
                "name":    products[pid].name if pid in products else f"Product {pid}",
                "unit":    products[pid].unit if pid in products else "",
                "count":   d["count"],
                "units":   d["units"],
                "spent":   round(d["spent"], 4),
                "in_stock": stocks[pid].quantity if pid in stocks else 0,
            }
            for pid, d in product_orders.items()
        ],
        key=lambda x: -x["count"],
    )

    # --- KPIs ---
    kpis = {
        "total_orders":    len(orders),
        "active_escrows":  status_counts["funded"] + status_counts["delivered"],
        "total_spent":     round(spent, 4),
        "cancelled_orders": status_counts["cancelled"],
    }

    return {
        "budget":               budget,
        "kpis":                 kpis,
        "orders_by_status":     status_counts,
        "spending_by_supplier": spending_by_supplier,
        "top_products":         top_products,
    }


@router.get("/predictions")
def predictions(session: Session = Depends(get_session)):
    """Consumption velocity + stockout predictions per product."""
    now      = datetime.now(timezone.utc)
    window7  = now - timedelta(days=7)
    window30 = now - timedelta(days=30)

    products  = session.exec(select(Product)).all()
    stocks    = {s.product_id: s for s in session.exec(select(Stock)).all()}
    suppliers = {s.id: s for s in session.exec(select(Supplier)).all()}

    # Best catalog price per product (cheapest supplier)
    catalog_entries = session.exec(select(SupplierProduct)).all()
    best_price: dict[int, tuple[float, int]] = {}  # product_id → (unit_price, supplier_id)
    for e in catalog_entries:
        if e.product_id not in best_price or e.unit_price < best_price[e.product_id][0]:
            best_price[e.product_id] = (e.unit_price, e.supplier_id)

    # All sale events
    all_events = session.exec(select(SaleEvent)).all()
    events_by_product: dict[int, list[SaleEvent]] = {}
    for e in all_events:
        events_by_product.setdefault(e.product_id, []).append(e)

    results = []
    monthly_budget_projection = 0.0

    for product in products:
        stock = stocks.get(product.id)
        if not stock:
            continue

        events      = events_by_product.get(product.id, [])
        events_30d  = [e for e in events if e.sold_at.replace(tzinfo=timezone.utc) >= window30]
        events_7d   = [e for e in events if e.sold_at.replace(tzinfo=timezone.utc) >= window7]

        sold_30d = sum(e.quantity for e in events_30d)
        sold_7d  = sum(e.quantity for e in events_7d)

        has_data   = len(events_30d) >= 2
        velocity7  = round(sold_7d  / 7,  3) if events_7d  else None
        velocity30 = round(sold_30d / 30, 3) if events_30d else None

        # Use 7-day velocity if available (more recent), fall back to 30-day
        velocity = velocity7 if velocity7 is not None else velocity30

        days_until_stockout = None
        days_until_reorder  = None
        urgency             = "no_data"

        if velocity and velocity > 0:
            days_until_stockout = math.floor(stock.quantity / velocity)
            buffer = stock.quantity - stock.reorder_point
            days_until_reorder  = math.floor(buffer / velocity) if buffer > 0 else 0

            if days_until_stockout <= 3:
                urgency = "critical"
            elif days_until_stockout <= 7:
                urgency = "warning"
            else:
                urgency = "ok"
        elif stock.quantity <= stock.reorder_point:
            urgency = "critical"  # already below threshold, no velocity data

        # Monthly spend projection
        price, sup_id = best_price.get(product.id, (None, None))
        monthly_units = round(velocity30 * 30, 1) if velocity30 else None
        monthly_cost  = round(monthly_units * price, 4) if monthly_units and price else None
        if monthly_cost:
            monthly_budget_projection += monthly_cost

        reorder_by_date = None
        if days_until_reorder is not None and days_until_reorder >= 0:
            reorder_by_date = (now + timedelta(days=days_until_reorder)).strftime("%Y-%m-%d")

        results.append({
            "product_id":          product.id,
            "product_name":        product.name,
            "unit":                product.unit,
            "current_stock":       stock.quantity,
            "reorder_point":       stock.reorder_point,
            "has_data":            has_data,
            "velocity_7d":         velocity7,
            "velocity_30d":        velocity30,
            "days_until_stockout": days_until_stockout,
            "days_until_reorder":  days_until_reorder,
            "reorder_by_date":     reorder_by_date,
            "urgency":             urgency,
            "sold_last_7d":        sold_7d,
            "sold_last_30d":       sold_30d,
            "best_price_algo":     price,
            "best_supplier":       suppliers[sup_id].name if sup_id and sup_id in suppliers else None,
            "monthly_cost_proj":   monthly_cost,
        })

    # Sort: critical first, then warning, then ok, then no_data
    order_map = {"critical": 0, "warning": 1, "ok": 2, "no_data": 3}
    results.sort(key=lambda x: (order_map[x["urgency"]], x["days_until_stockout"] or 9999))

    return {
        "predictions":               results,
        "monthly_budget_projection": round(monthly_budget_projection, 4),
    }
