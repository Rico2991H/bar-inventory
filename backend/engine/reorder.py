from sqlmodel import Session, select
from backend.models.product import Stock, Product, Supplier

# This is the core detection function
# It checks all stock rows and returns a list of items that need reordering
def check_reorder_needed(session: Session) -> list[dict]:
    reorder_list = []

    # Fetch all stock rows from the database
    stocks = session.exec(select(Stock)).all()

    for stock in stocks:
        # Core logic from your spec: if quantity drops at or below reorder_point → trigger
        if stock.quantity <= stock.reorder_point:

            # Fetch the related product so we can include its name
            product = session.exec(select(Product).where(Product.id == stock.product_id)).first()

            # Fetch the preferred supplier for context
            supplier = session.exec(select(Supplier).where(Supplier.id == product.preferred_supplier_id)).first()

            reorder_list.append({
                "product_id": stock.product_id,
                "product_name": product.name,
                "current_stock": stock.quantity,
                "reorder_point": stock.reorder_point,
                "reorder_qty": stock.reorder_qty,
                "max_price": stock.max_price,
                "preferred_supplier": supplier.name if supplier else None,
                "supplier_wallet": supplier.wallet_address if supplier else None,
            })

    return reorder_list