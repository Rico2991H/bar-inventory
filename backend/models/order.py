from sqlmodel import SQLModel, Field
from typing import Optional


class Order(SQLModel, table=True):
    """A purchase order backed by an on-chain escrow.

    Status lifecycle: funded -> delivered -> released
    (the order is only persisted once its escrow has been created and funded).
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="product.id")
    supplier_id: int = Field(foreign_key="supplier.id")
    quantity: int
    amount: int  # microalgos held in escrow for this order
    status: str = Field(default="funded")

    # On-chain escrow references
    app_id: Optional[int] = Field(default=None)
    app_address: Optional[str] = Field(default=None)

    # Transaction ids for auditability
    create_tx: Optional[str] = Field(default=None)
    fund_tx: Optional[str] = Field(default=None)
    delivery_tx: Optional[str] = Field(default=None)
    release_tx: Optional[str] = Field(default=None)


class OrderCreate(SQLModel):
    """Request body for creating an order (server fills in the on-chain fields)."""
    product_id: int
    supplier_id: int
    quantity: int
    amount: int  # microalgos to place in escrow
