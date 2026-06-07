"""Time simulation for demo purposes.

Each "skip day" advances an internal simulation clock by one day,
generates realistic sales for that day (velocity-based with ±30% noise),
decrements stock, and triggers the rule engine.

The clock starts 29 days in the past so events immediately fall inside
the 30-day velocity window used by /analytics/predictions.
"""

import random
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from backend.db.database import get_session
from backend.engine.rules import run_rule_engine
from backend.engine.auto_buy import try_auto_fund_order
from backend.models.product import (
    Order, OrderStatus, Product, SaleEvent, SimulationClock, Stock, StockLog,
)

router = APIRouter(prefix="/simulation", tags=["Simulation"])


def _velocity(product_id: int, events: list[SaleEvent]) -> float:
    """Average daily sales over the last 30 days. Falls back to reorder_qty/30."""
    now    = datetime.now(timezone.utc)
    window = now - timedelta(days=30)
    recent = [e for e in events if e.sold_at.replace(tzinfo=timezone.utc) >= window]
    if len(recent) >= 2:
        return sum(e.quantity for e in recent) / 30
    return None


@router.get("/state")
def sim_state(session: Session = Depends(get_session)):
    clock = session.get(SimulationClock, 1)
    if not clock or not clock.sim_start_real:
        return {"sim_day": 0, "started": False, "current_sim_date": None}
    current = clock.sim_start_real + timedelta(days=clock.sim_day)
    return {
        "sim_day":          clock.sim_day,
        "started":          True,
        "current_sim_date": current.strftime("%d. %b %Y"),
    }


@router.post("/skip-day")
def skip_day(session: Session = Depends(get_session)):
    now = datetime.now(timezone.utc)

    clock = session.get(SimulationClock, 1)
    if not clock:
        # Anchor 29 days in the past → full 30-day velocity window after 30 skips
        clock = SimulationClock(id=1, sim_day=0, sim_start_real=now - timedelta(days=29))
        session.add(clock)
        session.commit()
        session.refresh(clock)

    clock.sim_day += 1
    sim_ts = clock.sim_start_real + timedelta(
        days=clock.sim_day - 1,
        hours=random.randint(10, 22),
        minutes=random.randint(0, 59),
    )
    session.add(clock)

    products = session.exec(select(Product)).all()
    stocks   = {s.product_id: s for s in session.exec(select(Stock)).all()}

    all_events = session.exec(select(SaleEvent)).all()
    events_by_product: dict[int, list] = {}
    for e in all_events:
        events_by_product.setdefault(e.product_id, []).append(e)

    sales_log = []

    for product in products:
        stock = stocks.get(product.id)
        if not stock or stock.quantity <= 0:
            continue

        vel = _velocity(product.id, events_by_product.get(product.id, []))
        if vel is None:
            vel = max(0.1, stock.reorder_qty / 30)

        qty = round(vel * random.uniform(0.7, 1.3))
        qty = max(0, min(qty, stock.quantity))
        if qty == 0:
            continue

        session.add(SaleEvent(product_id=product.id, quantity=qty, sold_at=sim_ts))
        session.add(StockLog(product_id=product.id, change=-qty, reason="simulation",
                             note=f"Sim Tag {clock.sim_day}", logged_at=sim_ts))

        before         = stock.quantity
        stock.quantity -= qty
        session.add(stock)

        sales_log.append({
            "product":     product.name,
            "sold":        qty,
            "stock_after": stock.quantity,
            "low":         stock.quantity <= stock.reorder_point,
        })

    session.commit()

    # Auto-generate reorders for anything that dropped below threshold
    orders_triggered = 0
    new_order_ids = []
    for draft in run_rule_engine(session):
        existing = session.exec(
            select(Order).where(
                Order.product_id == draft["product_id"],
                Order.status     == OrderStatus.PENDING,
            )
        ).first()
        if existing:
            new_order_ids.append(existing.id)
        else:
            order = Order(product_id=draft["product_id"], quantity=draft["quantity"])
            session.add(order)
            session.commit()
            session.refresh(order)
            new_order_ids.append(order.id)
            orders_triggered += 1

    # Trigger auto-buy for all pending orders that need reordering
    for oid in new_order_ids:
        try_auto_fund_order(oid, session)

    return {
        "sim_day":          clock.sim_day,
        "sim_date":         sim_ts.strftime("%d. %b %Y"),
        "sales":            sales_log,
        "orders_triggered": orders_triggered,
    }


@router.post("/reset")
def reset_sim(session: Session = Depends(get_session)):
    """Wipe all sale events and reset the clock — back to day 0."""
    clock = session.get(SimulationClock, 1)
    if clock:
        session.delete(clock)
    for e in session.exec(select(SaleEvent)).all():
        session.delete(e)
    session.commit()
    return {"ok": True}
