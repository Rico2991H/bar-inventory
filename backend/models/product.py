from sqlmodel import SQLModel, Field
from typing import Optional

class Supplier(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    contact_email: str
    wallet_address: str  # Algorand wallet — needed later for payment release

class Product(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    unit: str  # e.g. "bottle", "case"
    preferred_supplier_id: Optional[int] = Field(default=None, foreign_key="supplier.id")

class Stock(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="product.id")
    quantity: int
    reorder_point: int   # trigger reorder below this
    reorder_qty: int     # how many to order
    max_price: float     # rule engine uses this later