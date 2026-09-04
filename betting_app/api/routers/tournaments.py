"""FastAPI router for tournament brackets and Monte Carlo simulations."""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from betting_app.services.tournament_service import (
    DEFAULT_WORLDS_2026_TEAMS,
    SUPPORTED_BRACKETS,
    TournamentSimulator,
    WorldsSimulator,
)

router = APIRouter(prefix="/tournaments", tags=["tournaments"])


class SimulateTournamentRequest(BaseModel):
    simulations: int = 10000
    manual_overrides: dict[str, str] | None = None  # match_id -> winner team name


class SimulateWorldsRequest(BaseModel):
    simulations: int = 5000
    teams: list[str] | None = None  # 16 teams

@router.get("")
def list_tournaments() -> list[dict[str, Any]]:
    """Return available tournaments supported for bracket simulation."""
    result = []
    for fn in SUPPORTED_BRACKETS.values():
        b = fn()
        result.append(
            {
                "id": b.id,
                "name": b.name,
                "region": b.region,
                "format": b.format,
                "teams": b.teams,
            }
        )
    return result

# ─── Worlds 2026 Simulation ───────────────────────────────────────

@router.get("/worlds/teams")
def get_default_worlds_teams() -> dict[str, Any]:
    """Return default 16 teams for Worlds 2026 simulation."""
    return {
        "tournament_id": "worlds_2026",
        "default_teams": DEFAULT_WORLDS_2026_TEAMS,
    }


@router.post("/worlds/simulate")
def simulate_worlds(body: SimulateWorldsRequest) -> dict[str, Any]:
    """Simulate full Worlds (Swiss Stage + Knockout Bo5) with custom or default 16 teams."""
    sim = WorldsSimulator()
    n_sims = min(max(body.simulations, 100), 20000)
    return sim.simulate_worlds(teams=body.teams, n_simulations=n_sims)


@router.get("/{tournament_id}")
def get_tournament_bracket(tournament_id: str) -> dict[str, Any]:
    """Return the current bracket state and default simulation results."""
    builder = SUPPORTED_BRACKETS.get(tournament_id)
    if not builder:
        raise HTTPException(status_code=404, detail=f"Tournament {tournament_id} not found")

    bracket = builder()
    simulator = TournamentSimulator()
    return simulator.simulate(bracket, n_simulations=5000)


@router.post("/{tournament_id}/simulate")
def simulate_tournament(tournament_id: str, body: SimulateTournamentRequest) -> dict[str, Any]:
    """Run Monte Carlo simulation with optional what-if manual match winners."""
    builder = SUPPORTED_BRACKETS.get(tournament_id)
    if not builder:
        raise HTTPException(status_code=404, detail=f"Tournament {tournament_id} not found")

    bracket = builder()
    simulator = TournamentSimulator()
    n_sims = min(max(body.simulations, 100), 50000)
    return simulator.simulate(bracket, n_simulations=n_sims, manual_overrides=body.manual_overrides)
