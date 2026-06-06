from fastapi import FastAPI
from backend.db.database import create_db
from backend.routers.inventory import router as inventory_router  # ← added
from backend.routers.orders import router as orders_router        # ← escrow orders
from backend.routers.blockchain import router as blockchain_router  # ← chain diagnostics

app = FastAPI(
    title="Bar Inventory API",
    description="Automated inventory and reorder system powered by Algorand",
    version="0.1.0"
)

@app.on_event("startup")
def on_startup():
    create_db()

@app.get("/health")
def health():
    return {"status": "ok"}

app.include_router(inventory_router)  # ← added
app.include_router(orders_router)
app.include_router(blockchain_router)