"""Thin service layer between the FastAPI backend and the Algorand escrow contract.

The bar (the "buyer") is represented by a single backend-controlled account.
Each purchase order gets its own Escrow app instance:

    create_and_fund_escrow()  -> deploy a new escrow + fund it     (phase 8)
    confirm_delivery()        -> mark the order delivered          (phase 9)
    release()                 -> pay the supplier from escrow      (phase 10)

Network selection is driven by the ALGORAND_NETWORK env var
("localnet" by default; "testnet"/"mainnet" supported for later).
The typed client (escrow_client.py) is vendored from
projects/bar-inventory/smart_contracts/artifacts/escrow/ — regenerate it with
`algokit project run build` in that project if the contract changes.
"""

import os
from functools import lru_cache

from algokit_utils import (
    AlgoAmount,
    AlgorandClient,
    CommonAppCallParams,
    PaymentParams,
    SigningAccount,
)

from backend.blockchain.escrow_client import (
    CreateArgs,
    EscrowClient,
    EscrowFactory,
    FundArgs,
)

# Min balance top-up so the app account can exist and pay out via an inner txn.
# Base app account MBR is 0.1 ALGO; we add a little headroom.
APP_MIN_BALANCE = AlgoAmount(micro_algo=200_000)

# Extra fee on release() to cover the contract's fee=0 inner payment (fee pooling).
RELEASE_EXTRA_FEE = AlgoAmount(micro_algo=1_000)


def network_name() -> str:
    return os.getenv("ALGORAND_NETWORK", "localnet").lower()


@lru_cache(maxsize=1)
def get_algorand() -> AlgorandClient:
    """AlgorandClient for the configured network (defaults to LocalNet)."""
    network = network_name()
    if network == "testnet":
        return AlgorandClient.testnet()
    if network == "mainnet":
        return AlgorandClient.mainnet()
    return AlgorandClient.default_localnet()


@lru_cache(maxsize=1)
def get_buyer() -> SigningAccount:
    """The bar's account.

    On LocalNet this auto-creates the account and funds it from the dispenser.
    On testnet/mainnet, set BUYER_MNEMONIC in the environment.
    """
    algorand = get_algorand()
    return algorand.account.from_environment("BUYER", AlgoAmount(algo=100))


def _factory() -> EscrowFactory:
    buyer = get_buyer()
    return EscrowFactory(
        get_algorand(),
        default_sender=buyer.address,
        default_signer=buyer.signer,
    )


def _client(app_id: int) -> EscrowClient:
    buyer = get_buyer()
    return EscrowClient(
        algorand=get_algorand(),
        app_id=app_id,
        default_sender=buyer.address,
        default_signer=buyer.signer,
    )


def create_and_fund_escrow(seller_address: str, amount_microalgos: int) -> dict:
    """Phase 8 — deploy a fresh escrow for an order and fund it.

    Steps:
      1. create(seller, amount)         -> new app instance
      2. top up the app's min balance   -> so it can hold funds + pay out
      3. fund(payment)                  -> buyer pays exactly `amount` into escrow
    """
    algorand = get_algorand()
    buyer = get_buyer()
    factory = _factory()

    client, create_result = factory.send.create(
        CreateArgs(seller=seller_address, amount=amount_microalgos),
    )

    # Cover the app account's minimum balance requirement.
    algorand.send.payment(
        PaymentParams(
            sender=buyer.address,
            receiver=client.app_address,
            amount=APP_MIN_BALANCE,
        )
    )

    # Group an exact-amount payment with the fund() call.
    fund_result = client.send.fund(
        FundArgs(
            payment=PaymentParams(
                sender=buyer.address,
                receiver=client.app_address,
                amount=AlgoAmount(micro_algo=amount_microalgos),
            )
        )
    )

    return {
        "app_id": client.app_id,
        "app_address": client.app_address,
        "create_tx": create_result.tx_ids[0] if create_result.tx_ids else None,
        "fund_tx": fund_result.tx_ids[0] if fund_result.tx_ids else None,
    }


def confirm_delivery(app_id: int) -> dict:
    """Phase 9 — buyer confirms the goods arrived, unlocking release."""
    result = _client(app_id).send.confirm_delivery()
    return {"tx": result.tx_ids[0] if result.tx_ids else None}


def release(app_id: int) -> dict:
    """Phase 10 — release the escrowed funds to the supplier.

    The contract's inner payment uses fee=0, so the outer call must carry an
    extra fee to cover it (fee pooling).
    """
    result = _client(app_id).send.release(
        params=CommonAppCallParams(extra_fee=RELEASE_EXTRA_FEE),
    )
    return {"tx": result.tx_ids[0] if result.tx_ids else None}


def get_escrow_state(app_id: int) -> dict:
    """Read the on-chain state of an escrow app."""
    gs = _client(app_id).state.global_state.get_all()
    return {
        "buyer": gs.get("buyer"),
        "seller": gs.get("seller"),
        "amount": gs.get("amount"),
        "funded": bool(gs.get("funded")),
        "delivered": bool(gs.get("delivered")),
        "released": bool(gs.get("released")),
    }


def buyer_balance_microalgos(address: str) -> int:
    """Current balance (microalgos) via the algod client — robust to SDK shape."""
    return int(get_algorand().client.algod.account_info(address)["amount"])
