"""Tests for tournament bracket simulation engine and endpoints across multiple leagues."""

from __future__ import annotations

from fastapi.testclient import TestClient

from betting_app.api.main import app
from betting_app.services.tournament_service import (
    SUPPORTED_BRACKETS,
    TournamentSimulator,
    get_lck_2026_playoffs_bracket,
    get_lec_2026_summer_playoffs_bracket,
    get_lpl_2026_split3_playoffs_bracket,
)
from betting_app.services.enc_simulation_service import (
    EncSimulator,
    EncTeam,
    build_enc_configuration,
)

client = TestClient(app)


def test_supported_brackets_structure() -> None:
    assert "lck_2026_playoffs" in SUPPORTED_BRACKETS
    assert "lec_2026_summer_playoffs" in SUPPORTED_BRACKETS
    assert "lpl_2026_split3_playoffs" in SUPPORTED_BRACKETS

    lck = get_lck_2026_playoffs_bracket()
    assert lck.id == "lck_2026_playoffs"
    assert len(lck.teams) == 6
    assert lck.matches["LB_R1"].winner == "Dplus"

    lec = get_lec_2026_summer_playoffs_bracket()
    assert lec.region == "LEC"
    assert len(lec.teams) == 6
    assert "UB_SF1" in lec.matches

    lpl = get_lpl_2026_split3_playoffs_bracket()
    assert lpl.region == "LPL"
    assert len(lpl.teams) == 6


def test_tournament_simulator_deterministic_manual_override() -> None:
    bracket = get_lck_2026_playoffs_bracket()
    ratings = {"geng": 2500.0, "t1": 1500.0, "ktrolster": 1400.0, "dplus": 1300.0}
    sim = TournamentSimulator(team_ratings=ratings)

    res = sim.simulate(bracket, n_simulations=100, manual_overrides={"Grand_Final": "T1"})
    assert res["simulations"] == 100
    standings = {s["team"]: s["champion_prob"] for s in res["standings"]}
    assert standings["T1"] == 1.0


def test_tournaments_api_endpoints() -> None:
    res = client.get("/tournaments")
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 3
    ids = [t["id"] for t in data]
    assert "lck_2026_playoffs" in ids
    assert "lec_2026_summer_playoffs" in ids
    assert "lpl_2026_split3_playoffs" in ids

    # LCK simulation endpoint
    sim_lck = client.post(
        "/tournaments/lck_2026_playoffs/simulate",
        json={"simulations": 200},
    )
    assert sim_lck.status_code == 200
    standings = sim_lck.json()["standings"]
    assert len(standings) == 6
    total_p = sum(s["champion_prob"] for s in standings)
    assert round(total_p, 1) == 1.0

    # LEC simulation endpoint
    sim_lec = client.post(
        "/tournaments/lec_2026_summer_playoffs/simulate",
        json={"simulations": 200},
    )
    assert sim_lec.status_code == 200
    assert len(sim_lec.json()["standings"]) == 6


def test_enc_selects_the_best_listed_polish_player_for_each_role() -> None:
    configuration = build_enc_configuration(
        rating_run={"ratings_version": "ratings-v2", "data_cutoff_at": "2026-09-03T00:00:00+00:00"},
        rating_rows=[
            {"entity_name": "Tracyn", "normalized_entity_name": "tracyn", "role": "TOP", "rating_value": 1736.5, "games_played": 50},
            {"entity_name": "Inspired", "normalized_entity_name": "inspired", "role": "JUNGLE", "rating_value": 2005.5, "games_played": 50},
            {"entity_name": "Jankos", "normalized_entity_name": "jankos", "role": "JUNGLE", "rating_value": 1662.6, "games_played": 50},
            {"entity_name": "Czajek", "normalized_entity_name": "czajek", "role": "MID", "rating_value": 1794.4, "games_played": 50},
            {"entity_name": "Harpoon", "normalized_entity_name": "harpoon", "role": "ADC", "rating_value": 1977.1, "games_played": 50},
            {"entity_name": "Busio", "normalized_entity_name": "busio", "role": "SUPPORT", "rating_value": 2056.9, "games_played": 50},
            {"entity_name": "Trymbi", "normalized_entity_name": "trymbi", "role": "SUPPORT", "rating_value": 1824.8, "games_played": 50},
        ],
    )
    poland = next(team for team in configuration["teams"] if team["nation"] == "Poland")

    assert poland["selection_status"] == "ready"
    assert {player["role"]: player["player"] for player in poland["selected_roster"]} == {
        "TOP": "Tracyn",
        "JUNGLE": "Inspired",
        "MID": "Czajek",
        "ADC": "Harpoon",
        "SUPPORT": "Busio",
    }


def test_enc_simulator_uses_published_stage_sizes_and_series_lengths() -> None:
    teams = [
        *(EncTeam(f"Direct {index}", "group_stage", 2000.0 + index) for index in range(8)),
        *(EncTeam(f"Play-In {index}", "play_in", 1800.0 + index) for index in range(24)),
    ]
    result = EncSimulator(teams).simulate(100)

    assert result["format"]["participants"] == 32
    assert result["format"]["play_in"].startswith("24 teams, 4 groups of 6")
    assert len(result["standings"]) == 32
    assert sum(team["champion_prob"] for team in result["standings"]) == 1.0
    assert all(team["group_stage_prob"] == 1.0 for team in result["standings"] if team["entry_stage"] == "group_stage")
