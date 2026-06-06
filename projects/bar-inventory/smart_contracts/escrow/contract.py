from algopy import (
    Account,
    ARC4Contract,
    Global,
    Txn,
    UInt64,
    gtxn,
    itxn,
)
from algopy.arc4 import abimethod


class Escrow(ARC4Contract):
    """Per-order escrow for the bar-inventory reorder flow.

    Lifecycle (one app instance per purchase order):
      1. create(seller, amount)  -> bar (buyer) deploys the escrow for an order
      2. fund(payment)           -> bar pays `amount` ALGO into the app account
      3. confirm_delivery()      -> bar confirms goods arrived
      4. release()               -> app pays out the held funds to the seller

    The buyer is whoever creates the app (the backend acts on the bar's behalf).
    Funds physically sit in the application account between fund() and release().
    """

    def __init__(self) -> None:
        # Global state — initialised to safe defaults; create() sets the real values.
        self.buyer = Account()
        self.seller = Account()
        self.amount = UInt64(0)
        self.funded = False
        self.delivered = False
        self.released = False

    @abimethod(create="require")
    def create(self, seller: Account, amount: UInt64) -> None:
        """Initialise the escrow for a single order."""
        assert amount > 0, "amount must be positive"
        self.buyer = Txn.sender
        self.seller = seller
        self.amount = amount

    @abimethod
    def fund(self, payment: gtxn.PaymentTransaction) -> None:
        """Accept the buyer's payment into the escrow.

        `payment` is a payment transaction grouped atomically with this call.
        """
        assert not self.funded, "already funded"
        assert payment.sender == self.buyer, "only the buyer may fund"
        assert (
            payment.receiver == Global.current_application_address
        ), "payment must go to the escrow"
        assert payment.amount == self.amount, "payment must equal the order amount"
        self.funded = True

    @abimethod
    def confirm_delivery(self) -> None:
        """Buyer confirms the goods were delivered, unlocking release."""
        assert Txn.sender == self.buyer, "only the buyer may confirm delivery"
        assert self.funded, "escrow is not funded"
        assert not self.released, "already released"
        self.delivered = True

    @abimethod
    def release(self) -> None:
        """Release the escrowed funds to the seller once delivery is confirmed."""
        assert self.funded, "escrow is not funded"
        assert self.delivered, "delivery not confirmed"
        assert not self.released, "already released"
        # fee=0 -> fee is covered by the outer transaction (fee pooling).
        itxn.Payment(
            receiver=self.seller,
            amount=self.amount,
            fee=0,
        ).submit()
        self.released = True
