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
from backend.blockchain import service
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

    # --- Process deliveries that are due (lead time elapsed) ---
    # Funded escrows whose delivery day has arrived: confirm + release on-chain
    # (pay the supplier) and restock. Sim stays resilient if the chain call fails.
    arrivals = []
    due = session.exec(
        select(Order).where(
            Order.status == OrderStatus.FUNDED,
            Order.deliver_on_day.is_not(None),
            Order.deliver_on_day <= clock.sim_day,
        )
    ).all()
    for o in due:
        if o.app_id is not None:
            try:
                service.confirm_delivery(o.app_id)
                service.release(o.app_id)
            except Exception:
                pass  # keep simulating even if LocalNet hiccups
        o.status = OrderStatus.RELEASED
        session.add(o)
        stock = stocks.get(o.product_id)
        if stock:
            stock.quantity += o.quantity
            session.add(stock)
            session.add(StockLog(
                product_id=o.product_id, change=o.quantity, reason="restock",
                note=f"Lieferung Order #{o.id} (Sim Tag {clock.sim_day})", logged_at=sim_ts,
            ))
        arrivals.append({"order_id": o.id, "product_id": o.product_id, "qty": o.quantity})
    if due:
        session.commit()

    all_events = session.exec(select(SaleEvent)).all()
    events_by_product: dict[int, list] = {}
    for e in all_events:
        events_by_product.setdefault(e.product_id, []).append(e)

    sales_log = []

    for product in products:
        stock = stocks.get(product.id)
        if not stock or stock.quantity <= 0:
            continue

        # Baseline daily demand so the simulation keeps producing sales even
        # with little/no history (e.g. right after a reset). Busier products,
        # whose measured velocity exceeds the baseline, override it.
        baseline = max(0.5, stock.reorder_qty / 14)
        vel = _velocity(product.id, events_by_product.get(product.id, [])) or 0
        vel = max(vel, baseline)

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

    # Auto-generate reorders for anything that dropped below threshold.
    # Skip products that already have an ACTIVE order (pending or in-transit/funded)
    # so we don't double-order goods that are already on the way.
    orders_triggered = 0
    new_order_ids = []
    for draft in run_rule_engine(session):
        active = session.exec(
            select(Order).where(
                Order.product_id == draft["product_id"],
                Order.status.in_([OrderStatus.PENDING, OrderStatus.FUNDED]),
            )
        ).first()
        if active:
            # Retry funding if it's still an unfunded draft; leave in-transit ones alone.
            if active.status == OrderStatus.PENDING:
                new_order_ids.append(active.id)
            continue
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
        "deliveries":       len(arrivals),
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
