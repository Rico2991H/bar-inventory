from fastapi import FastAPI
from backend.db.database import create_db

# This creates the FastAPI app instance
# title and description show up in the auto-generated docs
app = FastAPI(
    title="Bar Inventory API",
    description="Automated inventory and reorder system powered by Algorand",
    version="0.1.0"
)

# When the app starts, create all database tables
# This runs once on startup — safe to call multiple times, it won't recreate existing tables
@app.on_event("startup")
def on_startup():
    create_db()

# Basic health check endpoint
# Good habit — lets you verify the server is running
@app.get("/health")
def health():
    return {"status": "ok"}

from backend.routers.inventory import router as inventory_router

app.include_router(inventory_router)