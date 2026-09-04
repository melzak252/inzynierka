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
    """Construct the official 6-team LCK Double Elimination Playoff bracket tree."""
    teams = ["Gen.G", "Hanwha Life Esports", "T1", "KT Rolster", "Dplus", "BNK FearX"]
    
    matches: dict[str, BracketMatchNode] = {
        # Upper Round 1
        "UB_R1_M1": BracketMatchNode(
            id="UB_R1_M1",
            name="Upper Round 1 - Match 1",
            round_name="Upper Round 1",
            bracket_section="upper",
            best_of=5,
            team1="KT Rolster",
            team2="Dplus",
            winner=None,  # In progress / upcoming
            next_match_winner_id="UB_R2_M1",
            next_match_winner_slot=2,
            next_match_loser_id="LB_R1_M1",
            next_match_loser_slot=1,
        ),
        "UB_R1_M2": BracketMatchNode(
            id="UB_R1_M2",
            name="Upper Round 1 - Match 2",
            round_name="Upper Round 1",
            bracket_section="upper",
            best_of=5,
            team1="T1",
            team2="BNK FearX",
            winner="T1",  # Completed 3:1
            score1=3,
            score2=1,
            next_match_winner_id="UB_R2_M2",
            next_match_winner_slot=2,
            next_match_loser_id="LB_R1_M1",
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
            team2=None,  # Winner of UB_R1_M1
            next_match_winner_id="UB_Final",
            next_match_winner_slot=1,
            next_match_loser_id="LB_R2_M1",
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
            team1=None,  # Loser of UB_R1_M1
            team2="BNK FearX",  # Loser of UB_R1_M2
            next_match_winner_id="LB_R2_M2",
            next_match_winner_slot=2,
        ),
        # Lower Round 2 (Quarterfinals)
        "LB_R2_M1": BracketMatchNode(
            id="LB_R2_M1",
            name="Lower Round 2 - Match 1",
            round_name="Lower Round 2",
            bracket_section="lower",
            best_of=5,
            team1=None,  # Loser of UB_R2_M1
            team2=None,
            next_match_winner_id="LB_R3_M1",
            next_match_winner_slot=1,
        ),
        "LB_R2_M2": BracketMatchNode(
            id="LB_R2_M2",
            name="Lower Round 2 - Match 2",
            round_name="Lower Round 2",
            bracket_section="lower",
            best_of=5,
            team1=None,  # Loser of UB_R2_M2
            team2=None,  # Winner of LB_R1_M1
            next_match_winner_id="LB_R3_M1",
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
        # Lower Round 3 (Semifinal)
        "LB_R3_M1": BracketMatchNode(
            id="LB_R3_M1",
            name="Lower Bracket Semifinal",
            round_name="Lower Round 3",
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


class TournamentSimulator:
    """Monte Carlo tournament simulator powered by model win-rate estimations."""

    def __init__(self, team_ratings: dict[str, float] | None = None):
        self.team_ratings = team_ratings or self._load_team_ratings()

    @staticmethod
    def _load_team_ratings() -> dict[str, float]:
        """Load Glicko-2 ratings for teams from entity_ratings, fallback to 1750."""
        ratings: dict[str, float] = {}
        try:
            with connect() as conn:
                rows = conn.execute(
                    """
                    SELECT normalized_entity_name, rating_value
                    FROM entity_ratings
                    WHERE entity_type = 'team' AND rating_system = 'glicko2'
                    ORDER BY id DESC
                    LIMIT 2000
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
        k1 = canonical_team_key(team1)
        k2 = canonical_team_key(team2)
        r1 = self.team_ratings.get(k1, 1750.0)
        r2 = self.team_ratings.get(k2, 1750.0)

        # Bradley-Terry / Elo logistic map win probability
        diff = r1 - r2
        p_map = 1.0 / (1.0 + 10.0 ** (-diff / 400.0))
        # Series projection
        p_series = series_probability(p_map, best_of)
        return p_series

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

        # Topological evaluation order of matches
        execution_order = [
            "UB_R1_M1", "UB_R1_M2",
            "UB_R2_M1", "UB_R2_M2",
            "LB_R1_M1",
            "LB_R2_M1", "LB_R2_M2",
            "UB_Final",
            "LB_R3_M1",
            "LB_Final",
            "Grand_Final",
        ]

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
            gf = state["Grand_Final"]
            champ = gf.get("winner")
            runner_up = gf.get("team2") if champ == gf.get("team1") else gf.get("team1")

            lb_fin = state["LB_Final"]
            third = lb_fin.get("team2") if lb_fin.get("winner") == lb_fin.get("team1") else lb_fin.get("team1")

            lb_r3 = state["LB_R3_M1"]
            fourth = lb_r3.get("team2") if lb_r3.get("winner") == lb_r3.get("team1") else lb_r3.get("team1")

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
