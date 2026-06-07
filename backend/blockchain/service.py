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
    CommonAppCallCreateParams,
    CommonAppCallParams,
    PaymentParams,
    SigningAccount,
)
from algosdk.atomic_transaction_composer import TransactionWithSigner

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


def _ensure_buyer_funded(min_spending_microalgos: int = 10_000_000) -> None:
    """On LocalNet, top up the buyer from the dispenser when its spendable
    balance runs low.

    Every escrow app the buyer creates raises the buyer's own minimum-balance
    requirement (~0.1–0.2 ALGO per app), so a long-running simulation would
    eventually push the required minimum above the actual balance and all
    further escrow funding would fail. This keeps a spendable headroom.
    Only runs on LocalNet — testnet/mainnet must be funded manually.
    """
    if network_name() != "localnet":
        return
    try:
        algorand  = get_algorand()
        buyer     = get_buyer()
        dispenser = algorand.account.localnet_dispenser()
        algorand.account.ensure_funded(
            account_to_fund=buyer.address,
            dispenser_account=dispenser.address,
            min_spending_balance=AlgoAmount(micro_algo=min_spending_microalgos),
        )
    except Exception:
        # Best-effort: if this fails, the real funding txn below surfaces the error.
        pass


def create_and_fund_escrow(seller_address: str, amount_microalgos: int, order_hash: str) -> dict:
    """Phase 8 — deploy a fresh escrow for an order and fund it.

    Steps:
      1. create(seller, amount)         -> new app instance (note = order_hash bytes)
      2. top up the app's min balance   -> so it can hold funds + pay out
      3. fund(payment)                  -> buyer pays exactly `amount` into escrow

    The order_hash is embedded as the transaction note on the create call, anchoring
    this specific order to its escrow on-chain without changing the contract ABI.
    """
    algorand = get_algorand()
    buyer = get_buyer()

    # Keep the buyer solvent on LocalNet across long simulations.
    _ensure_buyer_funded()

    factory = _factory()

    note = bytes.fromhex(order_hash) if order_hash else None
    client, create_result = factory.send.create.create(
        CreateArgs(seller=seller_address, amount=amount_microalgos),
        params=CommonAppCallCreateParams(note=note),
    )

    # Cover the app account's minimum balance requirement.
    algorand.send.payment(
        PaymentParams(
            sender=buyer.address,
            receiver=client.app_address,
            amount=APP_MIN_BALANCE,
        )
    )

    # Group an exact-amount payment with the fund() call. The transaction arg
    # must be a built transaction with a signer, not raw params.
    pay_txn = algorand.create_transaction.payment(
        PaymentParams(
            sender=buyer.address,
            receiver=client.app_address,
            amount=AlgoAmount(micro_algo=amount_microalgos),
        )
    )
    fund_result = client.send.fund(
        FundArgs(payment=TransactionWithSigner(pay_txn, buyer.signer))
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
