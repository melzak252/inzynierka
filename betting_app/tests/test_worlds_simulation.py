"""Tests for the manually configured Worlds Play-In, Swiss, and knockout simulator."""

from __future__ import annotations

from fastapi.testclient import TestClient

from betting_app.services.canonical_match_service import canonical_team_key
from betting_app.services.tournament_service import WorldsSimulator, WorldsTeam


def _direct_teams() -> list[WorldsTeam]:
    pools = [1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4]
    return [
        WorldsTeam(name=f"Swiss Team {index}", region="LCK" if index < 4 else "LEC", pool=pool)
        for index, pool in enumerate(pools, start=1)
    ]


def _play_in_teams() -> list[WorldsTeam]:
    return [
        WorldsTeam(name="Play-In Favorite", region="LPL"),
        WorldsTeam(name="Play-In Team 2", region="LCP"),
        WorldsTeam(name="Play-In Team 3", region="CBLOL"),
        WorldsTeam(name="Play-In Team 4", region="EMEA Masters"),
    ]


def test_worlds_simulator_runs_play_in_swiss_and_knockout() -> None:
    favorite_key = canonical_team_key("Play-In Favorite")
    simulator = WorldsSimulator(team_ratings={favorite_key: 2400.0})

    result = simulator.simulate_worlds(
        direct_teams=_direct_teams(),
        play_in_teams=_play_in_teams(),
        play_in_winner_pool=4,
        n_simulations=200,
    )

    assert result["format"] == "play_in_double_elimination_bo5_swiss_and_knockout"
    assert len(result["standings"]) == 19
    assert round(sum(standing["champion_prob"] for standing in result["standings"]), 1) == 1.0
    assert round(sum(standing["top8_swiss_prob"] for standing in result["standings"]), 1) == 8.0

    standings = {standing["team"]: standing for standing in result["standings"]}
    assert standings["Swiss Team 1"]["play_in_qualifier_prob"] == 1.0
    assert standings["Play-In Favorite"]["play_in_qualifier_prob"] > 0.5


def test_worlds_api_requires_manual_participants(client: TestClient) -> None:
    direct_teams = [
        {"team": team.name, "region": team.region, "pool": team.pool}
        for team in _direct_teams()
    ]
    play_in_teams = [{"team": team.name, "region": team.region} for team in _play_in_teams()]

    missing_roster = client.post("/tournaments/worlds/simulate", json={"simulations": 100})
    assert missing_roster.status_code == 422

    response = client.post(
        "/tournaments/worlds/simulate",
        json={
            "simulations": 150,
            "direct_teams": direct_teams,
            "play_in_teams": play_in_teams,
            "play_in_winner_pool": 4,
        },
    )
    assert response.status_code == 200
    assert len(response.json()["standings"]) == 19


def test_worlds_rejects_an_unbalanced_swiss_pool(client: TestClient) -> None:
    direct_teams = [
        {"team": team.name, "region": team.region, "pool": 1}
        for team in _direct_teams()
    ]
    response = client.post(
        "/tournaments/worlds/simulate",
        json={
            "direct_teams": direct_teams,
            "play_in_teams": [{"team": team.name, "region": team.region} for team in _play_in_teams()],
            "play_in_winner_pool": 4,
        },
    )
    assert response.status_code == 422
    assert "Direct Swiss slots" in response.json()["detail"]
