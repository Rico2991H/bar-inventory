from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from backend.blockchain import service
from backend.db.database import get_session
from backend.models.product import Order

router = APIRouter(prefix="/blockchain", tags=["Blockchain"])


@router.get("/status")
def status():
    """Connectivity check: which network, the buyer account, its balance, and current round."""
    try:
        buyer   = service.get_buyer()
        balance = service.buyer_balance_microalgos(buyer.address)
        node_status = service.get_algorand().client.algod.status()
        last_round  = node_status.get("last-round")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Cannot reach Algorand node: {e}")
    return {
        "network":                 service.network_name(),
        "buyer_address":           buyer.address,
        "buyer_balance_microalgos": balance,
        "balance_algo":            round(balance / 1_000_000, 4),
        "last_round":              last_round,
    }


@router.get("/escrow/{app_id}")
def escrow_state(app_id: int, session: Session = Depends(get_session)):
    """Read the on-chain state of a specific escrow app.

    Also returns the order_hash and create_txn_id so callers can verify that
    the hash written as a note on the create transaction matches the DB record.
    """
    try:
        chain = service.get_escrow_state(app_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not read escrow {app_id}: {e}")

    order = session.exec(select(Order).where(Order.app_id == app_id)).first()
    return {
        **chain,
        "order_hash": order.order_hash if order else None,
        "create_txn_id": order.create_txn_id if order else None,
    }
