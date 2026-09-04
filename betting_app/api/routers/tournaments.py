"""FastAPI router for tournament brackets and Monte Carlo simulations."""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from betting_app.services.enc_simulation_service import (
    EncConfigurationError,
    EncSimulator,
    build_enc_configuration,
)
from betting_app.services.tournament_service import (
    SUPPORTED_BRACKETS,
    TournamentSimulator,
    WorldsSimulator,
    WorldsTeam,
)

router = APIRouter(prefix="/tournaments", tags=["tournaments"])


class SimulateTournamentRequest(BaseModel):
    simulations: int = 10000
    manual_overrides: dict[str, str] | None = None  # match_id -> winner team name


class WorldsTeamInput(BaseModel):
    team: str
    region: str
    pool: int | None = None


class SimulateWorldsRequest(BaseModel):
    simulations: int = 5000
    direct_teams: list[WorldsTeamInput]
    play_in_teams: list[WorldsTeamInput]
    play_in_winner_pool: int


class SimulateEncRequest(BaseModel):
    simulations: int = 5000

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



@router.post("/worlds/simulate")
def simulate_worlds(body: SimulateWorldsRequest) -> dict[str, Any]:
    """Simulate a user-configured Worlds Play-In, Swiss Stage, and knockout."""
    simulator = WorldsSimulator()
    direct_teams = [
        WorldsTeam(name=team.team, region=team.region, pool=team.pool)
        for team in body.direct_teams
    ]
    play_in_teams = [
        WorldsTeam(name=team.team, region=team.region)
        for team in body.play_in_teams
    ]
    n_simulations = min(max(body.simulations, 100), 20000)
    try:
        return simulator.simulate_worlds(
            direct_teams=direct_teams,
            play_in_teams=play_in_teams,
            play_in_winner_pool=body.play_in_winner_pool,
            n_simulations=n_simulations,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/enc")
def get_enc_configuration() -> dict[str, Any]:
    """Return the published ENC field and best available GL lineup for every nation."""
    return build_enc_configuration()


@router.post("/enc/simulate")
def simulate_enc(body: SimulateEncRequest) -> dict[str, Any]:
    """Simulate the published ENC 2027 format when every roster is verifiable."""
    configuration = build_enc_configuration()
    n_simulations = min(max(body.simulations, 100), 50000)
    try:
        return EncSimulator.from_configuration(configuration).simulate(n_simulations)
    except EncConfigurationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


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
