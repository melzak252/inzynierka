"""Daily-batched Glicko-2 ratings calibrated across competition families.

Player skill and competition location are deliberately separate.  Player
updates use game-level evidence, while the Gaussian family/tier bridge uses at
most one match-level result for an event.  A whole calendar day is evaluated
against one frozen prior and committed atomically, so input ordering cannot
leak information between same-day matches.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from src.models.competition_tiers import CompetitionTier, _RULES
from src.ratings.glicko2_core import (
    Glicko2Observation,
    Glicko2State,
    expected_score,
    inflate,
    update,
)

_RATING_SCALE = math.log(10.0) / 400.0
_KNOWN_TIERS = frozenset(
    tier.value for tier in CompetitionTier if tier is not CompetitionTier.UNKNOWN
)
_KNOWN_FAMILIES = frozenset(rule.identity.family for rule in _RULES)


@dataclass(frozen=True, slots=True)
class RatingEvent:
    """One completed match and its game results, from side A's perspective."""

    event_id: str
    event_date: date
    team_a_id: str
    team_b_id: str
    players_a: Sequence[str]
    players_b: Sequence[str]
    family_a: str
    family_b: str
    tier_a: str
    tier_b: str
    scores: Sequence[int]


@dataclass(frozen=True, slots=True)
class GaussianOffsetState:
    """One independently approximated Gaussian location component."""

    mean: float
    variance: float
    last_bridge_date: date | None = None

    @property
    def deviation(self) -> float:
        return math.sqrt(self.variance)


@dataclass(frozen=True, slots=True)
class PlayerRanking:
    """Raw player skill and its location-adjusted ranking representation."""

    player_id: str
    raw_rating: float
    raw_rd: float
    rating: float
    rd: float
    volatility: float
    family: str
    tier: str
    last_activity: date | None
    games_played: int


class FamilyCalibratedGlicko2:
    """Versionable player rating engine with family and tier calibration."""

    STATE_VERSION = 1

    def __init__(
        self,
        *,
        tau: float = 0.5,
        convergence_tolerance: float = 1e-6,
        rating_period_days: float = 30.0,
        initial_family_deviation: float = 150.0,
        initial_tier_deviation: float = 100.0,
        bridge_process_deviation: float = 1.0,
    ) -> None:
        if tau <= 0.0:
            raise ValueError("tau must be positive")
        if convergence_tolerance <= 0.0:
            raise ValueError("convergence_tolerance must be positive")
        if rating_period_days <= 0.0:
            raise ValueError("rating_period_days must be positive")
        if initial_family_deviation < 0.0 or initial_tier_deviation < 0.0:
            raise ValueError("initial offset deviations cannot be negative")
        if bridge_process_deviation < 0.0:
            raise ValueError("bridge_process_deviation cannot be negative")

        self.tau = float(tau)
        self.convergence_tolerance = float(convergence_tolerance)
        self.rating_period_days = float(rating_period_days)
        self.initial_family_deviation = float(initial_family_deviation)
        self.initial_tier_deviation = float(initial_tier_deviation)
        self.bridge_process_deviation = float(bridge_process_deviation)

        self._player_states: dict[str, Glicko2State] = {}
        self._player_affiliations: dict[str, tuple[str, str]] = {}
        self._player_last_activity: dict[str, date] = {}
        self._player_games: dict[str, int] = {}
        self._family_states: dict[str, GaussianOffsetState] = {}
        self._tier_states: dict[str, GaussianOffsetState] = {}
        self._family_tiers: dict[str, str] = {}
        self._current_date: date | None = None

    @property
    def current_date(self) -> date | None:
        return self._current_date

    @property
    def player_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._player_states))

    @property
    def family_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._family_states))

    @property
    def tier_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._tier_states))

    def get_player_state(self, player_id: str) -> Glicko2State:
        return self._player_states[player_id]

    def get_family_state(self, family: str) -> GaussianOffsetState:
        return self._family_states[family]

    def get_tier_state(self, tier: str) -> GaussianOffsetState:
        return self._tier_states[tier]

    def get_player_affiliation(self, player_id: str) -> tuple[str, str] | None:
        return self._player_affiliations.get(player_id)

    def get_player_last_activity(self, player_id: str) -> date | None:
        return self._player_last_activity.get(player_id)

    def get_player_games(self, player_id: str) -> int:
        return self._player_games.get(player_id, 0)

    def get_family_location(self, family: str, tier: str) -> GaussianOffsetState:
        family, tier = self._validate_affiliation(family, tier, "location")
        if family == "unknown":
            return self._unknown_location()
        family_state = self._family_states[family]
        tier_state = self._tier_states[tier]
        bridge_dates = tuple(
            value
            for value in (family_state.last_bridge_date, tier_state.last_bridge_date)
            if value is not None
        )
        return GaussianOffsetState(
            mean=family_state.mean + tier_state.mean,
            variance=family_state.variance + tier_state.variance,
            last_bridge_date=max(bridge_dates) if bridge_dates else None,
        )

    def get_player_ranking(
        self,
        player_id: str,
        *,
        family: str | None = None,
        tier: str | None = None,
    ) -> PlayerRanking:
        if (family is None) != (tier is None):
            raise ValueError("family and tier must be supplied together")
        if family is None:
            family, tier = self._player_affiliations.get(
                player_id, ("unknown", "unknown")
            )
        else:
            family, tier = self._validate_affiliation(family, tier, "ranking")

        stored_raw = self._player_states[player_id]
        last_activity = self._player_last_activity.get(player_id)
        inactive_periods = (
            0
            if self._current_date is None or last_activity is None
            else int(
                (self._current_date - last_activity).days
                // self.rating_period_days
            )
        )
        raw = inflate(stored_raw, inactive_periods)
        location = self.get_family_location(family, tier)
        return PlayerRanking(
            player_id=player_id,
            raw_rating=raw.rating,
            raw_rd=raw.rd,
            rating=raw.rating + location.mean,
            rd=math.sqrt(raw.rd * raw.rd + location.variance),
            volatility=raw.volatility,
            family=family,
            tier=tier,
            last_activity=last_activity,
            games_played=self._player_games.get(player_id, 0),
        )

    def get_player_rankings(self) -> tuple[PlayerRanking, ...]:
        return tuple(self.get_player_ranking(player_id) for player_id in self.player_ids)

    def process_period(self, events: Iterable[RatingEvent]) -> dict[str, float]:
        """Process exactly one complete calendar date against a frozen prior.

        Returns frozen-prior side-A win probabilities keyed in event-id order.
        No state is changed unless all events validate successfully.
        """

        ordered_events = self._validated_events(events)
        period_date = ordered_events[0].event_date
        if self._current_date is not None and period_date <= self._current_date:
            raise ValueError("rating periods must be processed in strictly increasing date order")

        player_states, family_states, tier_states = self._frozen_period_states(
            period_date, ordered_events
        )
        family_tiers = dict(self._family_tiers)
        observations: dict[str, list[Glicko2Observation]] = defaultdict(list)
        affiliation_candidates: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
        games_added: dict[str, int] = defaultdict(int)
        predictions: dict[str, float] = {}
        offset_evidence: list[tuple[float, dict[tuple[str, str], float], float]] = []

        for event in ordered_events:
            players_a = tuple(sorted(event.players_a))
            players_b = tuple(sorted(event.players_b))
            raw_a, raw_variance_a = self._aggregate_players(players_a, player_states)
            raw_b, raw_variance_b = self._aggregate_players(players_b, player_states)
            location_difference = self._location_difference(
                event, family_states, tier_states
            )
            predictions[event.event_id] = expected_score(
                raw_a + location_difference.mean,
                math.sqrt(raw_variance_a + location_difference.variance),
                raw_b,
                math.sqrt(raw_variance_b),
            )

            opponent_rd_for_a = math.sqrt(
                raw_variance_b + location_difference.variance
            )
            opponent_rd_for_b = math.sqrt(
                raw_variance_a + location_difference.variance
            )
            opponent_rating_for_a = raw_b - location_difference.mean
            opponent_rating_for_b = raw_a + location_difference.mean
            for score in event.scores:
                for player_id in players_a:
                    observations[player_id].append(
                        Glicko2Observation(
                            opponent_rating=opponent_rating_for_a,
                            opponent_rd=opponent_rd_for_a,
                            score=float(score),
                        )
                    )
                for player_id in players_b:
                    observations[player_id].append(
                        Glicko2Observation(
                            opponent_rating=opponent_rating_for_b,
                            opponent_rd=opponent_rd_for_b,
                            score=float(1 - score),
                        )
                    )

            affiliations_known = (
                event.family_a != "unknown" and event.family_b != "unknown"
            )
            if affiliations_known:
                for player_id in players_a:
                    affiliation_candidates[player_id].append(
                        (event.event_id, event.family_a, event.tier_a)
                    )
                for player_id in players_b:
                    affiliation_candidates[player_id].append(
                        (event.event_id, event.family_b, event.tier_b)
                    )
                family_tiers[event.family_a] = event.tier_a
                family_tiers[event.family_b] = event.tier_b
            for player_id in players_a:
                games_added[player_id] += len(event.scores)
            for player_id in players_b:
                games_added[player_id] += len(event.scores)

            majority = self._majority_score(event.scores)
            if (
                affiliations_known
                and event.family_a != event.family_b
                and majority is not None
            ):
                coefficients = self._offset_coefficients(event)
                difference = raw_a - raw_b + location_difference.mean
                probability = self._logistic(difference)
                offset_evidence.append((majority, coefficients, probability))

        committed_players = dict(player_states)
        for player_id in sorted(observations):
            player_observations = sorted(
                observations[player_id],
                key=lambda item: (
                    item.opponent_rating,
                    item.opponent_rd,
                    item.score,
                    item.weight,
                ),
            )
            committed_players[player_id] = update(
                player_states[player_id],
                player_observations,
                tau=self.tau,
                convergence_tolerance=self.convergence_tolerance,
            )

        committed_families, committed_tiers = self._updated_offsets(
            family_states, tier_states, offset_evidence, period_date
        )
        committed_families = self._center_family_locations(
            committed_families, committed_tiers, family_tiers
        )

        self._player_states = committed_players
        self._family_states = committed_families
        self._tier_states = committed_tiers
        self._family_tiers = family_tiers
        for player_id in sorted(affiliation_candidates):
            candidates = {
                (family, tier)
                for _, family, tier in affiliation_candidates[player_id]
            }
            if len(candidates) == 1:
                self._player_affiliations[player_id] = candidates.pop()
            elif player_id not in self._player_affiliations:
                self._player_affiliations.pop(player_id, None)
        for player_id in sorted(games_added):
            self._player_last_activity[player_id] = period_date
            self._player_games[player_id] = (
                self._player_games.get(player_id, 0) + games_added[player_id]
            )
        self._current_date = period_date
        return predictions

    def to_state(self) -> dict[str, Any]:
        """Return a deterministic, JSON-serializable engine snapshot."""

        players: dict[str, dict[str, Any]] = {}
        for player_id in self.player_ids:
            state = self._player_states[player_id]
            family, tier = self._player_affiliations.get(
                player_id, ("unknown", "unknown")
            )
            players[player_id] = {
                "rating": state.rating,
                "rd": state.rd,
                "volatility": state.volatility,
                "family": family,
                "tier": tier,
                "last_activity": self._date_to_json(
                    self._player_last_activity.get(player_id)
                ),
                "games_played": self._player_games.get(player_id, 0),
            }
        families = {
            family: {
                **self._offset_to_json(self._family_states[family]),
                "tier": self._family_tiers[family],
            }
            for family in self.family_ids
        }
        tiers = {
            tier: self._offset_to_json(self._tier_states[tier])
            for tier in self.tier_ids
        }
        return {
            "state_version": self.STATE_VERSION,
            "parameters": {
                "tau": self.tau,
                "convergence_tolerance": self.convergence_tolerance,
                "rating_period_days": self.rating_period_days,
                "initial_family_deviation": self.initial_family_deviation,
                "initial_tier_deviation": self.initial_tier_deviation,
                "bridge_process_deviation": self.bridge_process_deviation,
            },
            "current_date": self._date_to_json(self._current_date),
            "players": players,
            "families": families,
            "tiers": tiers,
        }

    @classmethod
    def from_state(cls, payload: Mapping[str, Any]) -> FamilyCalibratedGlicko2:
        """Restore a snapshot produced by :meth:`to_state`."""

        if payload.get("state_version") != cls.STATE_VERSION:
            raise ValueError("unsupported family-calibrated rating state version")
        parameters = payload.get("parameters")
        if not isinstance(parameters, Mapping):
            raise ValueError("state parameters must be a mapping")
        engine = cls(**dict(parameters))
        engine._current_date = cls._date_from_json(payload.get("current_date"))

        tiers = payload.get("tiers")
        families = payload.get("families")
        players = payload.get("players")
        if not isinstance(tiers, Mapping) or not isinstance(families, Mapping):
            raise ValueError("state offsets must be mappings")
        if not isinstance(players, Mapping):
            raise ValueError("state players must be a mapping")

        for raw_tier in sorted(tiers):
            tier = engine._validate_tier(raw_tier, "state tier")
            engine._tier_states[tier] = cls._offset_from_json(tiers[raw_tier])
        for raw_family in sorted(families):
            family = engine._validate_family(raw_family, "state family")
            value = families[raw_family]
            if not isinstance(value, Mapping):
                raise ValueError("family state must be a mapping")
            tier = engine._validate_tier(value.get("tier"), "family tier")
            if tier not in engine._tier_states:
                raise ValueError("family state references a missing tier")
            engine._family_states[family] = cls._offset_from_json(value)
            engine._family_tiers[family] = tier

        for raw_player_id in sorted(players):
            player_id = engine._validate_identifier(raw_player_id, "player id")
            value = players[raw_player_id]
            if not isinstance(value, Mapping):
                raise ValueError("player state must be a mapping")
            family, tier = engine._validate_affiliation(
                value.get("family"), value.get("tier"), "player affiliation"
            )
            if family != "unknown" and (
                family not in engine._family_states or tier not in engine._tier_states
            ):
                raise ValueError("player affiliation references a missing offset")
            state = Glicko2State(
                rating=float(value["rating"]),
                rd=float(value["rd"]),
                volatility=float(value["volatility"]),
            )
            games_played = value.get("games_played", 0)
            if not isinstance(games_played, int) or games_played < 0:
                raise ValueError("games_played must be a non-negative integer")
            last_activity = cls._date_from_json(value.get("last_activity"))
            if (
                engine._current_date is not None
                and last_activity is not None
                and last_activity > engine._current_date
            ):
                raise ValueError("player activity cannot be after the snapshot date")
            engine._player_states[player_id] = state
            if family != "unknown":
                engine._player_affiliations[player_id] = (family, tier)
            if last_activity is not None:
                engine._player_last_activity[player_id] = last_activity
            engine._player_games[player_id] = games_played
        return engine

    def _validated_events(self, events: Iterable[RatingEvent]) -> list[RatingEvent]:
        values = list(events)
        if not values:
            raise ValueError("a rating period must contain at least one event")
        seen_event_ids: set[str] = set()
        period_date: date | None = None
        for event in values:
            if not isinstance(event, RatingEvent):
                raise TypeError("events must be RatingEvent instances")
            event_id = self._validate_identifier(event.event_id, "event id")
            if event_id in seen_event_ids:
                raise ValueError(f"duplicate event id: {event_id}")
            seen_event_ids.add(event_id)
            if not isinstance(event.event_date, date) or isinstance(event.event_date, datetime):
                raise ValueError("event_date must be a calendar date")
            if period_date is None:
                period_date = event.event_date
            elif event.event_date != period_date:
                raise ValueError("all events in a rating period must share one date")
            team_a = self._validate_identifier(event.team_a_id, "team A id")
            team_b = self._validate_identifier(event.team_b_id, "team B id")
            if team_a == team_b:
                raise ValueError("an event must contain two different teams")
            players_a = self._validated_roster(event.players_a, "players_a")
            players_b = self._validated_roster(event.players_b, "players_b")
            if set(players_a) & set(players_b):
                raise ValueError("event rosters must be disjoint")
            self._validate_affiliation(
                event.family_a, event.tier_a, "side A affiliation"
            )
            self._validate_affiliation(
                event.family_b, event.tier_b, "side B affiliation"
            )
            if isinstance(event.scores, (str, bytes)):
                raise ValueError("scores must be a sequence of binary results")
            try:
                scores = tuple(event.scores)
            except TypeError as exc:
                raise ValueError("scores must be a sequence of binary results") from exc
            if not scores or any(type(score) is not int or score not in (0, 1) for score in scores):
                raise ValueError("scores must be nonempty and binary")
        return sorted(values, key=lambda item: item.event_id)

    @classmethod
    def _validated_roster(cls, roster: Sequence[str], field: str) -> tuple[str, ...]:
        if isinstance(roster, (str, bytes)):
            raise ValueError(f"{field} must be a player sequence")
        try:
            players = tuple(roster)
        except TypeError as exc:
            raise ValueError(f"{field} must be a player sequence") from exc
        if not players:
            raise ValueError(f"{field} cannot be empty")
        normalized = tuple(cls._validate_identifier(player, field) for player in players)
        if len(set(normalized)) != len(normalized):
            raise ValueError(f"{field} cannot contain duplicate players")
        return normalized

    @staticmethod
    def _validate_identifier(value: Any, field: str) -> str:
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise ValueError(f"{field} must be a nonempty normalized string")
        return value

    @classmethod
    def _validate_family(cls, value: Any, field: str) -> str:
        family = cls._validate_identifier(value, field)
        if family not in _KNOWN_FAMILIES:
            raise ValueError(f"{field} must be a known family")
        return family

    @classmethod
    def _validate_tier(cls, value: Any, field: str) -> str:
        tier = cls._validate_identifier(value, field)
        if tier not in _KNOWN_TIERS:
            raise ValueError(f"{field} must be a known competition tier")
        return tier

    @classmethod
    def _validate_affiliation(
        cls, family_value: Any, tier_value: Any, field: str
    ) -> tuple[str, str]:
        family = cls._validate_identifier(family_value, f"{field} family")
        tier = cls._validate_identifier(tier_value, f"{field} tier")
        if family == "unknown" or tier == "unknown":
            if family == tier == "unknown":
                return family, tier
            raise ValueError(f"{field} must be fully known or fully unknown")
        return cls._validate_family(family, field), cls._validate_tier(tier, field)

    def _frozen_period_states(
        self, period_date: date, events: Sequence[RatingEvent]
    ) -> tuple[
        dict[str, Glicko2State],
        dict[str, GaussianOffsetState],
        dict[str, GaussianOffsetState],
    ]:
        participating_players = {
            player_id
            for event in events
            for player_id in (*event.players_a, *event.players_b)
        }
        players = dict(self._player_states)
        for player_id in sorted(participating_players):
            if player_id not in players:
                players[player_id] = Glicko2State()
                continue
            last_activity = self._player_last_activity.get(player_id)
            elapsed_periods = (
                0
                if last_activity is None
                else int(
                    (period_date - last_activity).days // self.rating_period_days
                )
            )
            players[player_id] = inflate(players[player_id], elapsed_periods)

        elapsed_days = (
            0
            if self._current_date is None
            else (period_date - self._current_date).days
        )
        families = {
            family: self._advance_offset(state, elapsed_days)
            for family, state in self._family_states.items()
        }
        tiers = {
            tier: self._advance_offset(state, elapsed_days)
            for tier, state in self._tier_states.items()
        }
        for event in events:
            if event.family_a == "unknown" or event.family_b == "unknown":
                continue
            for family in (event.family_a, event.family_b):
                families.setdefault(
                    family,
                    GaussianOffsetState(
                        mean=0.0,
                        variance=self.initial_family_deviation**2,
                    ),
                )
            for tier in (event.tier_a, event.tier_b):
                tiers.setdefault(
                    tier,
                    GaussianOffsetState(
                        mean=0.0,
                        variance=self.initial_tier_deviation**2,
                    ),
                )
        return players, families, tiers

    def _advance_offset(
        self, state: GaussianOffsetState, elapsed_days: int
    ) -> GaussianOffsetState:
        if elapsed_days < 0:
            raise ValueError("cannot move offset state backwards")
        process_variance = (
            self.bridge_process_deviation**2
            * elapsed_days
            / self.rating_period_days
        )
        return GaussianOffsetState(
            mean=state.mean,
            variance=state.variance + process_variance,
            last_bridge_date=state.last_bridge_date,
        )

    @staticmethod
    def _aggregate_players(
        player_ids: Sequence[str], states: Mapping[str, Glicko2State]
    ) -> tuple[float, float]:
        count = len(player_ids)
        rating = math.fsum(states[player_id].rating for player_id in player_ids) / count
        variance = (
            math.fsum(states[player_id].rd ** 2 for player_id in player_ids)
            / (count * count)
        )
        return rating, variance

    def _location_difference(
        self,
        event: RatingEvent,
        families: Mapping[str, GaussianOffsetState],
        tiers: Mapping[str, GaussianOffsetState],
    ) -> GaussianOffsetState:
        missing_variance = 0.0
        coefficients: dict[tuple[str, str], float] = defaultdict(float)
        for family, tier, sign in (
            (event.family_a, event.tier_a, 1.0),
            (event.family_b, event.tier_b, -1.0),
        ):
            if family == tier == "unknown":
                missing_variance += self._unknown_location().variance
                continue
            coefficients[("family", family)] += sign
            coefficients[("tier", tier)] += sign
        if event.family_a != "unknown" and event.family_a == event.family_b:
            coefficients.clear()

        mean_terms: list[float] = []
        variance_terms: list[float] = [missing_variance]
        for (kind, name), coefficient in sorted(coefficients.items()):
            if coefficient == 0.0:
                continue
            states = families if kind == "family" else tiers
            state = states.get(name)
            if state is None:
                default_deviation = (
                    self.initial_family_deviation
                    if kind == "family"
                    else self.initial_tier_deviation
                )
                variance_terms.append(coefficient * coefficient * default_deviation**2)
                continue
            mean_terms.append(coefficient * state.mean)
            variance_terms.append(coefficient * coefficient * state.variance)
        return GaussianOffsetState(
            mean=math.fsum(mean_terms),
            variance=math.fsum(variance_terms),
        )

    def _unknown_location(self) -> GaussianOffsetState:
        return GaussianOffsetState(
            mean=0.0,
            variance=(
                self.initial_family_deviation**2 + self.initial_tier_deviation**2
            ),
        )

    @staticmethod
    def _majority_score(scores: Sequence[int]) -> float | None:
        wins = sum(scores)
        losses = len(scores) - wins
        if wins == losses:
            return None
        return 1.0 if wins > losses else 0.0

    @staticmethod
    def _offset_coefficients(event: RatingEvent) -> dict[tuple[str, str], float]:
        coefficients: dict[tuple[str, str], float] = defaultdict(float)
        coefficients[("family", event.family_a)] += 1.0
        coefficients[("tier", event.tier_a)] += 1.0
        coefficients[("family", event.family_b)] -= 1.0
        coefficients[("tier", event.tier_b)] -= 1.0
        return {
            component: coefficient
            for component, coefficient in coefficients.items()
            if coefficient != 0.0
        }

    @staticmethod
    def _logistic(rating_difference: float) -> float:
        exponent = max(-700.0, min(700.0, -_RATING_SCALE * rating_difference))
        return 1.0 / (1.0 + math.exp(exponent))

    def _updated_offsets(
        self,
        families: Mapping[str, GaussianOffsetState],
        tiers: Mapping[str, GaussianOffsetState],
        evidence: Sequence[tuple[float, Mapping[tuple[str, str], float], float]],
        period_date: date,
    ) -> tuple[dict[str, GaussianOffsetState], dict[str, GaussianOffsetState]]:
        states: dict[tuple[str, str], GaussianOffsetState] = {
            **{("family", name): state for name, state in families.items()},
            **{("tier", name): state for name, state in tiers.items()},
        }
        precision_addition: dict[tuple[str, str], float] = defaultdict(float)
        information_addition: dict[tuple[str, str], float] = defaultdict(float)
        for outcome, coefficients, probability in evidence:
            logistic_precision = _RATING_SCALE**2 * probability * (1.0 - probability)
            total_variance = math.fsum(
                coefficient * coefficient * states[component].variance
                for component, coefficient in coefficients.items()
            )
            for component, coefficient in coefficients.items():
                state = states[component]
                own_variance = coefficient * coefficient * state.variance
                other_variance = max(0.0, total_variance - own_variance)
                marginalizer = 1.0 + logistic_precision * other_variance
                precision_addition[component] += (
                    coefficient * coefficient * logistic_precision / marginalizer
                )
                information_addition[component] += (
                    coefficient
                    * _RATING_SCALE
                    * (outcome - probability)
                    / marginalizer
                )

        updated = dict(states)
        for component in sorted(precision_addition):
            prior = states[component]
            if prior.variance == 0.0:
                continue
            posterior_variance = 1.0 / (
                1.0 / prior.variance + precision_addition[component]
            )
            updated[component] = GaussianOffsetState(
                mean=prior.mean + posterior_variance * information_addition[component],
                variance=posterior_variance,
                last_bridge_date=period_date,
            )
        return (
            {name: updated[("family", name)] for name in sorted(families)},
            {name: updated[("tier", name)] for name in sorted(tiers)},
        )

    @staticmethod
    def _center_family_locations(
        families: Mapping[str, GaussianOffsetState],
        tiers: Mapping[str, GaussianOffsetState],
        family_tiers: Mapping[str, str],
    ) -> dict[str, GaussianOffsetState]:
        if not families:
            return {}
        names = sorted(families)
        center = math.fsum(
            families[family].mean + tiers[family_tiers[family]].mean
            for family in names
        ) / len(names)
        centered = {
            family: GaussianOffsetState(
                mean=families[family].mean - center,
                variance=families[family].variance,
                last_bridge_date=families[family].last_bridge_date,
            )
            for family in names
        }
        anchor = names[-1]
        other_total = math.fsum(
            centered[family].mean + tiers[family_tiers[family]].mean
            for family in names[:-1]
        )
        anchor_state = centered[anchor]
        centered[anchor] = GaussianOffsetState(
            mean=-other_total - tiers[family_tiers[anchor]].mean,
            variance=anchor_state.variance,
            last_bridge_date=anchor_state.last_bridge_date,
        )
        return centered

    @staticmethod
    def _date_to_json(value: date | None) -> str | None:
        return value.isoformat() if value is not None else None

    @staticmethod
    def _date_from_json(value: Any) -> date | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("serialized dates must be ISO strings or null")
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("serialized date is invalid") from exc

    @classmethod
    def _offset_to_json(cls, state: GaussianOffsetState) -> dict[str, Any]:
        return {
            "mean": state.mean,
            "variance": state.variance,
            "last_bridge_date": cls._date_to_json(state.last_bridge_date),
        }

    @classmethod
    def _offset_from_json(cls, value: Any) -> GaussianOffsetState:
        if not isinstance(value, Mapping):
            raise ValueError("offset state must be a mapping")
        mean = float(value["mean"])
        variance = float(value["variance"])
        if not math.isfinite(mean) or not math.isfinite(variance) or variance < 0.0:
            raise ValueError("offset state contains invalid values")
        return GaussianOffsetState(
            mean=mean,
            variance=variance,
            last_bridge_date=cls._date_from_json(value.get("last_bridge_date")),
        )


__all__ = [
    "FamilyCalibratedGlicko2",
    "GaussianOffsetState",
    "PlayerRanking",
    "RatingEvent",
]
