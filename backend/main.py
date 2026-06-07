from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.db.database import create_db
from backend.routers.inventory import router as inventory_router
from backend.routers.orders import router as orders_router
from backend.routers.blockchain import router as blockchain_router
from backend.routers.analytics import router as analytics_router
from backend.routers.webhooks import router as webhooks_router
from backend.routers.simulation import router as simulation_router

app = FastAPI(
    title="Bar Inventory API",
    description="Automated inventory and reorder system powered by Algorand",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def on_startup():
    create_db()

@app.get("/health")
def health():
    return {"status": "ok"}

app.include_router(inventory_router)
app.include_router(orders_router)
app.include_router(blockchain_router)
app.include_router(analytics_router)
app.include_router(webhooks_router)
app.include_router(simulation_router)
