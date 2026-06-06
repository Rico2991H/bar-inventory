# Next Steps & Roadmap

Status as of the latest merge to `main`: the **phases 1–10 vertical slice** works
end to end.

## Where we are now

Sell → rule engine detects low stock → generates a `PENDING` order (hashed) →
funds an on-chain escrow → confirm delivery → release payment to the supplier.

- Algorand `Escrow` ARC4 contract (`create` / `fund` / `confirm_delivery` / `release`)
- FastAPI backend: `inventory`, `orders`, and `blockchain` routers
- Rule engine + reorder detection over a SQLite store
- A real LocalNet end-to-end test that asserts the supplier's balance actually grows

## Logical next steps (priority order)

### 1. Close the inventory loop  *(biggest gap)*
`sell` decrements stock, but nothing ever increments it back. An order goes
`PENDING → FUNDED → DELIVERED → RELEASED`, yet `Stock.quantity` is never raised by
`order.quantity`. So after one cycle the product stays below its reorder point and
keeps re-triggering. **Fix:** on confirm-delivery (goods physically arrived), add
`order.quantity` back to stock. This is the single most important change to make the
system behave coherently.

### 2. Put the `order_hash` on-chain  *(the unfinished tamper-proof phase)*
We compute `order_hash` and comment "stored on Algorand later" — but the contract
never receives or stores it, so today the hash does nothing. Pass it into `create()`,
store it in global state, and expose it via `/blockchain/escrow/{app_id}` for
verification. This is the "why blockchain" story.

### 3. Add a cancel / refund / timeout path
`OrderStatus.CANCELLED` exists but has no endpoint, and the contract has **no way to
return funds**. If a supplier never delivers, the ALGO is locked in the app account
forever. Add a buyer-only `refund()` method (only if not released, ideally after a
timeout round) plus `POST /orders/{id}/cancel`.

### 4. Fix two concrete bugs
- `routers/inventory.py` → `sell_product` returns `"stock": stock.model_dump` — the
  method object, not a call. Should be `stock.model_dump()`.
- Same file duplicate-imports `Product, Supplier, Stock`. The auto-reorder logic in
  `sell` is also copy-pasted from `orders.generate` — extract to one shared function.

### 5. Frontend / dashboard
`src/` is empty; the system is API-only. A bar/club/café operator needs a UI: stock
levels, pending reorders, fund/confirm/release buttons, and order status.

### 6. Hardening beyond LocalNet
- **State-drift risk:** in `fund`/`release` the chain call and the DB commit are
  separate — a failed commit diverges on-chain and off-chain state. Add a
  reconcile/recovery path.
- **TestNet deploy** — `service.py` already supports it via `ALGORAND_NETWORK`.
- **Alembic migrations** (currently `create_all`), **auth / multi-venue** (single
  hardcoded buyer account today), and structured logging.

## Suggested order for a demo
**#1 + #4 first** (makes the loop actually work), then **#2** (the blockchain payoff),
then **#5** (something to show), with **#3** if time allows.
