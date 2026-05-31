"""EnsembleLegends Betting API — FastAPI application.

Run with::

    uvicorn betting_app.api.main:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from betting_app.core.database import init_db
from betting_app.api.routers import matches, predictions, bets
from betting_app.api.routers.system import router as system_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="EnsembleLegends Betting API",
    description="Backend for the LoL betting research manager. "
    "Provides upcoming matches with aggregated odds, model predictions, "
    "EV/Kelly analysis, wallet management, and automation triggers.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Mount routers ───────────────────────────────────────────────────────────
app.include_router(system_router)             # /health, /system/status, /bookmakers, /automation/*
app.include_router(matches.router)            # /matches, /matches/{id}, /matches/{id}/odds-history
app.include_router(predictions.router)        # /predictions
app.include_router(bets.router)               # /wallets, /bets, /bets/{id}/settle
