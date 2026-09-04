"""Tests for tournament bracket simulation engine and endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from betting_app.api.main import app
from betting_app.services.tournament_service import (
    TournamentSimulator,
    get_lck_2026_playoffs_bracket,
)

client = TestClient(app)


def test_lck_bracket_structure() -> None:
    bracket = get_lck_2026_playoffs_bracket()
    assert bracket.id == "lck_2026_playoffs"
    assert len(bracket.teams) == 6
    assert "Grand_Final" in bracket.matches
    assert bracket.matches["UB_R1_M2"].winner == "T1"


def test_tournament_simulator_deterministic_manual_override() -> None:
    bracket = get_lck_2026_playoffs_bracket()
    # Mock ratings: give Gen.G huge rating advantage
    ratings = {"geng": 2500.0, "t1": 1500.0, "ktrolster": 1400.0, "dplus": 1300.0}
    sim = TournamentSimulator(team_ratings=ratings)

    # Force KT Rolster to win Grand Final
    res = sim.simulate(bracket, n_simulations=100, manual_overrides={"Grand_Final": "KT Rolster"})
    assert res["simulations"] == 100
    standings = {s["team"]: s["champion_prob"] for s in res["standings"]}
    assert standings["KT Rolster"] == 1.0


def test_tournaments_api_endpoints() -> None:
    res = client.get("/tournaments")
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 1
    assert data[0]["id"] == "lck_2026_playoffs"

    sim_res = client.post(
        "/tournaments/lck_2026_playoffs/simulate",
        json={"simulations": 200},
    )
    assert sim_res.status_code == 200
    sim_data = sim_res.json()
    assert len(sim_data["standings"]) == 6
    total_champ_p = sum(s["champion_prob"] for s in sim_data["standings"])
    assert round(total_champ_p, 1) == 1.0
