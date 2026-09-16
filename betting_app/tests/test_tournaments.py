"""Tests for tournament bracket simulation engine and endpoints across multiple leagues."""

from __future__ import annotations

import random

import pytest

from fastapi.testclient import TestClient

from betting_app.api.main import app
from betting_app.services.tournament_service import (
    SUPPORTED_BRACKETS,
    TournamentSimulator,
    BracketMatchNode,
    TournamentBracket,
    WorldsSimulator,
    get_lck_2026_playoffs_bracket,
    get_lec_2026_summer_playoffs_bracket,
    get_lpl_2026_split3_playoffs_bracket,
    get_lcs_2026_championship_bracket,
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


@pytest.fixture
def offline_tournament_api(monkeypatch):
    monkeypatch.setattr(TournamentSimulator, "_load_team_ratings", staticmethod(lambda: {}))

    def local_bracket(self, tournament_id, **kwargs):
        return {"bracket": SUPPORTED_BRACKETS[tournament_id](), "source": "offline_fixture", "status": "ready"}

    monkeypatch.setattr(LiquipediaBracketService, "sync_bracket", local_bracket)


def test_supported_brackets_structure() -> None:
    assert "lck_2026_playoffs" in SUPPORTED_BRACKETS
    assert "lec_2026_summer_playoffs" in SUPPORTED_BRACKETS
    assert "lpl_2026_split3_playoffs" in SUPPORTED_BRACKETS
    assert "lcs_2026_championship" in SUPPORTED_BRACKETS

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


    lcs = get_lcs_2026_championship_bracket()
    assert lcs.region == "LCS"
    assert len(lcs.teams) == 6
    assert "UB_R1_M1" in lcs.matches
    assert "Grand_Final" in lcs.matches

def test_tournament_simulator_deterministic_manual_override() -> None:
    bracket = get_lck_2026_playoffs_bracket()
    ratings = {"geng": 2500.0, "t1": 1500.0, "ktrolster": 1400.0, "dplus": 1300.0}
    sim = TournamentSimulator(team_ratings=ratings)

    res = sim.simulate(
        bracket, n_simulations=100,
        manual_overrides={"LB_R3": "T1", "LB_Final": "T1", "Grand_Final": "T1"},
    )
    assert res["simulations"] == 100
    standings = {s["team"]: s["champion_prob"] for s in res["standings"]}
    assert standings["T1"] == 1.0


def test_tournaments_api_endpoints(offline_tournament_api) -> None:
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
    sim = TournamentSimulator(team_ratings={"offline": 1750.0}, seed=82)

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
    sim = TournamentSimulator(team_ratings={"offline": 1750.0}, seed=82)
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
    sim = TournamentSimulator(team_ratings={"offline": 1750.0}, seed=82)
    sim_res = sim.simulate(updated, n_simulations=500)
    standings_map = {s["team"]: s for s in sim_res["standings"]}
    assert standings_map["Top Esports"]["champion_prob"] == 0.0
    assert standings_map["Bilibili Gaming"]["champion_prob"] > 0.25
    assert standings_map["Anyone's Legend"]["champion_prob"] > 0.25


def _audit_final(**kwargs) -> TournamentBracket:
    node = BracketMatchNode(
        id="title", name="Title", round_name="Final", bracket_section="final",
        team1="Alpha", team2="Beta", **kwargs,
    )
    return TournamentBracket("audit", "Audit", "test", "single_elimination", {"title": node}, ["Alpha", "Beta"])


def test_audit_empty_ratings_do_not_open_database(monkeypatch) -> None:
    def forbidden():
        pytest.fail("Explicit empty ratings must not load the configured database")

    monkeypatch.setattr(TournamentSimulator, "_load_team_ratings", staticmethod(forbidden))
    assert TournamentSimulator(team_ratings={}).estimate_matchup_probability("Alpha", "Beta") == 0.5


def test_audit_score_distribution_agrees_with_series_and_reversed_sides() -> None:
    sim = TournamentSimulator(team_ratings={"alpha": 1925.0, "beta": 1750.0})
    scores = sim.estimate_score_distribution("Alpha", "Beta", 5)
    reversed_scores = sim.estimate_score_distribution("Beta", "Alpha", 5)
    assert sum(scores.values()) == pytest.approx(1.0)
    assert sum(p for score, p in scores.items() if score.startswith("3-")) == pytest.approx(
        sim.estimate_matchup_probability("Alpha", "Beta", 5), abs=1e-12,
    )
    for score, probability in scores.items():
        assert probability == pytest.approx(reversed_scores["-".join(reversed(score.split("-")))])


def test_audit_rejects_nonparticipant_override() -> None:
    bracket = get_lec_2026_summer_playoffs_bracket()
    with pytest.raises(ValueError):
        TournamentSimulator(team_ratings={"alpha": 1750}).simulate(
            bracket, 1, {"UB_SF1": "G2 Esports"},
        )


def test_audit_rejects_override_of_confirmed_result() -> None:
    with pytest.raises(ValueError):
        TournamentSimulator(team_ratings={"alpha": 1750}).simulate(
            get_lck_2026_playoffs_bracket(), 1, {"UB_R1_M1": "Dplus"},
        )


def test_audit_rejects_unknown_override_match() -> None:
    with pytest.raises(ValueError):
        TournamentSimulator(team_ratings={"alpha": 1750}).simulate(
            get_lec_2026_summer_playoffs_bracket(), 1, {"absent": "G2 Esports"},
        )


def test_audit_arbitrary_final_id_preserves_champion_and_runner_up_mass() -> None:
    result = TournamentSimulator(team_ratings={"alpha": 1750}).simulate(
        _audit_final(winner="Alpha", score1=3, score2=0), 1,
    )
    standings = {row["team"]: row for row in result["standings"]}
    assert standings["Alpha"]["champion_prob"] == 1.0
    assert standings["Beta"]["champion_prob"] == 0.0
    assert sum(row["top2_prob"] for row in standings.values()) == 2.0
    assert all(row["top4_prob"] == 1.0 for row in standings.values())


@pytest.mark.parametrize("change", ["cycle", "missing_target", "slot_collision", "missing_opponent", "duplicate_seed"])
def test_audit_rejects_invalid_graph(change) -> None:
    bracket = get_lec_2026_summer_playoffs_bracket()
    if change == "cycle":
        bracket.matches["Grand_Final"].next_match_winner_id = "UB_SF1"
    elif change == "missing_target":
        bracket.matches["UB_SF1"].next_match_winner_id = "absent"
    elif change == "slot_collision":
        bracket.matches["UB_SF2"].next_match_winner_slot = 1
    elif change == "missing_opponent":
        bracket.matches["UB_SF1"].team2 = None
    else:
        bracket.matches["UB_SF1"].team2 = "G2 Esports"
    with pytest.raises(ValueError):
        TournamentSimulator(team_ratings={"alpha": 1750}).simulate(bracket, 1)


@pytest.mark.parametrize("scores,winner", [((3, 3), "Alpha"), ((2, 0), "Alpha"), ((3, 0), None), ((-1, 0), None)])
def test_audit_rejects_inconsistent_live_score(scores, winner) -> None:
    with pytest.raises(ValueError):
        TournamentSimulator(team_ratings={"alpha": 1750}).simulate(
            _audit_final(score1=scores[0], score2=scores[1], winner=winner), 1,
        )


def test_audit_live_series_is_conditioned_on_current_score(monkeypatch) -> None:
    sim = TournamentSimulator(team_ratings={"alpha": 1750})
    monkeypatch.setattr(sim._rng, "random", lambda: 0.7)
    result = sim.simulate(_audit_final(score1=2, score2=0), 1)
    # Equal map strengths: from 2-0 in Bo5, Alpha wins with 7/8, not 1/2.
    assert next(row for row in result["standings"] if row["team"] == "Alpha")["champion_prob"] == 1.0


def test_audit_rejects_contradictory_downstream_live_participants() -> None:
    bracket = get_lck_2026_playoffs_bracket()
    bracket.matches["LB_R2"].team1 = "T1"
    with pytest.raises(ValueError):
        TournamentSimulator(team_ratings={"alpha": 1750}).simulate(bracket, 1)


def test_audit_rng_is_local_and_seed_reproducible() -> None:
    state = random.getstate()
    first = TournamentSimulator(team_ratings={"alpha": 1750}, seed=82).simulate(_audit_final(), 31)
    second = TournamentSimulator(team_ratings={"alpha": 1750}, seed=82).simulate(_audit_final(), 31)
    assert first["standings"] == second["standings"]
    assert random.getstate() == state
    assert sum(row["champion_prob"] for row in first["standings"]) == pytest.approx(1.0)


def test_audit_swiss_finds_available_nonrematch_pairing(monkeypatch) -> None:
    sim = WorldsSimulator(team_ratings={"alpha": 1750})
    monkeypatch.setattr(random, "shuffle", lambda teams: None)
    if hasattr(sim, "_rng"):
        monkeypatch.setattr(sim._rng, "shuffle", lambda teams: None)
    played = {frozenset(("Alpha", "Beta")), frozenset(("Gamma", "Delta"))}
    prior = played.copy()
    winners, losers = sim.simulate_swiss_round(["Alpha", "Beta", "Gamma", "Delta"], 1, played)
    assert len(played - prior) == 2
    assert set(winners + losers) == {"Alpha", "Beta", "Gamma", "Delta"}


@pytest.mark.parametrize("pool", [["Alpha", "Beta", "Gamma"], ["Alpha", "Alpha"]])
def test_audit_swiss_rejects_odd_or_duplicate_bucket(pool) -> None:
    with pytest.raises(ValueError):
        WorldsSimulator(team_ratings={"alpha": 1750}).simulate_swiss_round(pool, 1, set())


def test_audit_swiss_rejects_impossible_no_rematch_draw() -> None:
    with pytest.raises(ValueError):
        WorldsSimulator(team_ratings={"alpha": 1750}).simulate_swiss_round(
            ["Alpha", "Beta"], 1, {frozenset(("Alpha", "Beta"))},
        )


@pytest.mark.parametrize("count", [0, -1, True])
def test_audit_rejects_invalid_simulation_count(count) -> None:
    with pytest.raises(ValueError):
        TournamentSimulator(team_ratings={"alpha": 1750}).simulate(_audit_final(), count)


def test_audit_unrated_predictions_expose_noncertified_scope() -> None:
    result = TournamentSimulator(team_ratings={"alpha": 1750}).simulate(_audit_final(), 1)
    assert result["provenance"]["eligibility_live"] == 0
    assert result["provenance"]["rating_source_available_at"] is None
    assert result["provenance"]["unrated_teams"] == ["Beta"]


def test_audit_api_rejects_impossible_manual_winner(offline_tournament_api) -> None:
    response = client.post(
        "/tournaments/lec_2026_summer_playoffs/simulate",
        json={"simulations": 100, "manual_overrides": {"UB_SF1": "G2 Esports"}},
    )
    assert response.status_code == 422


def test_audit_renamed_double_elimination_routes_and_placements() -> None:
    bracket = get_lec_2026_summer_playoffs_bracket()
    forced = {
        "UB_SF1": "Karmine Corp", "UB_SF2": "G2 Esports",
        "LB_R1_M1": "GIANTX", "LB_R1_M2": "Team Vitality",
        "UB_Final": "Karmine Corp", "LB_SF": "GIANTX",
        "LB_Final": "G2 Esports", "Grand_Final": "G2 Esports",
    }
    renamed = {name: f"node{index}" for index, name in enumerate(bracket.matches)}
    for node in bracket.matches.values():
        node.id = renamed[node.id]
        node.next_match_winner_id = renamed.get(node.next_match_winner_id)
        node.next_match_loser_id = renamed.get(node.next_match_loser_id)
    bracket.matches = {node.id: node for node in bracket.matches.values()}
    result = TournamentSimulator(team_ratings={"offline": 1750}).simulate(
        bracket, 1, {renamed[name]: winner for name, winner in forced.items()},
    )
    standings = {row["team"]: row for row in result["standings"]}
    assert standings["G2 Esports"]["champion_prob"] == 1.0
    assert standings["Karmine Corp"]["top2_prob"] == 1.0
    assert standings["GIANTX"]["top3_prob"] == 1.0
    assert standings["GIANTX"]["top2_prob"] == 0.0
    assert standings["Team Vitality"]["top4_prob"] == 1.0
    assert standings["Team Vitality"]["top3_prob"] == 0.0
    assert standings["Natus Vincere"]["top4_prob"] == 0.0
    for cutoff, key in ((1, "champion_prob"), (2, "top2_prob"), (3, "top3_prob"), (4, "top4_prob")):
        assert sum(row[key] for row in standings.values()) == cutoff


def test_audit_single_elimination_does_not_invent_third_place() -> None:
    bracket = _audit_final(winner="Alpha", score1=3, score2=0)
    bracket.teams.extend(["Gamma", "Delta"])
    bracket.matches["semi1"] = BracketMatchNode(
        "semi1", "Semi 1", "Semi", "upper", team1="Alpha", team2="Gamma",
        winner="Alpha", next_match_winner_id="title", next_match_winner_slot=1,
    )
    bracket.matches["semi2"] = BracketMatchNode(
        "semi2", "Semi 2", "Semi", "upper", team1="Beta", team2="Delta",
        winner="Beta", next_match_winner_id="title", next_match_winner_slot=2,
    )
    result = TournamentSimulator(team_ratings={"offline": 1750}).simulate(bracket, 1)
    standings = {row["team"]: row for row in result["standings"]}
    assert standings["Gamma"]["top3_prob"] is None
    assert standings["Delta"]["top3_prob"] is None
    assert all(row["top4_prob"] == 1.0 for row in standings.values())


@pytest.mark.parametrize("side", [1, 2])
def test_audit_missing_opponent_is_not_an_implicit_bye(side) -> None:
    bracket = get_lec_2026_summer_playoffs_bracket()
    setattr(bracket.matches["UB_SF1"], f"team{side}", None)
    with pytest.raises(ValueError):
        TournamentSimulator(team_ratings={"offline": 1750}).simulate(bracket, 1)


@pytest.mark.parametrize("best_of", [0, 2, 3.5, True])
def test_audit_rejects_invalid_series_length(best_of) -> None:
    sim = TournamentSimulator(team_ratings={"offline": 1750})
    with pytest.raises(ValueError):
        sim.estimate_matchup_probability("Alpha", "Beta", best_of)


def test_audit_extreme_ratings_remain_finite_and_complementary() -> None:
    sim = TournamentSimulator(team_ratings={"alpha": -1e9, "beta": 1e9})
    probability = sim.estimate_matchup_probability("Alpha", "Beta")
    assert 0.0 <= probability <= 1.0
    assert probability + sim.estimate_matchup_probability("Beta", "Alpha") == pytest.approx(1.0)


def test_audit_worlds_mass_and_scope_are_explicit() -> None:
    from betting_app.services.tournament_service import WorldsTeam

    direct = [
        WorldsTeam(f"Direct {index}", "Region", (index // 4) + 1)
        for index in range(15)
    ]
    play_in = [WorldsTeam(f"Play In {index}", "Region") for index in range(4)]
    result = WorldsSimulator(team_ratings={"offline": 1750}, seed=82).simulate_worlds(direct, play_in, 4, 31)
    for key, total in (
        ("play_in_qualifier_prob", 16), ("top8_swiss_prob", 8),
        ("top4_prob", 4), ("top2_prob", 2), ("champion_prob", 1),
    ):
        assert sum(row[key] for row in result["standings"]) == pytest.approx(total, abs=1e-12)
    assert result["simulation_scope"]["rules_verified"] is False
    assert result["simulation_scope"]["pre_event_forecast"] is False
    assert result["provenance"]["eligibility_live"] == 0


def test_audit_invalid_probability_cannot_fabricate_series_winner(monkeypatch) -> None:
    sim = WorldsSimulator(team_ratings={"offline": 1750})
    monkeypatch.setattr(sim, "estimate_matchup_probability", lambda *args, **kwargs: float("nan"))
    with pytest.raises(ValueError):
        sim.simulate_series_winner("Alpha", "Beta", 3)


def test_audit_live_score_is_aligned_to_team_slots(monkeypatch) -> None:
    sim = TournamentSimulator(team_ratings={"offline": 1750})
    monkeypatch.setattr(sim._rng, "random", lambda: 0.3)
    result = sim.simulate(_audit_final(score1=0, score2=2), 1)
    assert next(row for row in result["standings"] if row["team"] == "Beta")["champion_prob"] == 1.0


def test_swiss_keeps_resolved_identities_until_a_new_simulation(monkeypatch):
    aliases = {team: team.lower() for team in "ABCD"}
    monkeypatch.setattr(
        "betting_app.services.tournament_service.canonical_team_key",
        lambda team: aliases[team],
    )
    simulator = WorldsSimulator({}, seed=82)
    simulator.simulate_swiss_round(list("ABCD"), 1, set())

    # A registry edit must not change participant identity between rounds.
    aliases["B"] = aliases["A"]
    winners, losers = simulator.simulate_swiss_round(list("ABCD"), 1, set())
    assert sorted(winners + losers) == list("ABCD")

    # The cache is not global: a fresh simulator must see the conflicting alias.
    with pytest.raises(ValueError):
        WorldsSimulator({}, seed=82).simulate_swiss_round(list("ABCD"), 1, set())
