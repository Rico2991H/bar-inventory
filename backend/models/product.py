from sqlmodel import SQLModel, Field
from typing import Optional
from enum import Enum

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

class OrderStatus(str, Enum):
    PENDING   = "pending"    # order draft created
    FUNDED    = "funded"     # escrow funded on Algorand
    DELIVERED = "delivered"  # supplier confirmed delivery
    RELEASED  = "released"   # payment released to supplier
    CANCELLED = "cancelled"  # something went wrong

class Order(SQLModel, table=True):
    id:               Optional[int] = Field(default=None, primary_key=True)
    product_id:       int           = Field(foreign_key="product.id")
    supplier_id:      int           = Field(foreign_key="supplier.id")
    quantity:         int
    total_price:      float
    status:           OrderStatus   = Field(default=OrderStatus.PENDING)
    order_hash:       Optional[str] = None  # hash of order JSON — stored on Algorand later
    escrow_address:   Optional[str] = None  # Algorand contract address — filled after deployment
    txn_id:           Optional[str] = None  # Algorand transaction ID — filled after funding