from fastapi import APIRouter, HTTPException

from backend.blockchain import service

router = APIRouter(prefix="/blockchain", tags=["Blockchain"])


@router.get("/status")
def status():
    """Connectivity check: which network, the buyer account, and its balance."""
    try:
        buyer = service.get_buyer()
        balance = service.buyer_balance_microalgos(buyer.address)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Cannot reach Algorand node: {e}")
    return {
        "network": service.network_name(),
        "buyer_address": buyer.address,
        "buyer_balance_microalgos": balance,
    }


@router.get("/escrow/{app_id}")
def escrow_state(app_id: int):
    """Read the on-chain state of a specific escrow app."""
    try:
        return service.get_escrow_state(app_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not read escrow {app_id}: {e}")
