"""Tournament bracket models and simulator engine using the operational rating model."""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Sequence

from betting_app.core.db import connect
from betting_app.services.canonical_match_service import canonical_team_key
from betting_app.services.upcoming_inference_service import series_probability

logger = logging.getLogger(__name__)


@dataclass
class BracketMatchNode:
    id: str  # e.g. "UB_R1_M1", "UB_Final", "Grand_Final"
    name: str  # e.g. "Upper Round 1 - Match 1"
    round_name: str  # e.g. "Upper Round 1", "Lower Final"
    bracket_section: str  # "upper", "lower", "final"
    best_of: int = 5
    team1: str | None = None  # Team name or None if TBD
    team2: str | None = None
    winner: str | None = None  # Confirmed winner if match already played
    score1: int | None = None
    score2: int | None = None
    next_match_winner_id: str | None = None  # Where does the winner advance
    next_match_winner_slot: int = 1  # Slot 1 or 2 in target match
    next_match_loser_id: str | None = None  # Where does the loser drop (Double Elim)
    next_match_loser_slot: int = 2


@dataclass
class TournamentBracket:
    id: str
    name: str
    region: str
    format: str  # "double_elimination", "single_elimination"
    matches: dict[str, BracketMatchNode]
    teams: list[str]


def get_lck_2026_playoffs_bracket() -> TournamentBracket:
    """Construct the complete, official 6-team LCK Double Elimination Playoff bracket tree.

    Complete tournament history and upcoming matches (LCK 2026 Season - Playoffs):
      Upper Round 1 (Quarterfinals):
        - UB_R1_M1: KT Rolster (3) vs Dplus (0) -> KT won, Dplus dropped to Lower R1
        - UB_R1_M2: T1 (3) vs BNK FearX (2) -> T1 won, BNK FearX dropped to Lower R1
      Upper Round 2 (Semifinals):
        - UB_R2_M1: Gen.G (3) vs KT Rolster (0) -> Gen.G won to UB Final, KT dropped to Lower R2
        - UB_R2_M2: Hanwha Life (3) vs T1 (2) -> Hanwha won to UB Final, T1 dropped to Lower R3
      Lower Round 1:
        - LB_R1: Dplus (3) vs BNK FearX (2) -> Dplus won, BNK FearX eliminated
      Lower Round 2 (Sept 4):
        - LB_R2: KT Rolster vs Dplus -> Winner to Lower R3 vs T1, Loser eliminated
      Upper Final (Sept 5):
        - UB_Final: Gen.G vs Hanwha Life -> Winner to Grand Final, Loser to Lower Final
      Lower Round 3 / Semifinal (Sept 6):
        - LB_R3: T1 vs Winner(KT vs Dplus) -> Winner to Lower Final, Loser eliminated
      Lower Final (Sept 12):
        - LB_Final: Loser(Gen.G vs Hanwha) vs Winner(LB_R3) -> Winner to Grand Final, Loser 3rd
      Grand Final (Sept 13):
        - Grand_Final: Winner(Gen.G vs Hanwha) vs Winner(Lower Final)
    """
    teams = ["Gen.G", "Hanwha Life Esports", "T1", "KT Rolster", "Dplus", "BNK FearX"]

    matches: dict[str, BracketMatchNode] = {
        # Upper Round 1
        "UB_R1_M1": BracketMatchNode(
            id="UB_R1_M1",
            name="Upper Quarterfinal 1",
            round_name="Upper Round 1",
            bracket_section="upper",
            best_of=5,
            team1="KT Rolster",
            team2="Dplus",
            winner="KT Rolster",
            score1=3,
            score2=0,
            next_match_winner_id="UB_R2_M1",
            next_match_winner_slot=2,
            next_match_loser_id="LB_R1",
            next_match_loser_slot=1,
        ),
        "UB_R1_M2": BracketMatchNode(
            id="UB_R1_M2",
            name="Upper Quarterfinal 2",
            round_name="Upper Round 1",
            bracket_section="upper",
            best_of=5,
            team1="T1",
            team2="BNK FearX",
            winner="T1",
            score1=3,
            score2=2,
            next_match_winner_id="UB_R2_M2",
            next_match_winner_slot=2,
            next_match_loser_id="LB_R1",
            next_match_loser_slot=2,
        ),
        # Upper Round 2 (Semifinals)
        "UB_R2_M1": BracketMatchNode(
            id="UB_R2_M1",
            name="Upper Semifinal 1",
            round_name="Upper Round 2",
            bracket_section="upper",
            best_of=5,
            team1="Gen.G",
            team2="KT Rolster",
            winner="Gen.G",
            score1=3,
            score2=0,
            next_match_winner_id="UB_Final",
            next_match_winner_slot=1,
            next_match_loser_id="LB_R2",
            next_match_loser_slot=1,
        ),
        "UB_R2_M2": BracketMatchNode(
            id="UB_R2_M2",
            name="Upper Semifinal 2",
            round_name="Upper Round 2",
            bracket_section="upper",
            best_of=5,
            team1="Hanwha Life Esports",
            team2="T1",
            winner="Hanwha Life Esports",
            score1=3,
            score2=2,
            next_match_winner_id="UB_Final",
            next_match_winner_slot=2,
            next_match_loser_id="LB_R3",
            next_match_loser_slot=1,
        ),
        # Upper Final
        "UB_Final": BracketMatchNode(
            id="UB_Final",
            name="Upper Bracket Final",
            round_name="Upper Final",
            bracket_section="upper",
            best_of=5,
            team1="Gen.G",
            team2="Hanwha Life Esports",
            winner=None,
            next_match_winner_id="Grand_Final",
            next_match_winner_slot=1,
            next_match_loser_id="LB_Final",
            next_match_loser_slot=1,
        ),
        # Lower Round 1
        "LB_R1": BracketMatchNode(
            id="LB_R1",
            name="Lower Round 1",
            round_name="Lower Round 1",
            bracket_section="lower",
            best_of=5,
            team1="Dplus",
            team2="BNK FearX",
            winner="Dplus",
            score1=3,
            score2=2,
            next_match_winner_id="LB_R2",
            next_match_winner_slot=2,
        ),
        # Lower Round 2
        "LB_R2": BracketMatchNode(
            id="LB_R2",
            name="Lower Round 2 (Worlds Decider)",
            round_name="Lower Round 2",
            bracket_section="lower",
            best_of=5,
            team1="KT Rolster",
            team2="Dplus",
            winner=None,
            next_match_winner_id="LB_R3",
            next_match_winner_slot=2,
        ),
        # Lower Round 3 / Semifinal
        "LB_R3": BracketMatchNode(
            id="LB_R3",
            name="Lower Bracket Semifinal",
            round_name="Lower Round 3",
            bracket_section="lower",
            best_of=5,
            team1="T1",
            team2=None,
            next_match_winner_id="LB_Final",
            next_match_winner_slot=2,
        ),
        # Lower Final
        "LB_Final": BracketMatchNode(
            id="LB_Final",
            name="Lower Bracket Final",
            round_name="Lower Final",
            bracket_section="lower",
            best_of=5,
            team1=None,
            team2=None,
            next_match_winner_id="Grand_Final",
            next_match_winner_slot=2,
        ),
        # Grand Final
        "Grand_Final": BracketMatchNode(
            id="Grand_Final",
            name="Grand Final",
            round_name="Grand Final",
            bracket_section="final",
            best_of=5,
            team1=None,
            team2=None,
        ),
    }

    return TournamentBracket(
        id="lck_2026_playoffs",
        name="LCK 2026 Season - Playoffs",
        region="LCK",
        format="double_elimination",
        matches=matches,
        teams=teams,
    )


def get_lec_2026_summer_playoffs_bracket() -> TournamentBracket:
    """Construct the official 6-team LEC 2026 Summer Double Elimination Playoff bracket tree."""
    teams = ["Karmine Corp", "GIANTX", "G2 Esports", "Team Vitality", "Natus Vincere", "Movistar KOI"]

    matches: dict[str, BracketMatchNode] = {
        # Upper Semifinal 1
        "UB_SF1": BracketMatchNode(
            id="UB_SF1",
            name="Upper Semifinal 1",
            round_name="Upper Semifinals",
            bracket_section="upper",
            best_of=5,
            team1="Karmine Corp",
            team2="GIANTX",
            winner=None,
            next_match_winner_id="UB_Final",
            next_match_winner_slot=1,
            next_match_loser_id="LB_R1_M1",
            next_match_loser_slot=2,
        ),
        # Upper Semifinal 2
        "UB_SF2": BracketMatchNode(
            id="UB_SF2",
            name="Upper Semifinal 2",
            round_name="Upper Semifinals",
            bracket_section="upper",
            best_of=5,
            team1="G2 Esports",
            team2="Team Vitality",
            winner=None,
            next_match_winner_id="UB_Final",
            next_match_winner_slot=2,
            next_match_loser_id="LB_R1_M2",
            next_match_loser_slot=2,
        ),
        # Lower Round 1 - Match 1
        "LB_R1_M1": BracketMatchNode(
            id="LB_R1_M1",
            name="Lower Round 1 - Match 1",
            round_name="Lower Round 1",
            bracket_section="lower",
            best_of=5,
            team1="Natus Vincere",
            team2=None,  # Loser of KC vs GX
            next_match_winner_id="LB_SF",
            next_match_winner_slot=1,
        ),
        # Lower Round 1 - Match 2
        "LB_R1_M2": BracketMatchNode(
            id="LB_R1_M2",
            name="Lower Round 1 - Match 2",
            round_name="Lower Round 1",
            bracket_section="lower",
            best_of=5,
            team1="Movistar KOI",
            team2=None,  # Loser of G2 vs VIT
            next_match_winner_id="LB_SF",
            next_match_winner_slot=2,
        ),
        # Upper Final
        "UB_Final": BracketMatchNode(
            id="UB_Final",
            name="Upper Bracket Final",
            round_name="Upper Final",
            bracket_section="upper",
            best_of=5,
            team1=None,
            team2=None,
            next_match_winner_id="Grand_Final",
            next_match_winner_slot=1,
            next_match_loser_id="LB_Final",
            next_match_loser_slot=1,
        ),
        # Lower Semifinal
        "LB_SF": BracketMatchNode(
            id="LB_SF",
            name="Lower Bracket Semifinal",
            round_name="Lower Semifinal",
            bracket_section="lower",
            best_of=5,
            team1=None,
            team2=None,
            next_match_winner_id="LB_Final",
            next_match_winner_slot=2,
        ),
        # Lower Final
        "LB_Final": BracketMatchNode(
            id="LB_Final",
            name="Lower Bracket Final",
            round_name="Lower Final",
            bracket_section="lower",
            best_of=5,
            team1=None,
            team2=None,
            next_match_winner_id="Grand_Final",
            next_match_winner_slot=2,
        ),
        # Grand Final
        "Grand_Final": BracketMatchNode(
            id="Grand_Final",
            name="LEC Grand Final (Nice)",
            round_name="Grand Final",
            bracket_section="final",
            best_of=5,
            team1=None,
            team2=None,
        ),
    }

    return TournamentBracket(
        id="lec_2026_summer_playoffs",
        name="LEC 2026 Summer - Playoffs",
        region="LEC",
        format="double_elimination",
        matches=matches,
        teams=teams,
    )


def get_lpl_2026_split3_playoffs_bracket() -> TournamentBracket:
    """Construct the LPL 2026 Split 3 Playoff bracket tree."""
    teams = [
        "Bilibili Gaming",
        "Anyone's Legend",
        "LGD Gaming",
        "JD Gaming",
        "Ninjas in Pyjamas",
        "Top Esports",
    ]

    matches: dict[str, BracketMatchNode] = {
        # Upper Round 2
        "UB_R2_M1": BracketMatchNode(
            id="UB_R2_M1",
            name="Upper Round 2 - Match 1",
            round_name="Upper Round 2",
            bracket_section="upper",
            best_of=5,
            team1="Anyone's Legend",
            team2="LGD Gaming",
            winner=None,
            next_match_winner_id="UB_Final",
            next_match_winner_slot=1,
            next_match_loser_id="LB_R2_M1",
            next_match_loser_slot=1,
        ),
        "UB_R2_M2": BracketMatchNode(
            id="UB_R2_M2",
            name="Upper Round 2 - Match 2",
            round_name="Upper Round 2",
            bracket_section="upper",
            best_of=5,
            team1="Bilibili Gaming",
            team2="Top Esports",
            winner=None,
            next_match_winner_id="UB_Final",
            next_match_winner_slot=2,
            next_match_loser_id="LB_R2_M2",
            next_match_loser_slot=1,
        ),
        # Lower Round 1
        "LB_R1_M1": BracketMatchNode(
            id="LB_R1_M1",
            name="Lower Round 1",
            round_name="Lower Round 1",
            bracket_section="lower",
            best_of=5,
            team1="JD Gaming",
            team2="Ninjas in Pyjamas",
            winner=None,
            next_match_winner_id="LB_R2_M1",
            next_match_winner_slot=2,
        ),
        # Lower Round 2
        "LB_R2_M1": BracketMatchNode(
            id="LB_R2_M1",
            name="Lower Round 2",
            round_name="Lower Round 2",
            bracket_section="lower",
            best_of=5,
            team1=None,  # Loser of AL vs LGD
            team2=None,  # Winner of JDG vs NIP
            next_match_winner_id="LB_Final",
            next_match_winner_slot=2,
        ),
        "LB_R2_M2": BracketMatchNode(
            id="LB_R2_M2",
            name="Lower Round 2 - Match 2",
            round_name="Lower Round 2",
            bracket_section="lower",
            best_of=5,
            team1=None,  # Loser of BLG vs TES
            team2=None,
            next_match_winner_id="LB_Final",
            next_match_winner_slot=2,
        ),
        # Upper Final
        "UB_Final": BracketMatchNode(
            id="UB_Final",
            name="Upper Bracket Final",
            round_name="Upper Final",
            bracket_section="upper",
            best_of=5,
            team1=None,
            team2=None,
            next_match_winner_id="Grand_Final",
            next_match_winner_slot=1,
            next_match_loser_id="LB_Final",
            next_match_loser_slot=1,
        ),
        # Lower Final
        "LB_Final": BracketMatchNode(
            id="LB_Final",
            name="Lower Bracket Final",
            round_name="Lower Final",
            bracket_section="lower",
            best_of=5,
            team1=None,
            team2=None,
            next_match_winner_id="Grand_Final",
            next_match_winner_slot=2,
        ),
        # Grand Final
        "Grand_Final": BracketMatchNode(
            id="Grand_Final",
            name="LPL Grand Final (Shanghai)",
            round_name="Grand Final",
            bracket_section="final",
            best_of=5,
            team1=None,
            team2=None,
        ),
    }

    return TournamentBracket(
        id="lpl_2026_split3_playoffs",
        name="LPL 2026 Split 3 - Playoffs",
        region="LPL",
        format="double_elimination",
        matches=matches,
        teams=teams,
    )


SUPPORTED_BRACKETS = {
    "lck_2026_playoffs": get_lck_2026_playoffs_bracket,
    "lec_2026_summer_playoffs": get_lec_2026_summer_playoffs_bracket,
    "lpl_2026_split3_playoffs": get_lpl_2026_split3_playoffs_bracket,
}

class TournamentSimulator:
    """Monte Carlo tournament simulator powered by model win-rate estimations."""

    def __init__(self, team_ratings: dict[str, float] | None = None):
        self.team_ratings = team_ratings or self._load_team_ratings()
        self._prob_cache: dict[tuple[str, str, int], float] = {}
    @staticmethod
    def _load_team_ratings() -> dict[str, float]:
        ratings: dict[str, float] = {}
        try:
            with connect() as conn:
                rows = conn.execute(
                    """
                    SELECT normalized_entity_name, rating_value
                    FROM entity_ratings
                    WHERE entity_type = 'team' AND rating_system = 'gl'
                    ORDER BY id DESC
                    LIMIT 4000
                    """
                ).fetchall()
            for r in rows:
                key = canonical_team_key(str(r["normalized_entity_name"]))
                if key and key not in ratings and r.get("rating_value") is not None:
                    ratings[key] = float(r["rating_value"])
        except Exception as e:
            logger.warning("Could not load team ratings from DB: %s", e)
        return ratings

    def estimate_matchup_probability(self, team1: str, team2: str, best_of: int = 5) -> float:
        """Estimate win probability of team1 vs team2 in a BoN series."""
        cache_key = (team1, team2, best_of)
        if cache_key in self._prob_cache:
            return self._prob_cache[cache_key]

        k1 = canonical_team_key(team1)
        k2 = canonical_team_key(team2)
        r1 = self.team_ratings.get(k1, 1750.0)
        r2 = self.team_ratings.get(k2, 1750.0)
        # Bradley-Terry / Elo logistic map win probability.
        p_map = 1.0 / (1.0 + 10.0 ** (-(r1 - r2) / 400.0))

        # Brackets do not contain verified game-one side selection. Keep the
        # forecast side-neutral rather than inferring a priority from ratings.
        p_series = series_probability(p_map, best_of)
        self._prob_cache[cache_key] = p_series
        return p_series

    def estimate_score_distribution(self, team1: str, team2: str, best_of: int = 5) -> dict[str, float]:
        """Estimate exact series score distribution (e.g. 3-0, 3-1, 3-2) using Markov simulation."""
        k1 = canonical_team_key(team1)
        k2 = canonical_team_key(team2)
        r1 = self.team_ratings.get(k1, 1750.0)
        r2 = self.team_ratings.get(k2, 1750.0)
        p_map = 1.0 / (1.0 + 10.0 ** (-(r1 - r2) / 400.0))
        from betting_app.ml.models.markov_series import predict_score_distribution

        def predict(priority: bool) -> dict[str, float]:
            return predict_score_distribution(
                p_map,
                team_a_has_game1_priority=priority,
                best_of=best_of,
            )

        priority_a = predict(True)
        priority_b = predict(False)
        return {
            score: (float(priority_a.get(score, 0.0)) + float(priority_b.get(score, 0.0))) / 2.0
            for score in set(priority_a) | set(priority_b)
        }
    def simulate(
        self,
        bracket: TournamentBracket,
        n_simulations: int = 10000,
        manual_overrides: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Run Monte Carlo simulation of remaining tournament matches.

        manual_overrides: dict mapping match_id -> forced winner team name
        """
        manual = manual_overrides or {}
        championship_counts = {team: 0 for team in bracket.teams}
        top2_counts = {team: 0 for team in bracket.teams}
        top3_counts = {team: 0 for team in bracket.teams}
        top4_counts = {team: 0 for team in bracket.teams}

        # Dynamic topological sort of matches based on dependency
        def get_execution_order(matches: dict[str, BracketMatchNode]) -> list[str]:
            dependencies: dict[str, set[str]] = {m_id: set() for m_id in matches}
            for m_id, m in matches.items():
                if m.next_match_winner_id and m.next_match_winner_id in dependencies:
                    dependencies[m.next_match_winner_id].add(m_id)
                if m.next_match_loser_id and m.next_match_loser_id in dependencies:
                    dependencies[m.next_match_loser_id].add(m_id)

            order: list[str] = []
            visited: set[str] = set()

            while len(order) < len(matches):
                progress = False
                for m_id, deps in dependencies.items():
                    if m_id not in visited and deps.issubset(visited):
                        order.append(m_id)
                        visited.add(m_id)
                        progress = True
                if not progress:
                    # Cycle or disconnected node, append remaining
                    for m_id in matches:
                        if m_id not in visited:
                            order.append(m_id)
                            visited.add(m_id)
                    break
            return order

        execution_order = get_execution_order(bracket.matches)
        for _ in range(n_simulations):
            # Clone match states
            state = {
                m_id: {
                    "team1": m.team1,
                    "team2": m.team2,
                    "winner": m.winner,
                }
                for m_id, m in bracket.matches.items()
            }

            for m_id in execution_order:
                m_def = bracket.matches[m_id]
                curr = state[m_id]

                t1 = curr["team1"]
                t2 = curr["team2"]

                # For early rounds or bye-matches, if only one team is present and it's a seed
                if t1 and not t2 and not m_def.next_match_loser_id and m_id != "Grand_Final":
                    # Auto-advance
                    curr["winner"] = t1

                winner = curr["winner"]
                if not winner and t1 and t2:
                    if m_id in manual:
                        winner = manual[m_id]
                    else:
                        p_t1 = self.estimate_matchup_probability(t1, t2, m_def.best_of)
                        winner = t1 if random.random() < p_t1 else t2
                    curr["winner"] = winner

                if winner:
                    loser = t2 if winner == t1 else t1

                    # Advance winner
                    if m_def.next_match_winner_id:
                        target_m = state[m_def.next_match_winner_id]
                        if m_def.next_match_winner_slot == 1:
                            target_m["team1"] = winner
                        else:
                            target_m["team2"] = winner

                    # Advance loser
                    if m_def.next_match_loser_id and loser:
                        target_m = state[m_def.next_match_loser_id]
                        if m_def.next_match_loser_slot == 1:
                            target_m["team1"] = loser
                        else:
                            target_m["team2"] = loser
            gf = state.get("Grand_Final")
            champ = gf.get("winner") if gf else None
            runner_up = (gf.get("team2") if champ == gf.get("team1") else gf.get("team1")) if gf else None

            lb_fin = state.get("LB_Final")
            third = (lb_fin.get("team2") if lb_fin.get("winner") == lb_fin.get("team1") else lb_fin.get("team1")) if lb_fin else None

            lb_semi = state.get("LB_R3") or state.get("LB_SF") or state.get("LB_R3_M1")
            fourth = (lb_semi.get("team2") if lb_semi.get("winner") == lb_semi.get("team1") else lb_semi.get("team1")) if lb_semi else None
            if champ and champ in championship_counts:
                championship_counts[champ] += 1
            if runner_up and runner_up in top2_counts:
                top2_counts[runner_up] += 1
            if third and third in top3_counts:
                top3_counts[third] += 1
            if fourth and fourth in top4_counts:
                top4_counts[fourth] += 1

        results = []
        for team in bracket.teams:
            champ_p = championship_counts[team] / n_simulations
            top2_p = (championship_counts[team] + top2_counts[team]) / n_simulations
            top3_p = (championship_counts[team] + top2_counts[team] + top3_counts[team]) / n_simulations
            top4_p = (championship_counts[team] + top2_counts[team] + top3_counts[team] + top4_counts[team]) / n_simulations
            results.append(
                {
                    "team": team,
                    "champion_prob": round(champ_p, 4),
                    "top2_prob": round(top2_p, 4),
                    "top3_prob": round(top3_p, 4),
                    "top4_prob": round(top4_p, 4),
                }
            )

        results.sort(key=lambda x: x["champion_prob"], reverse=True)

        return {
            "tournament_id": bracket.id,
            "tournament_name": bracket.name,
            "simulations": n_simulations,
            "standings": results,
            "bracket": {
                m_id: {
                    "id": m.id,
                    "name": m.name,
                    "round_name": m.round_name,
                    "bracket_section": m.bracket_section,
                    "best_of": m.best_of,
                    "team1": m.team1,
                    "team2": m.team2,
                    "winner": m.winner,
                    "score1": m.score1,
                    "score2": m.score2,
                }
                for m_id, m in bracket.matches.items()
            },
        }

@dataclass(frozen=True)
class WorldsTeam:
    """A manually configured Worlds participant and its Swiss draw metadata."""

    name: str
    region: str
    pool: int | None = None


class WorldsSimulator(TournamentSimulator):
    """Monte Carlo simulator for a user-configured Play-In, Swiss, and knockout Worlds."""

    def simulate_series_winner(self, team1: str, team2: str, best_of: int) -> str:
        """Simulate one series and return its winner."""
        probability = self.estimate_matchup_probability(team1, team2, best_of=best_of)
        return team1 if random.random() < probability else team2

    def simulate_play_in(self, teams: Sequence[WorldsTeam]) -> str:
        """Simulate a four-team double-elimination Bo5 Play-In with one Swiss qualifier."""
        bracket = list(teams)
        random.shuffle(bracket)

        upper_winner_1 = self.simulate_series_winner(bracket[0].name, bracket[1].name, best_of=5)
        upper_loser_1 = bracket[1].name if upper_winner_1 == bracket[0].name else bracket[0].name
        upper_winner_2 = self.simulate_series_winner(bracket[2].name, bracket[3].name, best_of=5)
        upper_loser_2 = bracket[3].name if upper_winner_2 == bracket[2].name else bracket[2].name

        lower_round_winner = self.simulate_series_winner(upper_loser_1, upper_loser_2, best_of=5)
        upper_final_winner = self.simulate_series_winner(upper_winner_1, upper_winner_2, best_of=5)
        upper_final_loser = upper_winner_2 if upper_final_winner == upper_winner_1 else upper_winner_1
        lower_final_winner = self.simulate_series_winner(
            lower_round_winner,
            upper_final_loser,
            best_of=5,
        )
        return self.simulate_series_winner(upper_final_winner, lower_final_winner, best_of=5)

    def simulate_swiss_round(
        self,
        pool: Sequence[str],
        best_of: int,
        played_pairs: set[frozenset[str]],
    ) -> tuple[list[str], list[str]]:
        """Pair a Swiss record bucket, avoiding prior pairings where the bucket permits it."""
        shuffled = list(pool)
        for _ in range(32):
            random.shuffle(shuffled)
            if all(
                frozenset((shuffled[index], shuffled[index + 1])) not in played_pairs
                for index in range(0, len(shuffled) - 1, 2)
            ):
                break

        winners: list[str] = []
        losers: list[str] = []
        for index in range(0, len(shuffled) - 1, 2):
            team1, team2 = shuffled[index], shuffled[index + 1]
            winner = self.simulate_series_winner(team1, team2, best_of)
            loser = team2 if winner == team1 else team1
            played_pairs.add(frozenset((team1, team2)))
            winners.append(winner)
            losers.append(loser)
        return winners, losers

    @staticmethod
    def validate_participants(
        direct_teams: Sequence[WorldsTeam],
        play_in_teams: Sequence[WorldsTeam],
        play_in_winner_pool: int,
    ) -> None:
        """Validate the fixed 15 direct + 4 Play-In participant contract."""
        if len(direct_teams) != 15:
            raise ValueError("Worlds requires exactly 15 direct Swiss participants.")
        if len(play_in_teams) != 4:
            raise ValueError("Worlds requires exactly 4 Play-In participants.")
        if play_in_winner_pool not in {1, 2, 3, 4}:
            raise ValueError("The Play-In qualifier must be assigned to Swiss pool 1, 2, 3, or 4.")

        all_teams = [*direct_teams, *play_in_teams]
        team_keys = [canonical_team_key(team.name) for team in all_teams]
        if any(not key for key in team_keys):
            raise ValueError("Every Worlds participant requires a team name.")
        if len(set(team_keys)) != len(team_keys):
            raise ValueError("A team cannot occupy more than one Worlds slot.")
        if any(not team.region.strip() for team in all_teams):
            raise ValueError("Every Worlds participant requires a region.")
        if any(team.pool not in {1, 2, 3, 4} for team in direct_teams):
            raise ValueError("Every direct Swiss participant requires pool 1, 2, 3, or 4.")

        pool_counts = {pool: sum(team.pool == pool for team in direct_teams) for pool in range(1, 5)}
        if pool_counts[play_in_winner_pool] != 3 or any(
            count != 4 for pool, count in pool_counts.items() if pool != play_in_winner_pool
        ):
            raise ValueError(
                "Direct Swiss slots must fill three pools with four teams and the Play-In pool with three."
            )

    def simulate_worlds(
        self,
        direct_teams: Sequence[WorldsTeam],
        play_in_teams: Sequence[WorldsTeam],
        play_in_winner_pool: int,
        n_simulations: int = 5000,
    ) -> dict[str, Any]:
        """Simulate a manually configured Worlds from Play-In through the Bo5 final."""
        self.validate_participants(direct_teams, play_in_teams, play_in_winner_pool)

        all_teams = [*direct_teams, *play_in_teams]
        direct_names = [team.name for team in direct_teams]
        qualifier_counts = {team.name: 0 for team in all_teams}
        swiss_advance_counts = {team.name: 0 for team in all_teams}
        knockout_top4_counts = {team.name: 0 for team in all_teams}
        knockout_top2_counts = {team.name: 0 for team in all_teams}
        champion_counts = {team.name: 0 for team in all_teams}
        metadata = {team.name: team for team in all_teams}

        for direct_team in direct_teams:
            qualifier_counts[direct_team.name] = n_simulations

        for _ in range(n_simulations):
            play_in_qualifier = self.simulate_play_in(play_in_teams)
            qualifier_counts[play_in_qualifier] += 1
            qualifier_metadata = metadata[play_in_qualifier]
            participant_teams = [
                *direct_teams,
                WorldsTeam(
                    name=play_in_qualifier,
                    region=qualifier_metadata.region,
                    pool=play_in_winner_pool,
                ),
            ]
            records = {team.name: [0, 0] for team in participant_teams}
            played_pairs: set[frozenset[str]] = set()
            advanced_teams: list[str] = []
            next_buckets: dict[tuple[int, int], list[str]] = {}

            first_round_pools = {
                pool: [team.name for team in participant_teams if team.pool == pool]
                for pool in range(1, 5)
            }
            for higher_pool, lower_pool in ((1, 4), (2, 3)):
                random.shuffle(first_round_pools[higher_pool])
                random.shuffle(first_round_pools[lower_pool])
                for team1, team2 in zip(
                    first_round_pools[higher_pool],
                    first_round_pools[lower_pool],
                    strict=True,
                ):
                    winner = self.simulate_series_winner(team1, team2, best_of=1)
                    loser = team2 if winner == team1 else team1
                    played_pairs.add(frozenset((team1, team2)))
                    records[winner][0] += 1
                    records[loser][1] += 1
                    next_buckets.setdefault((1, 0), []).append(winner)
                    next_buckets.setdefault((0, 1), []).append(loser)

            buckets = next_buckets
            for _round_number in range(2, 6):
                next_buckets = {}
                for (wins, losses), pool in buckets.items():
                    best_of = 3 if wins == 2 or losses == 2 else 1
                    winners, losers = self.simulate_swiss_round(pool, best_of, played_pairs)
                    for winner in winners:
                        records[winner][0] += 1
                        new_wins, new_losses = records[winner]
                        if new_wins == 3:
                            advanced_teams.append(winner)
                        else:
                            next_buckets.setdefault((new_wins, new_losses), []).append(winner)
                    for loser in losers:
                        records[loser][1] += 1
                        new_wins, new_losses = records[loser]
                        if new_losses < 3:
                            next_buckets.setdefault((new_wins, new_losses), []).append(loser)
                buckets = next_buckets
                if len(advanced_teams) == 8:
                    break

            for team in advanced_teams:
                swiss_advance_counts[team] += 1

            random.shuffle(advanced_teams)
            quarterfinal_winners = [
                self.simulate_series_winner(advanced_teams[index], advanced_teams[index + 1], best_of=5)
                for index in range(0, 8, 2)
            ]
            for team in quarterfinal_winners:
                knockout_top4_counts[team] += 1

            semifinal_winners = [
                self.simulate_series_winner(
                    quarterfinal_winners[index],
                    quarterfinal_winners[index + 1],
                    best_of=5,
                )
                for index in range(0, 4, 2)
            ]
            for team in semifinal_winners:
                knockout_top2_counts[team] += 1
            champion_counts[
                self.simulate_series_winner(semifinal_winners[0], semifinal_winners[1], best_of=5)
            ] += 1

        standings = []
        for team in all_teams:
            standings.append(
                {
                    "team": team.name,
                    "region": team.region,
                    "stage": "direct_swiss" if team.name in direct_names else "play_in",
                    "pool": team.pool if team.name in direct_names else None,
                    "play_in_qualifier_prob": round(qualifier_counts[team.name] / n_simulations, 4),
                    "champion_prob": round(champion_counts[team.name] / n_simulations, 4),
                    "top2_prob": round(knockout_top2_counts[team.name] / n_simulations, 4),
                    "top4_prob": round(knockout_top4_counts[team.name] / n_simulations, 4),
                    "top8_swiss_prob": round(swiss_advance_counts[team.name] / n_simulations, 4),
                }
            )

        standings.sort(key=lambda standing: standing["champion_prob"], reverse=True)
        return {
            "tournament_id": "worlds_2026",
            "tournament_name": "League of Legends World Championship 2026",
            "format": "play_in_double_elimination_bo5_swiss_and_knockout",
            "simulations": n_simulations,
            "teams": [team.name for team in all_teams],
            "direct_teams": [
                {"team": team.name, "region": team.region, "pool": team.pool} for team in direct_teams
            ],
            "play_in_teams": [{"team": team.name, "region": team.region} for team in play_in_teams],
            "play_in_winner_pool": play_in_winner_pool,
            "standings": standings,
        }
