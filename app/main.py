from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import engine
from app.models import procurement, vendor, audit, catalog
from app.api import procurement as procurement_router
from app.api import webhooks as webhooks_router
from app.api import websocket as websocket_router
from app.api import catalog as catalog_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Tables are managed externally in procbay_schema — do not create_all here
    yield
    await engine.dispose()


app = FastAPI(
    title="ProcBay Agentic Orchestrator",
    version="1.0.0",
    description="Centralized State Machine Orchestrator for Automated Procurement",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(procurement_router.router, prefix="/api/v1/procurement", tags=["procurement"])
app.include_router(webhooks_router.router, prefix="/api/v1/webhooks", tags=["webhooks"])
app.include_router(websocket_router.router, prefix="/ws", tags=["websocket"])
app.include_router(catalog_router.router, prefix="/api/v1/catalog", tags=["catalog"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "procbay-orchestrator", "version": "1.0.0"}


@app.get("/")
async def root():
    return {
        "service": "ProcBay Agentic Orchestrator",
        "docs": "/docs",
        "health": "/health",
    }
