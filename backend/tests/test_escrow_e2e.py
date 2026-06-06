"""End-to-end test for the escrow order flow (phases 8-10).

Drives the real FastAPI endpoints in-process against a running AlgoKit
LocalNet. It deploys a real escrow per order, funds it, confirms delivery,
releases payment, and asserts the supplier's on-chain balance actually grew.

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


def _make_supplier_and_product(client) -> tuple[int, int, str]:
    """Create a supplier with a fresh Algorand wallet + a product. Returns ids + wallet."""
    supplier_wallet = service.get_algorand().account.random().address
    r = client.post(
        "/inventory/suppliers",
        json={
            "name": "Test Distillery",
            "contact_email": "orders@test-distillery.example",
            "wallet_address": supplier_wallet,
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
    return supplier_id, product_id, supplier_wallet


def test_full_escrow_flow_pays_supplier(client):
    """create order -> fund -> confirm delivery -> release, and supplier gets paid."""
    supplier_id, product_id, supplier_wallet = _make_supplier_and_product(client)
    amount = 5_000_000  # 5 ALGO in microalgos
    start_balance = _balance(supplier_wallet)

    # --- Phase 8: create order deploys + funds an escrow ---
    r = client.post(
        "/orders",
        json={
            "product_id": product_id,
            "supplier_id": supplier_id,
            "quantity": 10,
            "amount": amount,
        },
    )
    assert r.status_code == 200, r.text
    order = r.json()
    order_id = order["id"]
    app_id = order["app_id"]
    assert order["status"] == "funded"
    assert app_id and order["app_address"]
    assert order["create_tx"] and order["fund_tx"]

    state = client.get(f"/blockchain/escrow/{app_id}").json()
    assert state["amount"] == amount
    assert state["funded"] is True
    assert state["delivered"] is False
    assert state["released"] is False
    assert state["seller"] == supplier_wallet

    # --- Phase 9: confirm delivery ---
    r = client.post(f"/orders/{order_id}/confirm-delivery")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "delivered"
    assert client.get(f"/blockchain/escrow/{app_id}").json()["delivered"] is True

    # --- Phase 10: release payment to supplier ---
    r = client.post(f"/orders/{order_id}/release")
    assert r.status_code == 200, r.text
    released = r.json()
    assert released["status"] == "released"
    assert released["release_tx"]
    assert client.get(f"/blockchain/escrow/{app_id}").json()["released"] is True

    # The supplier's on-chain balance grew by exactly the escrow amount.
    assert _balance(supplier_wallet) - start_balance == amount


def test_cannot_release_before_delivery(client):
    """Release is rejected until delivery is confirmed."""
    supplier_id, product_id, _ = _make_supplier_and_product(client)
    r = client.post(
        "/orders",
        json={
            "product_id": product_id,
            "supplier_id": supplier_id,
            "quantity": 1,
            "amount": 1_000_000,
        },
    )
    assert r.status_code == 200, r.text
    order_id = r.json()["id"]

    r = client.post(f"/orders/{order_id}/release")
    assert r.status_code == 400
    assert "deliver" in r.json()["detail"].lower()


def test_order_requires_supplier_wallet(client):
    """An order for a supplier with no wallet address is rejected before any chain call."""
    r = client.post(
        "/inventory/suppliers",
        json={"name": "No Wallet Co", "contact_email": "a@b.example", "wallet_address": ""},
    )
    assert r.status_code == 200, r.text
    supplier_id = r.json()["id"]
    r = client.post(
        "/inventory/products",
        json={"name": "Tonic", "unit": "case", "preferred_supplier_id": supplier_id},
    )
    product_id = r.json()["id"]

    r = client.post(
        "/orders",
        json={
            "product_id": product_id,
            "supplier_id": supplier_id,
            "quantity": 1,
            "amount": 1_000_000,
        },
    )
    assert r.status_code == 400
    assert "wallet" in r.json()["detail"].lower()
