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
from betting_app.services.liquipedia_bracket_service import (
    LiquipediaBracketService,
    TOURNAMENT_METADATA,
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

    # Bracket GET endpoint with sync metadata
    get_lck = client.get("/tournaments/lck_2026_playoffs")
    assert get_lck.status_code == 200
    get_lck_data = get_lck.json()
    assert "source" in get_lck_data
    assert "status" in get_lck_data
    assert "bracket" in get_lck_data
    assert len(get_lck_data["standings"]) == 6

    # Sync POST endpoint
    sync_res = client.post(
        "/tournaments/lck_2026_playoffs/sync",
        json={"source": "auto", "force": False},
    )
    assert sync_res.status_code == 200
    sync_data = sync_res.json()
    assert sync_data["tournament_id"] == "lck_2026_playoffs"
    assert "source" in sync_data
    assert "bracket" in sync_data


def test_liquipedia_parser_wikitext_and_html() -> None:
    service = LiquipediaBracketService()

    # Test Wikitext parsing
    wikitext_sample = (
        "{{Bracket\n"
        "|r1m1team1=KT Rolster |r1m1score1=3 |r1m1win1=1\n"
        "|r1m1team2=Dplus KIA |r1m1score2=0\n"
        "|r1m2team1=T1 |r1m2score1=3 |r1m2win1=1\n"
        "|r1m2team2=BNK FearX |r1m2score2=2\n"
        "}}"
    )
    wiki_matches = service.parse_bracket_wikitext(wikitext_sample)
    assert len(wiki_matches) == 2
    assert wiki_matches[0]["team1"] == "KT Rolster"
    assert wiki_matches[0]["score1"] == 3
    assert wiki_matches[0]["winner"] == "KT Rolster"

    # Test HTML parsing
    html_sample = (
        '<div class="bracket-game">'
        '  <span class="bracket-team">KT Rolster</span><span class="bracket-score">1</span>'
        '  <span class="bracket-team">Dplus KIA</span><span class="bracket-score">3</span>'
        '</div>'
    )
    html_matches = service.parse_bracket_html(html_sample)
    assert len(html_matches) == 1
    assert html_matches[0]["team1"] == "KT Rolster"
    assert html_matches[0]["score2"] == 3
    assert html_matches[0]["winner"] == "Dplus KIA"


def test_bracket_sync_service_chronological_mapping() -> None:
    service = LiquipediaBracketService()
    bracket = get_lck_2026_playoffs_bracket()
    round_order = TOURNAMENT_METADATA["lck_2026_playoffs"]["round_order"]

    parsed_matches = [
        {"team1": "T1", "team2": "BNK FearX", "score1": 3, "score2": 2, "winner": "T1", "date": "2026-08-29 08:00:00"},
        {"team1": "Dplus KIA", "team2": "KT Rolster", "score1": 0, "score2": 3, "winner": "KT Rolster", "date": "2026-08-30 08:00:00"},
        {"team1": "Gen.G", "team2": "KT Rolster", "score1": 3, "score2": 0, "winner": "Gen.G", "date": "2026-09-01 08:00:00"},
        {"team1": "KT Rolster", "team2": "Dplus KIA", "score1": 1, "score2": 3, "winner": "Dplus KIA", "date": "2026-09-04 08:00:00"},
    ]

    updated_bracket, count = service.map_matches_chronologically(bracket, parsed_matches, round_order)
    assert count == 4
    assert updated_bracket.matches["UB_R1_M1"].winner == "KT Rolster"
    assert updated_bracket.matches["UB_R1_M2"].winner == "T1"
    assert updated_bracket.matches["UB_R2_M1"].winner == "Gen.G"
    assert updated_bracket.matches["LB_R2"].winner == "Dplus"


def test_enc_selects_the_best_listed_polish_player_for_each_role() -> None:
    configuration = build_enc_configuration(
        rating_run={"ratings_version": "ratings-v2", "data_cutoff_at": "2026-09-03T00:00:00+00:00"},
        rating_rows=[
            {"entity_name": "Tracyn", "normalized_entity_name": "tracyn", "role": "MID", "rating_value": 1736.5, "games_played": 50},
            {"entity_name": "Inspired", "normalized_entity_name": "inspired", "role": "MID", "rating_value": 2005.5, "games_played": 50},
            {"entity_name": "Jankos", "normalized_entity_name": "jankos", "role": "MID", "rating_value": 1662.6, "games_played": 50},
            {"entity_name": "Czajek", "normalized_entity_name": "czajek", "role": "TOP", "rating_value": 1794.4, "games_played": 50},
            {"entity_name": "Harpoon", "normalized_entity_name": "harpoon", "role": "TOP", "rating_value": 1977.1, "games_played": 50},
            {"entity_name": "Busio", "normalized_entity_name": "busio", "role": "TOP", "rating_value": 2056.9, "games_played": 50},
            {"entity_name": "Trymbi", "normalized_entity_name": "trymbi", "role": "TOP", "rating_value": 1824.8, "games_played": 50},
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


def test_enc_defaults_unrated_fandom_role_players_and_simulates() -> None:
    configuration = build_enc_configuration(
        rating_run={"ratings_version": "ratings-v2", "data_cutoff_at": "2026-09-03T00:00:00+00:00"},
        rating_rows=[],
    )
    guatemala = next(team for team in configuration["teams"] if team["nation"] == "Guatemala")
    solidarity = next(team for team in configuration["teams"] if team["nation"] == "Solidarity Slot")

    assert configuration["simulation_ready"] is True
    assert configuration["default_rating"] == 1500.0
    assert len(configuration["teams"]) == 32
    assert [player["player"] for player in guatemala["selected_roster"]] == [
        "Putilt", "BlindWalker", "Piyey", "SunTiger", "Onier",
    ]
    assert all(player["rating"] == 1500.0 and player["rating_source"] == "default"
               for player in guatemala["selected_roster"])
    assert solidarity["selection_status"] == "defaulted"
    assert EncSimulator.from_configuration(configuration).simulate(100)["simulations"] == 100


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
