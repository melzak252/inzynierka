"""Tests for Worlds 2026 simulator and API endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from betting_app.api.main import app
from betting_app.services.canonical_match_service import canonical_team_key
from betting_app.services.tournament_service import (
    DEFAULT_WORLDS_2026_TEAMS,
    WorldsSimulator,
)

client = TestClient(app)


def test_worlds_simulator_swiss_and_knockout() -> None:
    k_geng = canonical_team_key("Gen.G")
    k_gam = canonical_team_key("GAM Esports")
    sim = WorldsSimulator(team_ratings={k_geng: 2400.0, k_gam: 1100.0})
    res = sim.simulate_worlds(teams=DEFAULT_WORLDS_2026_TEAMS, n_simulations=200)

    assert res["tournament_id"] == "worlds_2026"
    assert res["format"] == "swiss_and_knockout"
    assert len(res["standings"]) == 16

    total_champ_p = sum(s["champion_prob"] for s in res["standings"])
    assert round(total_champ_p, 1) == 1.0

    # Top teams should have higher Swiss progression prob
    standings_map = {s["team"]: s for s in res["standings"]}
    assert standings_map["Gen.G"]["top8_swiss_prob"] > standings_map["GAM Esports"]["top8_swiss_prob"]


def test_worlds_api_endpoints() -> None:
    res = client.get("/tournaments/worlds/teams")
    assert res.status_code == 200
    data = res.json()
    assert len(data["default_teams"]) == 16

    sim_res = client.post(
        "/tournaments/worlds/simulate",
        json={"simulations": 150},
    )
    assert sim_res.status_code == 200
    sim_data = sim_res.json()
    assert len(sim_data["standings"]) == 16
    assert sum(s["champion_prob"] for s in sim_data["standings"]) > 0.95
