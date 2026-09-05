"""EnsembleLegends Betting API — FastAPI application."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from betting_app.api.routers import matches, predictions, bets
from betting_app.api.routers.embeddings import router as embeddings_router
from betting_app.api.routers.system import router as system_router
from betting_app.api.routers.scheduler import router as scheduler_router
from betting_app.api.routers.timing import router as timing_router
from betting_app.api.routers.bootstrap import router as bootstrap_router
from betting_app.api.routers.financial import router as financial_router
from betting_app.api.routers.rankings import router as rankings_router
from betting_app.api.routers.tournaments import router as tournaments_router
from betting_app.api.routers.players import router as players_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema is managed via Alembic or init_db() in CLI scripts
    yield


app = FastAPI(
    title="EnsembleLegends Betting API",
    description="LoL betting research manager backend.",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system_router)
app.include_router(scheduler_router)
app.include_router(matches.router)
app.include_router(predictions.router)
app.include_router(bets.router)
app.include_router(timing_router)
app.include_router(bootstrap_router)
app.include_router(financial_router)
app.include_router(embeddings_router)
app.include_router(rankings_router)
app.include_router(tournaments_router)
app.include_router(players_router)
