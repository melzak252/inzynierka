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
    assert len(lpl.teams) == 8
    assert "UB_R1_M1" in lpl.matches
    assert "LB_R3" in lpl.matches


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
    # LPL simulation endpoint
    sim_lpl = client.post(
        "/tournaments/lpl_2026_split3_playoffs/simulate",
        json={"simulations": 200},
    )
    assert sim_lpl.status_code == 200
    lpl_standings = sim_lpl.json()["standings"]
    assert len(lpl_standings) == 8
    assert round(sum(s["champion_prob"] for s in lpl_standings), 1) == 1.0


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


def test_lpl_simulation_tes_elimination_and_no_100_percent_top3_bug() -> None:
    """Verify TES is not mathematically forced to 100% Top 3 and when eliminated in LB R1 has 0% Top 3."""
    sim = TournamentSimulator()

    # 1. Pre-playoff state: TES must NOT be hardcoded to 100% Top 3
    bracket_pre = get_lpl_2026_split3_playoffs_bracket()
    res_pre = sim.simulate(bracket_pre, n_simulations=500)
    standings_pre = {s["team"]: s for s in res_pre["standings"]}
    assert len(res_pre["standings"]) == 8
    assert standings_pre["Top Esports"]["top3_prob"] < 1.0, "TES must not have 100% top 3 before playoffs"
    assert standings_pre["Top Esports"]["champion_prob"] > 0.0

    # 2. Live state where TES was eliminated in LB R1 by Invictus Gaming
    bracket_live = get_lpl_2026_split3_playoffs_bracket()
    # UB R1 results: TES lost to LGD
    bracket_live.matches["UB_R1_M1"].winner = "LGD Gaming"
    bracket_live.matches["UB_R1_M1"].score1 = 2
    bracket_live.matches["UB_R1_M1"].score2 = 3
    # Advance loser TES to LB_R1_M1 slot 2
    bracket_live.matches["LB_R1_M1"].team2 = "Top Esports"
    # LB R1 results: Invictus Gaming defeats Top Esports
    bracket_live.matches["LB_R1_M1"].winner = "Invictus Gaming"
    bracket_live.matches["LB_R1_M1"].score1 = 3
    bracket_live.matches["LB_R1_M1"].score2 = 2

    res_live = sim.simulate(bracket_live, n_simulations=500)
    standings_live = {s["team"]: s for s in res_live["standings"]}
    tes = standings_live["Top Esports"]
    assert tes["champion_prob"] == 0.0
    assert tes["top2_prob"] == 0.0
    assert tes["top3_prob"] == 0.0
    assert tes["top4_prob"] == 0.0

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


def test_lec_bracket_round_order_keys_match() -> None:
    """Verify LEC round_order keys in metadata strictly match bracket match IDs."""
    meta = TOURNAMENT_METADATA["lec_2026_summer_playoffs"]
    bracket = get_lec_2026_summer_playoffs_bracket()
    for node_id in meta["round_order"]:
        assert node_id in bracket.matches, f"Node {node_id} from round_order must exist in LEC matches"


def test_score_alignment_reversed_order() -> None:
    """Verify scores are aligned to node.team1 and node.team2 even when parsed match has reversed sides."""
    service = LiquipediaBracketService()
    bracket = get_lck_2026_playoffs_bracket()
    # In bracket: UB_R1_M1 has team1="KT Rolster", team2="Dplus"
    # Parsed match has team1="Dplus KIA" (0) vs team2="KT Rolster" (3)
    parsed = [
        {
            "team1": "Dplus KIA",
            "team2": "KT Rolster",
            "score1": 0,
            "score2": 3,
            "winner": "KT Rolster",
            "date": "2026-08-30 08:00:00",
        }
    ]
    updated, count = service.map_matches_chronologically(bracket, parsed, ["UB_R1_M1"])
    assert count == 1
    node = updated.matches["UB_R1_M1"]
    assert node.team1 == "KT Rolster"
    assert node.team2 == "Dplus"
    assert node.score1 == 3, "KT Rolster (team1) must have score 3, not 0"
    assert node.score2 == 0, "Dplus (team2) must have score 0, not 3"
    assert node.winner == "KT Rolster"


def test_all_supported_brackets_simulate_successfully() -> None:
    """Verify each supported bracket tree simulates without dead ends or missing slots."""
    sim = TournamentSimulator()
    for tournament_id, builder in SUPPORTED_BRACKETS.items():
        bracket = builder()
        res = sim.simulate(bracket, n_simulations=200)
        assert res["tournament_id"] == tournament_id
        assert len(res["standings"]) == len(bracket.teams)
        total_champ = sum(s["champion_prob"] for s in res["standings"])
        assert round(total_champ, 2) == 1.0, f"{tournament_id} champion probabilities must sum to 1"


def test_lpl_bracket_sync_and_upper_finals() -> None:
    """Verify LPL 2026 bracket mapping places AL vs BLG in Upper Finals and does not pre-populate Grand Final."""
    service = LiquipediaBracketService()
    bracket = get_lpl_2026_split3_playoffs_bracket()
    round_order = TOURNAMENT_METADATA["lpl_2026_split3_playoffs"]["round_order"]

    # Simulated real Cargo export matches up to 2026-09-05
    fandom_matches = [
        {"team1": "Top Esports", "team2": "LGD Gaming", "score1": 2, "score2": 3, "winner": "LGD Gaming", "date": "2026-08-29 09:00:00"},
        {"team1": "JD Gaming", "team2": "Team WE", "score1": 1, "score2": 3, "winner": "Team WE", "date": "2026-08-30 09:00:00"},
        {"team1": "Bilibili Gaming", "team2": "Team WE", "score1": 3, "score2": 1, "winner": "Bilibili Gaming", "date": "2026-09-03 09:00:00"},
        {"team1": "Anyone's Legend", "team2": "LGD Gaming", "score1": 3, "score2": 1, "winner": "Anyone's Legend", "date": "2026-09-04 09:00:00"},
        {"team1": "Invictus Gaming", "team2": "Top Esports", "score1": 3, "score2": 2, "winner": "Invictus Gaming", "date": "2026-09-05 06:00:00"},
        {"team1": "Ninjas in Pyjamas.CN", "team2": "JD Gaming", "score1": 1, "score2": 0, "winner": None, "date": "2026-09-05 11:00:00"},
        {"team1": "Invictus Gaming", "team2": "Team WE", "score1": None, "score2": None, "winner": None, "date": "2026-09-06 06:00:00"},
        {"team1": "Anyone's Legend", "team2": "Bilibili Gaming", "score1": None, "score2": None, "winner": None, "date": "2026-09-07 09:00:00"},
    ]

    updated, count = service.map_matches_chronologically(bracket, fandom_matches, round_order)
    assert count >= 6

    # Upper Finals MUST be Anyone's Legend vs Bilibili Gaming
    ub_final = updated.matches["UB_Final"]
    assert {ub_final.team1, ub_final.team2} == {"Anyone's Legend", "Bilibili Gaming"}
    assert ub_final.winner is None

    # Lower Round 2 Match 1 MUST be Invictus Gaming vs Team WE
    lb_r2_m1 = updated.matches["LB_R2_M1"]
    assert {lb_r2_m1.team1, lb_r2_m1.team2} == {"Invictus Gaming", "Team WE"}

    # Lower Round 2 Match 2 MUST await winner of NIP vs JDG and loser of AL vs LGD (LGD Gaming)
    lb_r2_m2 = updated.matches["LB_R2_M2"]
    assert "LGD Gaming" in (lb_r2_m2.team1, lb_r2_m2.team2)

    # Grand Final MUST NOT have predetermined teams or winner
    grand_final = updated.matches["Grand_Final"]
    assert grand_final.team1 is None
    assert grand_final.team2 is None
    assert grand_final.winner is None

    # Simulate tournament: AL and BLG must have high champion probability, TES must be 0%
    sim = TournamentSimulator()
    sim_res = sim.simulate(updated, n_simulations=500)
    standings_map = {s["team"]: s for s in sim_res["standings"]}
    assert standings_map["Top Esports"]["champion_prob"] == 0.0
    assert standings_map["Bilibili Gaming"]["champion_prob"] > 0.25
    assert standings_map["Anyone's Legend"]["champion_prob"] > 0.25
