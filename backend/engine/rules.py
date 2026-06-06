from sqlmodel import Session, select
from backend.models.product import Stock, Product, Supplier
from backend.engine.reorder import check_reorder_needed
import math

# A validated order draft — this is the output of the rule engine
# Not a database model, just a data shape we pass around
class OrderDraft:
    def __init__(self, product_id, product_name, quantity, supplier_id, supplier_name, supplier_wallet, total_price):
        self.product_id      = product_id
        self.product_name    = product_name
        self.quantity        = quantity
        self.supplier_id     = supplier_id
        self.supplier_name   = supplier_name
        self.supplier_wallet = supplier_wallet  # Algorand wallet — used later for payment
        self.total_price     = total_price

    def to_dict(self):
        return {
            "product_id":      self.product_id,
            "product_name":    self.product_name,
            "quantity":        self.quantity,
            "supplier_id":     self.supplier_id,
            "supplier_name":   self.supplier_name,
            "supplier_wallet": self.supplier_wallet,
            "total_price":     self.total_price,
        }


def run_rule_engine(session: Session) -> list[dict]:
    # Step 1 — get everything that needs reordering
    reorder_items = check_reorder_needed(session)

    if not reorder_items:
        return []

    orders = []

    for item in reorder_items:
        # Step 2 — fetch the stock row to get max_price and reorder_qty
        stock = session.exec(
            select(Stock).where(Stock.product_id == item["product_id"])
        ).first()

        # Step 3 — fetch the preferred supplier
        product = session.exec(
            select(Product).where(Product.id == item["product_id"])
        ).first()

        supplier = session.exec(
            select(Supplier).where(Supplier.id == product.preferred_supplier_id)
        ).first()

        print(f"DEBUG product: {product}")
        print(f"DEBUG supplier: {supplier}")
        if not supplier:
            # No supplier configured — skip this item
            continue

            # Step 4 — calculate total price (rounded up for safety)
        total_price = math.ceil(stock.reorder_qty * stock.max_price * 100) / 100

        # Step 6 — build the order draft
        draft = OrderDraft(
            product_id      = item["product_id"],
            product_name    = item["product_name"],
            quantity        = stock.reorder_qty,
            supplier_id     = supplier.id,
            supplier_name   = supplier.name,
            supplier_wallet = supplier.wallet_address,
            total_price     = total_price,
        )

        orders.append(draft.to_dict())

    return orders