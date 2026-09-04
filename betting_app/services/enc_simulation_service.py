"""ENC 2027 roster selection and published-format Monte Carlo simulation."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from betting_app.core.db import get_session
from betting_app.services.enc_rosters import (
    ENC_PARTICIPANTS,
    ENC_PUBLISHED_ROLE_PLAYERS,
    ENC_ROSTER_SOURCE_URL,
)
from betting_app.services.rating_contract import OPERATIONAL_RATINGS_VERSION
from betting_app.services.upcoming_inference_service import series_probability

STANDARD_ROLES = ("TOP", "JUNGLE", "MID", "ADC", "SUPPORT")
DEFAULT_PLAYER_RATING = 1500.0

# Leaguepedia names that resolve to more than one current player-rating entity.
# These ids identify the player linked from the published national roster.
ROSTER_PLAYER_IDS = {
    "Knight": "1270",
    "Kaze": "5009",
    "Lost": "1123",
    "Neo": "1126",
}


@dataclass(frozen=True)
class EncTeam:
    nation: str
    entry_stage: str
    roster_rating: float


class EncConfigurationError(ValueError):
    """The published participant list cannot yet produce a valid simulation."""


def _rating_snapshot(session: Session) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    run = session.execute(
        text(
            """
            SELECT ratings_version, data_cutoff_at
            FROM rating_runs
            WHERE status = 'completed'
            ORDER BY
                CASE WHEN ratings_version = :operational_version THEN 0 ELSE 1 END,
                finished_at DESC NULLS LAST,
                id DESC
            LIMIT 1
            """
        ),
        {"operational_version": OPERATIONAL_RATINGS_VERSION},
    ).mappings().first()
    if run is None:
        return None, []

    rows = session.execute(
        text(
            """
            SELECT entity_name, normalized_entity_name, role, rating_value, games_played
            FROM entity_ratings
            WHERE ratings_version = :ratings_version
              AND entity_type = 'player'
              AND rating_system = 'gl'
              AND rating_value IS NOT NULL
            """
        ),
        {"ratings_version": run["ratings_version"]},
    ).mappings().all()
    return dict(run), [dict(row) for row in rows]


def _select_lineup(
    nation: str,
    ratings_by_name: Mapping[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[str]]:
    role_players = ENC_PUBLISHED_ROLE_PLAYERS.get(nation, {})
    selected: list[dict[str, Any]] = []
    missing_roles: list[str] = []
    for role in STANDARD_ROLES:
        eligible_players = role_players.get(role, ())
        if not eligible_players:
            missing_roles.append(role)
            continue

        candidates: list[dict[str, Any]] = []
        for player_name in eligible_players:
            candidate_id = ROSTER_PLAYER_IDS.get(player_name)
            for row in ratings_by_name.get(player_name.casefold(), []):
                if candidate_id and str(row["normalized_entity_name"]) != candidate_id:
                    continue
                candidates.append(dict(row))

        if candidates:
            best = max(candidates, key=lambda item: float(item["rating_value"]))
            selected.append(
                {
                    "role": role,
                    "player": best["entity_name"],
                    "normalized_player_id": str(best["normalized_entity_name"]),
                    "rating": round(float(best["rating_value"]), 1),
                    "games_played": int(best.get("games_played") or 0),
                    "rating_source": "gl",
                }
            )
            continue

        default_player = eligible_players[0]
        selected.append(
            {
                "role": role,
                "player": default_player,
                "normalized_player_id": f"default:{nation.casefold()}:{role.casefold()}",
                "rating": DEFAULT_PLAYER_RATING,
                "games_played": 0,
                "rating_source": "default",
            }
        )
    return selected, missing_roles


def build_enc_configuration(
    *,
    session: Session | None = None,
    rating_run: Mapping[str, Any] | None = None,
    rating_rows: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Select the highest current GL rating in each Fandom-designated ENC role.

    A published player with no current GL row receives the explicit 1500.0
    default. The UI marks this separately from a stored rating.
    """
    if rating_rows is None:
        if session is None:
            with get_session() as owned_session:
                return build_enc_configuration(session=owned_session)
        loaded_run, loaded_rows = _rating_snapshot(session)
        rating_run, rating_rows = loaded_run, loaded_rows

    if rating_run is None:
        return {
            "tournament_id": "enc_2027",
            "tournament_name": "Esports Nations Cup 2027",
            "source_url": ENC_ROSTER_SOURCE_URL,
            "format": enc_format(),
            "ratings_version": None,
            "data_cutoff_at": None,
            "default_rating": DEFAULT_PLAYER_RATING,
            "default_rating_policy": "Published player without a current GL row",
            "teams": [],
            "simulation_ready": False,
            "blocking_issues": ["Brak ukończonego snapshotu rankingów GL."],
        }

    ratings_by_name: dict[str, list[dict[str, Any]]] = {}
    for row in rating_rows:
        name = str(row.get("entity_name") or "")
        if name:
            ratings_by_name.setdefault(name.casefold(), []).append(dict(row))

    teams: list[dict[str, Any]] = []
    incomplete_nations: list[str] = []
    for participant in ENC_PARTICIPANTS:
        selected, missing_roles = _select_lineup(participant["nation"], ratings_by_name)
        ready = not missing_roles
        if not ready:
            incomplete_nations.append(participant["nation"])
        teams.append(
            {
                "nation": participant["nation"],
                "entry_stage": participant["entry_stage"],
                "ranking": participant["ranking"],
                "source_roster": list(participant["players"]),
                "selected_roster": selected,
                "missing_roles": missing_roles,
                "selection_status": "ready" if ready else "incomplete",
                "roster_rating": round(sum(player["rating"] for player in selected) / len(selected), 1)
                if ready
                else None,
            }
        )

    default_solidarity_roster = [
        {
            "role": role,
            "player": f"Solidarity Slot — {role}",
            "normalized_player_id": f"default:solidarity:{role.casefold()}",
            "rating": DEFAULT_PLAYER_RATING,
            "games_played": 0,
            "rating_source": "default",
        }
        for role in STANDARD_ROLES
    ]
    teams.append(
        {
            "nation": "Solidarity Slot",
            "entry_stage": "play_in",
            "ranking": None,
            "source_roster": [],
            "selected_roster": default_solidarity_roster,
            "missing_roles": [],
            "selection_status": "defaulted",
            "roster_rating": DEFAULT_PLAYER_RATING,
        }
    )
    issues: list[str] = []
    if incomplete_nations:
        issues.append(
            "Brak przypisanej roli w ogłoszonej kadrze dla: "
            + ", ".join(incomplete_nations)
            + "."
        )
    return {
        "tournament_id": "enc_2027",
        "tournament_name": "Esports Nations Cup 2027",
        "source_url": ENC_ROSTER_SOURCE_URL,
        "format": enc_format(),
        "ratings_version": str(rating_run["ratings_version"]),
        "data_cutoff_at": str(rating_run["data_cutoff_at"]),
        "default_rating": DEFAULT_PLAYER_RATING,
        "default_rating_policy": "Published player without a current GL row",
        "teams": teams,
        "simulation_ready": not issues,
        "blocking_issues": issues,
    }


def enc_format() -> dict[str, Any]:
    """The published structure; draw and tie-break procedures remain unannounced."""
    return {
        "participants": 32,
        "invited": 16,
        "direct_group_stage": 8,
        "online_qualifiers": 14,
        "wildcards": ["Solidarity Slot", "Host GCC"],
        "play_in": "24 teams, 4 groups of 6, double round robin Bo1; top 2 advance",
        "group_stage": "16 teams, 4 groups of 4, single round robin Bo3; top 2 advance",
        "playoffs": "single elimination; quarterfinals and semifinals Bo3, final Bo5",
        "draw_and_tiebreak_policy": "Group draws, playoff bracket draws, and tied group positions are shuffled uniformly because the published page does not specify them.",
    }


class EncSimulator:
    """Simulate the exact published ENC stages from verified five-player ratings."""

    def __init__(self, teams: Sequence[EncTeam]):
        self.teams = tuple(teams)
        self._ratings = {team.nation: team.roster_rating for team in teams}
        self._validate_participants()

    @classmethod
    def from_configuration(cls, configuration: Mapping[str, Any]) -> "EncSimulator":
        if not configuration.get("simulation_ready"):
            issues = "; ".join(str(issue) for issue in configuration.get("blocking_issues", []))
            raise EncConfigurationError(issues or "Konfiguracja ENC nie jest kompletna.")
        return cls(
            [
                EncTeam(
                    nation=str(team["nation"]),
                    entry_stage=str(team["entry_stage"]),
                    roster_rating=float(team["roster_rating"]),
                )
                for team in configuration["teams"]
            ]
        )

    def _validate_participants(self) -> None:
        if len(self.teams) != 32:
            raise ValueError("ENC requires exactly 32 national teams.")
        if len({team.nation for team in self.teams}) != 32:
            raise ValueError("Each ENC nation must occupy exactly one slot.")
        direct = [team for team in self.teams if team.entry_stage == "group_stage"]
        play_in = [team for team in self.teams if team.entry_stage == "play_in"]
        if len(direct) != 8 or len(play_in) != 24:
            raise ValueError("ENC requires 8 direct Group Stage teams and 24 Play-In teams.")

    def _winner(self, nation_a: str, nation_b: str, best_of: int) -> str:
        rating_diff = self._ratings[nation_a] - self._ratings[nation_b]
        game_probability = 1.0 / (1.0 + 10.0 ** (-rating_diff / 400.0))
        probability = series_probability(game_probability, best_of)
        return nation_a if random.random() < probability else nation_b

    def _rank_group(self, teams: Sequence[str], *, best_of: int, repeat: int) -> list[str]:
        wins = {team: 0 for team in teams}
        for _ in range(repeat):
            for index, nation_a in enumerate(teams):
                for nation_b in teams[index + 1 :]:
                    wins[self._winner(nation_a, nation_b, best_of)] += 1
        shuffled = list(teams)
        random.shuffle(shuffled)
        return sorted(shuffled, key=lambda nation: wins[nation], reverse=True)

    def simulate(self, n_simulations: int) -> dict[str, Any]:
        direct = [team.nation for team in self.teams if team.entry_stage == "group_stage"]
        play_in = [team.nation for team in self.teams if team.entry_stage == "play_in"]
        group_stage_counts = {team.nation: n_simulations if team.nation in direct else 0 for team in self.teams}
        playoff_counts = {team.nation: 0 for team in self.teams}
        top4_counts = {team.nation: 0 for team in self.teams}
        top2_counts = {team.nation: 0 for team in self.teams}
        champion_counts = {team.nation: 0 for team in self.teams}

        for _ in range(n_simulations):
            shuffled_play_in = play_in[:]
            random.shuffle(shuffled_play_in)
            play_in_advancers: list[str] = []
            for index in range(0, 24, 6):
                play_in_advancers.extend(
                    self._rank_group(shuffled_play_in[index : index + 6], best_of=1, repeat=2)[:2]
                )
            for nation in play_in_advancers:
                group_stage_counts[nation] += 1

            group_stage_teams = [*direct, *play_in_advancers]
            random.shuffle(group_stage_teams)
            playoff_teams: list[str] = []
            for index in range(0, 16, 4):
                playoff_teams.extend(
                    self._rank_group(group_stage_teams[index : index + 4], best_of=3, repeat=1)[:2]
                )
            for nation in playoff_teams:
                playoff_counts[nation] += 1

            random.shuffle(playoff_teams)
            semifinalists = [
                self._winner(playoff_teams[index], playoff_teams[index + 1], best_of=3)
                for index in range(0, 8, 2)
            ]
            for nation in semifinalists:
                top4_counts[nation] += 1
            finalists = [
                self._winner(semifinalists[index], semifinalists[index + 1], best_of=3)
                for index in range(0, 4, 2)
            ]
            for nation in finalists:
                top2_counts[nation] += 1
            champion_counts[self._winner(finalists[0], finalists[1], best_of=5)] += 1

        standings = [
            {
                "nation": team.nation,
                "entry_stage": team.entry_stage,
                "roster_rating": round(team.roster_rating, 1),
                "group_stage_prob": round(group_stage_counts[team.nation] / n_simulations, 4),
                "playoff_prob": round(playoff_counts[team.nation] / n_simulations, 4),
                "top4_prob": round(top4_counts[team.nation] / n_simulations, 4),
                "top2_prob": round(top2_counts[team.nation] / n_simulations, 4),
                "champion_prob": round(champion_counts[team.nation] / n_simulations, 4),
            }
            for team in self.teams
        ]
        standings.sort(key=lambda team: team["champion_prob"], reverse=True)
        return {
            "tournament_id": "enc_2027",
            "tournament_name": "Esports Nations Cup 2027",
            "format": enc_format(),
            "simulations": n_simulations,
            "standings": standings,
        }
