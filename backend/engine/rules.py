from sqlmodel import Session, select
from backend.models.product import Stock, Product
from backend.engine.reorder import check_reorder_needed


def run_rule_engine(session: Session) -> list[dict]:
    """Detect low-stock products and return order drafts.

    Supplier selection and pricing happen at fund time (manual UI choice),
    so drafts only carry product identity and quantity.
    """
    reorder_items = check_reorder_needed(session)
    if not reorder_items:
        return []

    drafts = []
    for item in reorder_items:
        stock = session.exec(
            select(Stock).where(Stock.product_id == item["product_id"])
        ).first()
        if not stock:
            continue

        drafts.append({
            "product_id":   item["product_id"],
            "product_name": item["product_name"],
            "quantity":     stock.reorder_qty,
        })

    return drafts
