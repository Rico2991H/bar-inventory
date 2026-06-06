"""End-to-end test for the integrated reorder + escrow flow (phases 1-10).

Drives the real FastAPI endpoints in-process against a running AlgoKit
LocalNet, exercising the whole pipeline:

    seed low stock -> POST /orders/generate (rule engine -> PENDING)
                   -> POST /orders/{id}/fund            (deploy + fund escrow)
                   -> POST /orders/{id}/confirm-delivery (DELIVERED)
                   -> POST /orders/{id}/release          (pay supplier)

and asserts the supplier's on-chain balance actually grew by the order total.

Requirements:
  * AlgoKit LocalNet running (`algokit localnet start`)
The test auto-skips if LocalNet is not reachable, so CI without a node stays green.

Run:
  source .venv/bin/activate
  pytest backend/tests/test_escrow_e2e.py -v
"""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from backend.main import app
from backend.db.database import get_session
from backend.models.product import OrderStatus
from backend.blockchain import service


def _localnet_available() -> bool:
    """True if we can reach LocalNet and obtain a funded buyer account."""
    try:
        buyer = service.get_buyer()
        service.buyer_balance_microalgos(buyer.address)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _localnet_available(),
    reason="AlgoKit LocalNet not reachable (run `algokit localnet start`)",
)


@pytest.fixture(name="client")
def client_fixture():
    """FastAPI client backed by an isolated in-memory DB (no inventory.db writes)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    def get_session_override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = get_session_override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _balance(address: str) -> int:
    return int(service.get_algorand().client.algod.account_info(address)["amount"])


def _seed_low_stock(client, *, wallet: str, reorder_qty: int = 10, max_price: float = 0.5):
    """Create a supplier (with wallet), product, and a stock row below its reorder point.

    Returns (supplier_id, product_id). Expected order total = reorder_qty * max_price ALGO.
    """
    r = client.post(
        "/inventory/suppliers",
        json={
            "name": "Test Distillery",
            "contact_email": "orders@test-distillery.example",
            "wallet_address": wallet,
        },
    )
    assert r.status_code == 200, r.text
    supplier_id = r.json()["id"]

    r = client.post(
        "/inventory/products",
        json={"name": "Gin", "unit": "bottle", "preferred_supplier_id": supplier_id},
    )
    assert r.status_code == 200, r.text
    product_id = r.json()["id"]

    r = client.post(
        "/inventory/stock",
        json={
            "product_id": product_id,
            "quantity": 2,            # below reorder_point -> triggers reorder
            "reorder_point": 5,
            "reorder_qty": reorder_qty,
            "max_price": max_price,
        },
    )
    assert r.status_code == 200, r.text
    return supplier_id, product_id


def _generate_one_order(client) -> dict:
    r = client.post("/orders/generate")
    assert r.status_code == 200, r.text
    orders = r.json()["orders"]
    assert len(orders) == 1, orders
    return orders[0]


def test_full_reorder_and_escrow_flow_pays_supplier(client):
    """generate -> fund -> confirm delivery -> release, and supplier gets paid."""
    supplier_wallet = service.get_algorand().account.random().address
    _seed_low_stock(client, wallet=supplier_wallet, reorder_qty=10, max_price=0.5)
    expected_micro = 5_000_000  # 10 * 0.5 ALGO
    start_balance = _balance(supplier_wallet)

    # --- Phases 1-5: rule engine produces a PENDING order ---
    order = _generate_one_order(client)
    order_id = order["id"]
    assert order["status"] == OrderStatus.PENDING.value
    assert order["total_price"] == 5.0
    assert order["order_hash"]

    # --- Phase 8: fund deploys + funds the escrow ---
    r = client.post(f"/orders/{order_id}/fund")
    assert r.status_code == 200, r.text
    funded = r.json()
    assert funded["status"] == OrderStatus.FUNDED.value
    app_id = funded["app_id"]
    assert app_id and funded["escrow_address"] and funded["txn_id"]

    state = client.get(f"/blockchain/escrow/{app_id}").json()
    assert state["amount"] == expected_micro
    assert state["funded"] is True
    assert state["delivered"] is False
    assert state["seller"] == supplier_wallet

    # --- Phase 9: confirm delivery ---
    r = client.post(f"/orders/{order_id}/confirm-delivery")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == OrderStatus.DELIVERED.value
    assert client.get(f"/blockchain/escrow/{app_id}").json()["delivered"] is True

    # --- Phase 10: release payment to supplier ---
    r = client.post(f"/orders/{order_id}/release")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == OrderStatus.RELEASED.value
    assert client.get(f"/blockchain/escrow/{app_id}").json()["released"] is True

    # The supplier's on-chain balance grew by exactly the order total.
    assert _balance(supplier_wallet) - start_balance == expected_micro


def test_cannot_release_before_delivery(client):
    """Release is rejected on a funded order until delivery is confirmed."""
    supplier_wallet = service.get_algorand().account.random().address
    _seed_low_stock(client, wallet=supplier_wallet)
    order_id = _generate_one_order(client)["id"]

    r = client.post(f"/orders/{order_id}/fund")
    assert r.status_code == 200, r.text

    r = client.post(f"/orders/{order_id}/release")
    assert r.status_code == 400
    assert "deliver" in r.json()["detail"].lower()


def test_fund_requires_supplier_wallet(client):
    """Funding an order whose supplier has no wallet is rejected before any chain call."""
    _seed_low_stock(client, wallet="")  # supplier with no payout wallet
    order_id = _generate_one_order(client)["id"]

    r = client.post(f"/orders/{order_id}/fund")
    assert r.status_code == 400
    assert "wallet" in r.json()["detail"].lower()
