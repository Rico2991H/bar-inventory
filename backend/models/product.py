from sqlmodel import SQLModel, Field
from typing import Optional
from enum import Enum
from datetime import datetime

class Supplier(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    contact_email: str
    wallet_address: str

class Product(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    unit: str
    preferred_supplier_id: Optional[int] = Field(default=None, foreign_key="supplier.id")
    lead_time_days: int = Field(default=2)  # delivery lead time in (simulation) days

class Stock(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="product.id")
    quantity: int
    reorder_point: int
    reorder_qty: int
    max_price: float  # upper price limit used as fallback when no catalog entry exists

class SupplierProduct(SQLModel, table=True):
    """Catalog entry: a specific product offered by a supplier at a given unit price."""
    id:            Optional[int]   = Field(default=None, primary_key=True)
    supplier_id:   int             = Field(foreign_key="supplier.id")
    product_id:    int             = Field(foreign_key="product.id")
    unit_price:    float           # price per unit in ALGO
    min_order_qty: int             = Field(default=1)

class Budget(SQLModel, table=True):
    """Single-row table holding the bar's total procurement budget (in ALGO)."""
    id:           int   = Field(default=1, primary_key=True)
    total_budget: float = Field(default=0.0)

class SaleEvent(SQLModel, table=True):
    """Log of every stock sale — used to calculate consumption velocity."""
    id:         Optional[int] = Field(default=None, primary_key=True)
    product_id: int           = Field(foreign_key="product.id")
    quantity:   int
    sold_at:    datetime      = Field(default_factory=datetime.utcnow)


class StockLog(SQLModel, table=True):
    """Human-readable log of all stock ins and outs, shown in the Inventory tab."""
    id:         Optional[int]   = Field(default=None, primary_key=True)
    product_id: int             = Field(foreign_key="product.id")
    change:     int             # positive = in (restock), negative = out (sale)
    reason:     str             # "sale" | "restock" | "simulation"
    note:       Optional[str]   = None
    logged_at:  datetime        = Field(default_factory=datetime.utcnow)


class AutoBuyConfig(SQLModel, table=True):
    """Per-product auto-buy settings (one row per product, created on first save)."""
    id:             Optional[int]   = Field(default=None, primary_key=True)
    product_id:     int             = Field(foreign_key="product.id")
    enabled:        bool            = Field(default=False)
    mode:           str             = Field(default="fixed")  # "fixed" | "ai"
    supplier_id:    Optional[int]   = Field(default=None, foreign_key="supplier.id")
    last_ai_choice: Optional[str]   = None  # JSON: {supplier_id, name, reasoning, at}


class SimulationClock(SQLModel, table=True):
    """Tracks the current position of the time simulation (single row, id=1)."""
    id:             int               = Field(default=1, primary_key=True)
    sim_day:        int               = Field(default=0)
    sim_start_real: Optional[datetime] = None  # real timestamp when simulation started


class OrderStatus(str, Enum):
    PENDING   = "pending"
    FUNDED    = "funded"
    DELIVERED = "delivered"
    RELEASED  = "released"
    CANCELLED = "cancelled"

class Order(SQLModel, table=True):
    id:             Optional[int]   = Field(default=None, primary_key=True)
    product_id:     int             = Field(foreign_key="product.id")
    supplier_id:    Optional[int]   = Field(default=None, foreign_key="supplier.id")
    quantity:       int
    unit_price:     Optional[float] = None  # set at fund time from catalog
    total_price:    Optional[float] = None  # unit_price * quantity, set at fund time
    status:         OrderStatus     = Field(default=OrderStatus.PENDING)
    order_hash:     Optional[str]   = None
    escrow_address: Optional[str]   = None
    app_id:         Optional[int]   = None
    create_txn_id:  Optional[str]   = None
    txn_id:         Optional[str]   = None
    rating:         Optional[int]   = None  # 1–5, set after release
    rating_note:    Optional[str]   = None
    deliver_on_day: Optional[int]   = None  # sim day the goods arrive (set at fund time)