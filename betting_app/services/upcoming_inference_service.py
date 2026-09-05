"""Build operational features, predictions and EV signals for upcoming LoL matches.

This module intentionally separates the production-ish upcoming workflow from the
thesis final model artefacts.  The final EXP-039 model needs confirmed upcoming
rosters and the exact historical feature matrix.  For live upcoming matches we
use a durable current roster (automatically refreshed from GOL.GG, with a
manual confirmation fallback) for each team, then use
player ratings, team ratings and W20 context.  Diagnostics are stored in SQLite
so this can be audited and replaced by a confirmed-roster pipeline later.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from typing import Any

from betting_app.core.db import query_df, transaction
from betting_app.core.ev import expected_value, fair_market_probabilities
from betting_app.core.matching import normalize_team_name
from betting_app.core.staking import fractional_kelly_stake
from betting_app.ml.calibration.conformal_contract import conformal_bounds_for_side
from betting_app.services.canonical_match_service import (
    align_snapshot_odds,
    canonical_team_key,
    parse_iso,
)
from betting_app.services.mapping_service import golgg_name_from_id, suggest_mapping
from betting_app.services.rating_contract import (
    OPERATIONAL_FEATURE_VERSION,
    OPERATIONAL_MODEL_NAME,
    OPERATIONAL_MODEL_VERSION,
    OPERATIONAL_RATINGS_VERSION,
    PUBLIC_RATING_SYSTEMS,
    RAW_RATING_SYSTEMS,
    REGIONAL_ENGINE,
)
from src.ratings.competition_adjustment import (
    CompetitionAdjustment,
    NEUTRAL_COMPETITION_ADJUSTMENT,
    adjust_probability,
)
from src.ratings.family_calibrated_glicko2 import FamilyCalibratedGlicko2

DEFAULT_FEATURE_VERSION = OPERATIONAL_FEATURE_VERSION
DEFAULT_RATINGS_VERSION = OPERATIONAL_RATINGS_VERSION
DEFAULT_W20_VERSION = "w20-latest"
DEFAULT_MODEL_NAME = OPERATIONAL_MODEL_NAME
DEFAULT_MODEL_VERSION = OPERATIONAL_MODEL_VERSION
DEFAULT_HYBRID_MODEL_NAME = "Hybrid-Operational-Market"
DEFAULT_HYBRID_ALPHA = 0.50
DEFAULT_HYBRID_TEMPERATURE = 1.00
RATING_SYSTEMS = PUBLIC_RATING_SYSTEMS
W20_FIELDS = (
    "win_rate",
    "avg_kills",
    "avg_deaths",
    "avg_gd15",
    "avg_dpm",
    "avg_vspm",
    "avg_gold",
    "avg_towers",
    "avg_dragons",
    "avg_nashors",
    "avg_game_duration",
)


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-40.0, min(40.0, value))))


def logit(probability: float) -> float:
    p = max(1e-6, min(1.0 - 1e-6, probability))
    return math.log(p / (1.0 - p))


def apply_temperature_probability(probability: float, temperature: float) -> float:
    """Apply binary temperature scaling to one probability."""

    if temperature <= 0:
        raise ValueError("temperature must be positive")
    return sigmoid(logit(probability) / temperature)


def build_all_upcoming_features(
    *,
    feature_version: str = DEFAULT_FEATURE_VERSION,
    ratings_version: str = DEFAULT_RATINGS_VERSION,
    w20_version: str = DEFAULT_W20_VERSION,
    min_mapping_confidence: float = 0.72,
    include_past: bool = False,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Build and upsert feature vectors for canonical upcoming matches."""

    matches = load_canonical_matches(include_past=include_past, limit=limit)
    results: list[dict[str, Any]] = []
    for match in matches:
        result = build_features_for_match(
            dict(match),
            feature_version=feature_version,
            ratings_version=ratings_version,
            w20_version=w20_version,
            min_mapping_confidence=min_mapping_confidence,
        )
        results.append(result)
    return results


def _select_aligned_golgg_ids(
    canonical_match: dict[str, Any],
    offers: list[dict[str, Any]],
) -> tuple[int | None, int | None]:
    """Return GOL.GG IDs in canonical A/B order from the newest valid offer.

    ``upcoming_matches`` keeps the bookmaker's raw team order. Selecting the
    newest row directly therefore swaps rosters whenever a bookmaker lists
    the same event B-vs-A. Only use offers whose teams match the canonical
    identity, and swap their IDs when their raw order is reversed.
    """

    league = str(canonical_match.get("league") or "")
    match_date = canonical_match.get("start_time_normalized")
    canonical_a = canonical_team_key(
        str(canonical_match.get("team_a_name") or ""), league=league, match_date=match_date
    )
    canonical_b = canonical_team_key(
        str(canonical_match.get("team_b_name") or ""), league=league, match_date=match_date
    )
    for offer in offers:
        offer_league = str(offer.get("league") or league)
        raw_a = canonical_team_key(
            str(offer.get("raw_team_a") or ""), league=offer_league, match_date=match_date
        )
        raw_b = canonical_team_key(
            str(offer.get("raw_team_b") or ""), league=offer_league, match_date=match_date
        )
        golgg_a, golgg_b = offer.get("team_a_golgg_id"), offer.get("team_b_golgg_id")
        if golgg_a is None or golgg_b is None:
            continue
        if raw_a == canonical_a and raw_b == canonical_b:
            return int(golgg_a), int(golgg_b)
        if raw_a == canonical_b and raw_b == canonical_a:
            return int(golgg_b), int(golgg_a)
    return None, None


def load_canonical_matches(*, include_past: bool = False, limit: int | None = None):
    """Load canonical matches with GOL.GG IDs aligned to canonical A/B sides."""

    where = "WHERE cm.status = 'upcoming'"
    params: list[Any] = []
    if not include_past:
        where += " AND (cm.start_time_normalized IS NULL OR cm.start_time_normalized >= ?)"
        params.append(datetime.now(UTC).replace(microsecond=0).isoformat())
    sql = f"""
        SELECT cm.*,
               COUNT(DISTINCT os.bookmaker_id) AS bookmaker_count,
               MAX(os.scraped_at) AS last_scraped_at
        FROM canonical_matches cm
        JOIN odds_snapshots os ON os.canonical_match_id = cm.id
        {where}
        GROUP BY cm.id
        ORDER BY cm.start_time_normalized ASC, cm.id ASC
    """
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))
    with transaction() as connection:
        matches = [dict(row) for row in connection.execute(sql, tuple(params)).fetchall()]
        if not matches:
            return []
        match_ids = [int(match["id"]) for match in matches]
        placeholders = ", ".join("?" for _ in match_ids)
        rows = connection.execute(
            f"""
            SELECT canonical_match_id, raw_team_a, raw_team_b, league,
                   team_a_golgg_id, team_b_golgg_id, last_seen_at
            FROM upcoming_matches
            WHERE canonical_match_id IN ({placeholders})
            ORDER BY canonical_match_id ASC, last_seen_at DESC, id DESC
            """,
            tuple(match_ids),
        ).fetchall()

    offers_by_match: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        offer = dict(row)
        offers_by_match.setdefault(int(offer["canonical_match_id"]), []).append(offer)
    for match in matches:
        team_a_id, team_b_id = _select_aligned_golgg_ids(
            match, offers_by_match.get(int(match["id"]), [])
        )
        match["team_a_golgg_id"] = team_a_id
        match["team_b_golgg_id"] = team_b_id
    return matches


def build_features_for_match(
    match: dict[str, Any],
    *,
    feature_version: str,
    ratings_version: str,
    w20_version: str,
    min_mapping_confidence: float,
    team_a_roster_override: dict[str, Any] | None = None,
    team_b_roster_override: dict[str, Any] | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Build one canonical match feature vector, persisting it when requested."""

    canonical_match_id = int(match["id"])
    team_a_raw = str(match.get("team_a_name") or "")
    team_b_raw = str(match.get("team_b_name") or "")

    # Resolve GOL.GG team names: prefer IDs from upcoming_matches (no fuzzy matching)
    golgg_a_id = match.get("team_a_golgg_id")
    golgg_b_id = match.get("team_b_golgg_id")
    team_a_golgg = golgg_name_from_id(golgg_a_id)
    team_b_golgg = golgg_name_from_id(golgg_b_id)
    mapping_from_ids = team_a_golgg is not None and team_b_golgg is not None

    if not mapping_from_ids:
        team_a_golgg, conf_a, source_a = suggest_mapping(
            team_a_raw,
            source_system="bookmaker",
            league=str(match.get("league") or ""),
            match_date=str(match.get("start_time_normalized") or ""),
        )
        team_b_golgg, conf_b, source_b = suggest_mapping(
            team_b_raw,
            source_system="bookmaker",
            league=str(match.get("league") or ""),
            match_date=str(match.get("start_time_normalized") or ""),
        )
    else:
        conf_a = conf_b = 1.0
        source_a = source_b = "golgg_id"

    missing: list[str] = []
    if not team_a_golgg or conf_a < min_mapping_confidence:
        missing.append(f"team_a_mapping:{team_a_raw}:{conf_a:.3f}")
    if not team_b_golgg or conf_b < min_mapping_confidence:
        missing.append(f"team_b_mapping:{team_b_raw}:{conf_b:.3f}")

    ratings_a = load_team_ratings(team_a_golgg, ratings_version) if team_a_golgg else {}
    ratings_b = load_team_ratings(team_b_golgg, ratings_version) if team_b_golgg else {}
    regional_adjustment = load_regional_adjustment(
        ratings_a, ratings_b, ratings_version
    )
    for system in RATING_SYSTEMS:
        if system not in ratings_a:
            missing.append(f"team_a_rating:{system}")
        if system not in ratings_b:
            missing.append(f"team_b_rating:{system}")

    w20_a = load_w20(team_a_golgg, w20_version) if team_a_golgg else None
    w20_b = load_w20(team_b_golgg, w20_version) if team_b_golgg else None
    if not w20_a:
        missing.append("team_a_w20")
    if not w20_b:
        missing.append("team_b_w20")

    rating_probs = rating_probabilities(ratings_a, ratings_b, regional_adjustment)
    roster_a = team_a_roster_override or (load_last_roster(team_a_golgg) if team_a_golgg else None)
    roster_b = team_b_roster_override or (load_last_roster(team_b_golgg) if team_b_golgg else None)
    if not roster_a or len(roster_a.get("players", [])) < 5:
        missing.append("team_a_last_roster")
    if not roster_b or len(roster_b.get("players", [])) < 5:
        missing.append("team_b_last_roster")
    player_ratings_a = load_roster_player_ratings(roster_a, ratings_version) if roster_a else {}
    player_ratings_b = load_roster_player_ratings(roster_b, ratings_version) if roster_b else {}
    for system in RATING_SYSTEMS:
        if system not in player_ratings_a:
            missing.append(f"team_a_player_rating:{system}")
        if system not in player_ratings_b:
            missing.append(f"team_b_player_rating:{system}")
    player_probs = player_rating_probabilities(
        player_ratings_a, player_ratings_b, regional_adjustment
    )
    w20_prob = w20_probability(w20_a, w20_b) if w20_a and w20_b else None
    features = {
        "canonical_match_id": canonical_match_id,
        "canonical": {
            "team_a_name": team_a_raw,
            "team_b_name": team_b_raw,
            "start_time_normalized": match.get("start_time_normalized"),
            "league": match.get("league"),
            "bookmaker_count": match.get("bookmaker_count"),
        },
        "mapping": {
            "team_a_golgg_name": team_a_golgg,
            "team_b_golgg_name": team_b_golgg,
            "team_a_confidence": conf_a,
            "team_b_confidence": conf_b,
            "team_a_source": source_a,
            "team_b_source": source_b,
        },
        "ratings": {
            "team_a": ratings_a,
            "team_b": ratings_b,
            "probabilities": rating_probs,
        },
        "regional_adjustment": regional_adjustment_state(regional_adjustment),
        "player_ratings": {
            "team_a_roster": roster_a,
            "team_b_roster": roster_b,
            "team_a": player_ratings_a,
            "team_b": player_ratings_b,
            "probabilities": player_probs,
            "roster_source": "match_override"
            if team_a_roster_override or team_b_roster_override
            else "current_team_roster",
        },
        "w20": {"team_a": w20_a, "team_b": w20_b, "probability": w20_prob},
        "diagnostics": {
            "missing": missing,
            "missing_player_roster": not roster_a or not roster_b,
            "note": "Upcoming rosters use the durable current team roster; it is refreshed from the latest GOL.GG game or manually confirmed.",
        },
    }
    status = "ready_player" if not missing else "partial"
    data_cutoff_at = latest_data_cutoff(ratings_version, w20_version)
    if persist:
        upsert_upcoming_features(
            canonical_match_id=canonical_match_id,
            feature_version=feature_version,
            ratings_version=ratings_version,
            data_cutoff_at=data_cutoff_at,
            team_a_golgg_name=team_a_golgg,
            team_b_golgg_name=team_b_golgg,
            feature_status=status,
            missing_reason=";".join(missing) if missing else None,
            features=features,
        )
    return {
        "canonical_match_id": canonical_match_id,
        "status": status,
        "missing": missing,
        "data_cutoff_at": data_cutoff_at,
        "features": features,
    }


def load_team_ratings(team_name: str | None, ratings_version: str) -> dict[str, dict[str, Any]]:
    if not team_name:
        return {}
    frame = query_df(
        """
        SELECT rating_system, rating_value, rd, sigma, games_played, last_match_at, state_json
        FROM entity_ratings
        WHERE ratings_version = ? AND entity_type = 'team' AND normalized_entity_name = ?
        """,
        (ratings_version, normalize_team_name(team_name)),
    )
    result: dict[str, dict[str, Any]] = {}
    for row in frame.to_dict("records"):
        system = str(row["rating_system"])
        result[system] = {
            "rating_value": none_or_float(row.get("rating_value")),
            "rd": none_or_float(row.get("rd")),
            "sigma": none_or_float(row.get("sigma")),
            "games_played": int(row.get("games_played") or 0),
            "last_match_at": row.get("last_match_at"),
            "state_json": row.get("state_json"),
        }
    return result


def load_player_ratings(player_names: list[str], ratings_version: str) -> dict[str, dict[str, dict[str, Any]]]:
    """Load ratings for a list of players.

    Returns: { player_name: { system_name: { rating_value, rd, sigma, ... } } }
    """
    if not player_names:
        return {}

    placeholders = ", ".join(["?"] * len(player_names))
    frame = query_df(
        f"""
        SELECT normalized_entity_name, rating_system, rating_value, rd, sigma, games_played, last_match_at
        FROM entity_ratings
        WHERE ratings_version = ? AND entity_type = 'player' AND normalized_entity_name IN ({placeholders})
        """,
        (ratings_version, *[normalize_team_name(p) for p in player_names]),
    )

    result: dict[str, dict[str, dict[str, Any]]] = {}
    for row in frame.to_dict("records"):
        p_name = str(row["normalized_entity_name"])
        system = str(row["rating_system"])
        if p_name not in result:
            result[p_name] = {}
        result[p_name][system] = {
            "rating_value": none_or_float(row.get("rating_value")),
            "rd": none_or_float(row.get("rd")),
            "sigma": none_or_float(row.get("sigma")),
            "games_played": int(row.get("games_played") or 0),
            "last_match_at": row.get("last_match_at"),
        }
    return result


def load_w20(team_name: str | None, feature_version: str, window_size: int = 20) -> dict[str, Any] | None:
    if not team_name:
        return None
    frame = query_df(
        """
        SELECT *
        FROM team_rolling_features
        WHERE feature_version = ? AND normalized_team_name = ? AND window_size = ?
        LIMIT 1
        """,
        (feature_version, normalize_team_name(team_name), window_size),
    )
    if frame.empty:
        return None
    row = frame.iloc[0].to_dict()
    result = {
        "team_name": row.get("team_name"),
        "matches_count": int(row.get("matches_count") or 0),
        "games_count": int(row.get("games_count") or 0),
        "data_cutoff_at": row.get("data_cutoff_at"),
    }
    for field in W20_FIELDS:
        result[field] = none_or_float(row.get(field))
    try:
        extra = json.loads(row.get("features_json") or "{}")
        result["last_match_at"] = extra.get("last_match_at")
        result["team_id"] = extra.get("team_id")
    except json.JSONDecodeError:
        pass
    return result


def load_last_roster(team_name: str | None) -> dict[str, Any] | None:
    """Return the best known current roster, then GOL.GG last-match fallback.

    A durable roster is populated after completed GOL.GG games and may be
    manually confirmed before an announced lineup first appears in GOL.GG.
    Older deployments/databases gracefully retain the historical fallback.
    """

    if not team_name:
        return None
    try:
        current = query_df(
            """
            SELECT player_id, player_name, role, team_name, source,
                   source_match_id, source_match_date, source_game_id
            FROM team_current_roster_players
            WHERE normalized_team_name = ?
            ORDER BY CASE role
                WHEN 'TOP' THEN 1 WHEN 'JUNGLE' THEN 2 WHEN 'MID' THEN 3
                WHEN 'ADC' THEN 4 WHEN 'SUPPORT' THEN 5 ELSE 9 END
            """,
            (normalize_team_name(team_name),),
        )
        if len(current) == 5 and len(set(current["role"].astype(str).str.upper())) == 5:
            rows = current.to_dict("records")
            first = rows[0]
            source_val = str(first.get("source") or "")
            source_tourn = (
                "manual confirmation" if source_val == "manual"
                else "LoL Fandom active roster" if source_val == "fandom"
                else "Liquipedia active roster" if source_val == "liquipedia"
                else "GOL.GG current roster"
            )
            return {
                "team_name": first.get("team_name") or team_name,
                "source_match_id": first.get("source_match_id"),
                "source_match_date": first.get("source_match_date"),
                "source_tournament": source_tourn,
                "source_game_id": first.get("source_game_id"),
                "source": source_val or "auto",
                "players": [
                    {"player_id": str(row.get("player_id") or ""), "player_name": row.get("player_name"), "role": row.get("role")}
                    for row in rows
                ],
            }
    except Exception:
        # Migration may not yet exist in a developer database.
        pass

    matches = query_df(
        """
        SELECT gm.match_id, gm.date, gm.tournament_name
        FROM golgg_matches gm
        JOIN golgg_game_players gp ON gp.match_id = gm.match_id
        WHERE gp.team_name = ?
        ORDER BY gm.date DESC, gm.match_id DESC
        LIMIT 1
        """,
        (team_name,),
    )
    if matches.empty:
        # Fallback for exact-name drift: scan candidate team names and compare with Python normalization.
        candidates = query_df(
            """
            SELECT gp.team_name, gm.match_id, gm.date, gm.tournament_name
            FROM golgg_game_players gp
            JOIN golgg_matches gm ON gm.match_id = gp.match_id
            WHERE gp.team_name IS NOT NULL
            ORDER BY gm.date DESC, CAST(gm.match_id AS INTEGER) DESC
            LIMIT 20000
            """
        )
        wanted = normalize_team_name(team_name)
        candidates = candidates[candidates["team_name"].map(lambda value: normalize_team_name(str(value)) == wanted)]
        if candidates.empty:
            return None
        matches = candidates.head(1)
    match = matches.iloc[0].to_dict()
    first_game = query_df(
        """
        SELECT game_id
        FROM golgg_game_players
        WHERE match_id = ? AND team_name = ?
        GROUP BY game_id
        ORDER BY CAST(game_id AS INTEGER) ASC, game_id ASC
        LIMIT 1
        """,
        (str(match["match_id"]), team_name),
    )
    if first_game.empty:
        # If fallback matched a historical spelling, reuse that exact spelling.
        exact_team = str(candidates.iloc[0]["team_name"]) if "candidates" in locals() and not candidates.empty else team_name
        first_game = query_df(
            """
            SELECT game_id
            FROM golgg_game_players
            WHERE match_id = ? AND team_name = ?
            GROUP BY game_id
            ORDER BY CAST(game_id AS INTEGER) ASC, game_id ASC
            LIMIT 1
            """,
            (str(match["match_id"]), exact_team),
        )
        team_name = exact_team
    if first_game.empty:
        return None
    players = query_df(
        """
        SELECT player_id, player_name, role, team_name
        FROM golgg_game_players
        WHERE match_id = ? AND game_id = ? AND team_name = ?
        ORDER BY CASE role
            WHEN 'TOP' THEN 1 WHEN 'JUNGLE' THEN 2 WHEN 'MID' THEN 3
            WHEN 'ADC' THEN 4 WHEN 'SUPPORT' THEN 5 ELSE 9 END, role
        """,
        (str(match["match_id"]), str(first_game.iloc[0]["game_id"]), team_name),
    )
    roster_players = [
        {
            "player_id": str(row.get("player_id") or ""),
            "player_name": row.get("player_name"),
            "role": row.get("role"),
        }
        for row in players.to_dict("records")
        if row.get("player_id")
    ]
    return {
        "team_name": team_name,
        "source_match_id": str(match["match_id"]),
        "source_match_date": match.get("date"),
        "source_tournament": match.get("tournament_name"),
        "source_game_id": str(first_game.iloc[0]["game_id"]),
        "players": roster_players,
    }


def load_roster_player_ratings(roster: dict[str, Any] | None, ratings_version: str) -> dict[str, dict[str, Any]]:
    """Load aggregate player ratings for a roster by rating system."""

    if not roster:
        return {}
    roster_players = {
        str(player["player_id"]): player
        for player in roster.get("players", [])
        if player.get("player_id")
    }
    if not roster_players:
        return {}
    roster_players_by_identity: dict[str, dict[str, Any]] = {}
    for player in roster_players.values():
        for identity in (player.get("player_id"), player.get("player_name")):
            if identity:
                roster_players_by_identity.setdefault(
                    normalize_team_name(str(identity)),
                    player,
                )

    player_ids = list(roster_players)
    player_names = list(
        dict.fromkeys(
            str(identity).casefold()
            for player in roster_players.values()
            for identity in (player.get("player_id"), player.get("player_name"))
            if identity
        )
    )
    id_placeholders = ",".join("?" for _ in player_ids)
    name_placeholders = ",".join("?" for _ in player_names)
    frame = query_df(
        f"""
        SELECT rating_system, entity_name, normalized_entity_name, rating_value, rd, sigma, games_played, last_match_at
        FROM entity_ratings
        WHERE ratings_version = ? AND entity_type = 'player'
          AND (
              normalized_entity_name IN ({id_placeholders})
              OR LOWER(entity_name) IN ({name_placeholders})
          )
        """,
        (ratings_version, *player_ids, *player_names),
    )
    # ``query_df`` returns a column-less empty DataFrame when none of a
    # manually selected/new roster's IDs has a rating snapshot yet. That is a
    # valid partial-data state, not a reason to abort predictions for every
    # upcoming match in the batch.
    if frame.empty or "rating_system" not in frame.columns:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for system, group in frame.groupby("rating_system"):
        matched_players: dict[str, dict[str, Any]] = {}
        for player in group.to_dict("records"):
            roster_player = roster_players.get(str(player["normalized_entity_name"]))
            if roster_player is None:
                roster_player = roster_players_by_identity.get(
                    normalize_team_name(str(player.get("entity_name") or ""))
                )
            if roster_player is None:
                continue
            player_id = str(roster_player["player_id"])
            existing = matched_players.get(player_id)
            if existing is None or int(player.get("games_played") or 0) > int(
                existing["games_played"] or 0
            ):
                matched_players[player_id] = {
                    **player,
                    "player_id": player_id,
                    "player_name": roster_player.get("player_name")
                    or player.get("entity_name"),
                    "role": roster_player.get("role"),
                }
        player_records = list(matched_players.values())
        ratings = [
            none_or_float(player.get("rating_value"))
            for player in player_records
        ]
        ratings = [value for value in ratings if value is not None]
        if not ratings:
            continue
        result[str(system)] = {
            "avg_rating_value": sum(ratings) / len(ratings),
            "min_rating_value": min(ratings),
            "max_rating_value": max(ratings),
            "players_with_rating": len(ratings),
            "expected_players": len(player_ids),
            "players": player_records,
        }
    return result


def _regional_affiliation(rating: dict[str, Any], side: str) -> tuple[str, str] | None:
    state_json = rating.get("state_json")
    if not state_json:
        return None
    try:
        state = json.loads(str(state_json))
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid regional Glicko state for {side}") from error
    if not isinstance(state, dict):
        raise ValueError(f"invalid regional Glicko state for {side}")
    family = state.get("family")
    tier = state.get("tier")
    if family is None and tier is None:
        return None
    if not isinstance(family, str) or not isinstance(tier, str):
        raise ValueError(f"invalid regional affiliation for {side}")
    return family, tier


def load_regional_adjustment(
    ratings_a: dict[str, Any],
    ratings_b: dict[str, Any],
    ratings_version: str,
) -> CompetitionAdjustment:
    """Load the one persisted regional posterior for a v2 matchup.

    The calibrated Glicko probability already contains this location effect.
    Non-Glicko systems receive the same posterior once, after their native
    probability is calculated.  Unknown team affiliations remain neutral.
    """
    if ratings_version != OPERATIONAL_RATINGS_VERSION:
        return NEUTRAL_COMPETITION_ADJUSTMENT
    left = ratings_a.get("gl")
    right = ratings_b.get("gl")
    if left is None or right is None:
        return NEUTRAL_COMPETITION_ADJUSTMENT
    affiliation_a = _regional_affiliation(left, "team_a")
    affiliation_b = _regional_affiliation(right, "team_b")
    if affiliation_a is None or affiliation_b is None:
        return NEUTRAL_COMPETITION_ADJUSTMENT
    runs = query_df(
        """
        SELECT systems_json
        FROM rating_runs
        WHERE ratings_version = ? AND status = 'completed'
        ORDER BY finished_at DESC, id DESC
        LIMIT 1
        """,
        (ratings_version,),
    )
    if runs.empty:
        raise ValueError(f"no completed regional rating run for {ratings_version!r}")
    try:
        payload = json.loads(str(runs.iloc[0]["systems_json"]))
        regional = payload["gl"]
        if regional.get("engine") != REGIONAL_ENGINE:
            raise ValueError("unexpected regional Glicko engine")
        engine = FamilyCalibratedGlicko2.from_state(regional["state"])
    except (KeyError, TypeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(
            f"invalid persisted regional posterior for {ratings_version!r}"
        ) from error
    location = engine.get_location_difference(
        affiliation_a[0],
        affiliation_a[1],
        affiliation_b[0],
        affiliation_b[1],
    )
    return CompetitionAdjustment(
        mean=float(location.mean), variance=float(location.variance)
    )


def regional_adjustment_state(adjustment: CompetitionAdjustment) -> dict[str, Any]:
    return {
        "engine": REGIONAL_ENGINE,
        "mean": adjustment.mean,
        "variance": adjustment.variance,
        "applies_to": list(RAW_RATING_SYSTEMS),
    }


def _rating_probability(system: str, left: float, right: float) -> float:
    diff = left - right
    if system in {"elo", "gl"}:
        return 1.0 / (1.0 + 10 ** (-diff / 400.0))
    if system == "os":
        return sigmoid(diff / 5.0)
    return sigmoid(diff / 8.333)


def _with_regional_adjustment(
    system: str,
    probability: float,
    adjustment: CompetitionAdjustment,
) -> float:
    if system == "gl":
        return probability
    return adjust_probability(probability, adjustment)


def rating_probabilities(
    ratings_a: dict[str, Any],
    ratings_b: dict[str, Any],
    adjustment: CompetitionAdjustment = NEUTRAL_COMPETITION_ADJUSTMENT,
) -> dict[str, float]:
    probs: dict[str, float] = {}
    for system in RATING_SYSTEMS:
        left = ratings_a.get(system, {}).get("rating_value")
        right = ratings_b.get(system, {}).get("rating_value")
        if left is None or right is None:
            continue
        probs[system] = _with_regional_adjustment(
            system, _rating_probability(system, float(left), float(right)), adjustment
        )
    if probs:
        probs["consensus"] = sum(probs.values()) / len(probs)
    return probs


def player_rating_probabilities(
    ratings_a: dict[str, Any],
    ratings_b: dict[str, Any],
    adjustment: CompetitionAdjustment = NEUTRAL_COMPETITION_ADJUSTMENT,
) -> dict[str, float]:
    probs: dict[str, float] = {}
    for system in RATING_SYSTEMS:
        left = ratings_a.get(system, {}).get("avg_rating_value")
        right = ratings_b.get(system, {}).get("avg_rating_value")
        if left is None or right is None:
            continue
        probs[system] = _with_regional_adjustment(
            system, _rating_probability(system, float(left), float(right)), adjustment
        )
    if probs:
        probs["consensus"] = sum(probs.values()) / len(probs)
    return probs


def w20_probability(w20_a: dict[str, Any], w20_b: dict[str, Any]) -> float:
    win = (w20_a.get("win_rate") or 0.5) - (w20_b.get("win_rate") or 0.5)
    kills = (w20_a.get("avg_kills") or 12.0) - (w20_b.get("avg_kills") or 12.0)
    deaths = (w20_a.get("avg_deaths") or 12.0) - (w20_b.get("avg_deaths") or 12.0)
    gd15 = (w20_a.get("avg_gd15") or 0.0) - (w20_b.get("avg_gd15") or 0.0)
    dpm = (w20_a.get("avg_dpm") or 1800.0) - (w20_b.get("avg_dpm") or 1800.0)
    towers = (w20_a.get("avg_towers") or 5.0) - (w20_b.get("avg_towers") or 5.0)
    score = 1.25 * win + 0.035 * kills - 0.03 * deaths + 0.00018 * gd15 + 0.00008 * dpm + 0.07 * towers
    return sigmoid(score)


def upsert_upcoming_features(**kwargs: Any) -> None:
    with transaction() as connection:
        connection.execute(
            """
            INSERT INTO upcoming_match_features(
                canonical_match_id, feature_version, ratings_version, data_cutoff_at,
                team_a_golgg_name, team_b_golgg_name, feature_status, missing_reason,
                features_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(canonical_match_id, feature_version, ratings_version) DO UPDATE SET
                data_cutoff_at = excluded.data_cutoff_at,
                team_a_golgg_name = excluded.team_a_golgg_name,
                team_b_golgg_name = excluded.team_b_golgg_name,
                feature_status = excluded.feature_status,
                missing_reason = excluded.missing_reason,
                features_json = excluded.features_json
            """,
            (
                kwargs["canonical_match_id"],
                kwargs["feature_version"],
                kwargs["ratings_version"],
                kwargs["data_cutoff_at"],
                kwargs["team_a_golgg_name"],
                kwargs["team_b_golgg_name"],
                kwargs["feature_status"],
                kwargs["missing_reason"],
                json.dumps(kwargs["features"], ensure_ascii=False, sort_keys=True),
            ),
        )


def latest_data_cutoff(ratings_version: str, w20_version: str) -> str | None:
    rating = query_df("SELECT data_cutoff_at FROM rating_runs WHERE ratings_version = ?", (ratings_version,))
    if not rating.empty and rating.iloc[0].get("data_cutoff_at"):
        return str(rating.iloc[0]["data_cutoff_at"])
    w20 = query_df(
        "SELECT MAX(data_cutoff_at) AS data_cutoff_at FROM team_rolling_features WHERE feature_version = ?",
        (w20_version,),
    )
    if not w20.empty and w20.iloc[0].get("data_cutoff_at"):
        return str(w20.iloc[0]["data_cutoff_at"])
    return None


def register_operational_model(
    *,
    model_name: str = DEFAULT_MODEL_NAME,
    model_version: str = DEFAULT_MODEL_VERSION,
    feature_version: str = DEFAULT_FEATURE_VERSION,
    ratings_version: str = DEFAULT_RATINGS_VERSION,
) -> int:
    """Register one exact, immutable regional operational-model contract."""
    expected = (
        DEFAULT_MODEL_NAME,
        DEFAULT_MODEL_VERSION,
        DEFAULT_FEATURE_VERSION,
        DEFAULT_RATINGS_VERSION,
    )
    actual = (model_name, model_version, feature_version, ratings_version)
    if actual != expected:
        raise ValueError(
            "operational model contract must be "
            f"{expected!r}, got {actual!r}"
        )
    feature_schema = {
        "ratings": list(RATING_SYSTEMS),
        "player_ratings": list(RATING_SYSTEMS),
        "ratings_version": ratings_version,
        "regional_engine": REGIONAL_ENGINE,
        "regional_projection": {
            "source": "family-calibrated Glicko-2 posterior",
            "applies_to": list(RAW_RATING_SYSTEMS),
            "excluded_system": "gl",
        },
        "roster_source": "current team roster, refreshed from GOL.GG or manual confirmation",
        "w20_fields": list(W20_FIELDS),
        "formula": (
            "map_p = 0.70 * player_rating_consensus + 0.20 * "
            "team_rating_consensus + 0.10 * w20_probability; "
            "match_p = binomial_tail(map_p, best_of); no market input"
        ),
        "limitations": [
            "last-match roster fallback",
            "not confirmed upcoming rosters",
            "not the final EXP-039 Sym-Cal model",
        ],
    }
    params = {
        "player_rating_weight": 0.70,
        "team_rating_weight": 0.20,
        "w20_weight": 0.10,
        "map_probability_clip": [0.03, 0.97],
        "series_projection": "binomial_tail",
        "supported_best_of": [1, 3, 5, 7],
    }
    schema_json = json.dumps(feature_schema, ensure_ascii=False, sort_keys=True)
    params_json = json.dumps(params, ensure_ascii=False, sort_keys=True)
    with transaction() as connection:
        connection.execute(
            """
            INSERT INTO model_artifacts(
                model_name, model_version, feature_schema_json, model_params_json, status
            ) VALUES (?, ?, ?, ?, 'active')
            ON CONFLICT(model_name, model_version) DO NOTHING
            """,
            (model_name, model_version, schema_json, params_json),
        )
        row = connection.execute(
            """
            SELECT id, feature_schema_json, model_params_json, status
            FROM model_artifacts
            WHERE model_name = ? AND model_version = ?
            """,
            (model_name, model_version),
        ).fetchone()
    if row is None:
        raise RuntimeError("operational model artifact was not persisted")
    if (
        row["feature_schema_json"] != schema_json
        or row["model_params_json"] != params_json
        or row["status"] != "active"
    ):
        raise ValueError(
            f"existing operational artifact {model_name}/{model_version} does not match the ratings-v2 contract"
        )
    return int(row["id"])


def predict_all_upcoming(
    *,
    feature_version: str = DEFAULT_FEATURE_VERSION,
    ratings_version: str = DEFAULT_RATINGS_VERSION,
    model_name: str = DEFAULT_MODEL_NAME,
    model_version: str = DEFAULT_MODEL_VERSION,
    include_partial: bool = False,
) -> list[dict[str, Any]]:
    """Generate and store probabilities from latest upcoming feature rows."""

    model_artifact_id = register_operational_model(
        model_name=model_name,
        model_version=model_version,
        feature_version=feature_version,
        ratings_version=ratings_version,
    )
    params: list[Any] = [feature_version, ratings_version]
    status_filter = "AND feature_status = 'ready_player'"
    if include_partial:
        status_filter = "AND feature_status IN ('ready_player', 'ready_team', 'partial')"
    frame = query_df(
        f"""
        SELECT umf.*, cm.team_a_name, cm.team_b_name, cm.start_time_normalized, cm.league, cm.best_of
        FROM upcoming_match_features umf
        JOIN canonical_matches cm ON cm.id = umf.canonical_match_id
        WHERE feature_version = ? AND ratings_version = ? {status_filter}
        ORDER BY cm.start_time_normalized ASC
        """,
        tuple(params),
    )
    results: list[dict[str, Any]] = []
    with transaction() as connection:
        connection.execute(
            """
            UPDATE canonical_predictions
            SET prediction_status = 'stale'
            WHERE prediction_status = 'active' AND model_name = ? AND model_version = ?
            """,
            (model_name, model_version),
        )
        for row in frame.to_dict("records"):
            features = json.loads(row.get("features_json") or "{}")
            map_probability, diagnostics = predict_probability_from_features(features)
            prob_a = series_probability(map_probability, row.get("best_of"))
            cursor = connection.execute(
                """
                INSERT INTO canonical_predictions(
                    canonical_match_id, model_artifact_id, model_name, model_version, predicted_at,
                    prob_a, prob_b, features_version, ratings_version, data_cutoff_at, diagnostics_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                (
                    int(row["canonical_match_id"]),
                    model_artifact_id,
                    model_name,
                    model_version,
                    utc_now_iso(),
                    prob_a,
                    1.0 - prob_a,
                    feature_version,
                    ratings_version,
                    row.get("data_cutoff_at"),
                    json.dumps(
                        {
                            **diagnostics,
                            "map_win_probability": map_probability,
                            "series_win_probability": prob_a,
                            "best_of": _normalized_best_of(row.get("best_of")),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                ),
            )
            prediction_id = int(cursor.fetchone()["id"])
            results.append(
                {
                    "prediction_id": prediction_id,
                    "canonical_match_id": int(row["canonical_match_id"]),
                    "match": f"{row.get('team_a_name')} vs {row.get('team_b_name')}",
                    "prob_a": prob_a,
                    "prob_b": 1.0 - prob_a,
                    "diagnostics": diagnostics,
                }
            )
    return results


def _normalized_best_of(best_of: Any) -> int:
    """Validate supported series lengths; an absent format is a single map."""

    try:
        value = 1 if best_of is None else int(best_of)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"best_of must be one of 1, 3, 5, 7; got {best_of!r}"
        ) from error
    if value not in {1, 3, 5, 7}:
        raise ValueError(f"best_of must be one of 1, 3, 5, 7; got {best_of!r}")
    return value


def series_probability(
    map_probability: float,
    best_of: Any,
    *,
    team_a_has_priority: bool | None = None,
    blue_side_bonus: float = 0.22,
) -> float:
    """Convert a per-map probability to a BoN series probability.

    A bracket forecast normally has no verified game-one side-selection data.
    In that case average both possible priority assignments; this preserves
    team-side symmetry instead of granting an arbitrary advantage to team A.
    """

    maps = _normalized_best_of(best_of)
    probability = max(1e-6, min(1.0 - 1e-6, float(map_probability)))
    if maps == 1:
        return probability

    from betting_app.ml.models.markov_series import predict_series_proba

    def predict(priority: bool) -> float:
        return float(
            predict_series_proba(
                probability,
                priority,
                best_of=maps,
                blue_side_bonus=blue_side_bonus,
            )
        )

    if team_a_has_priority is not None:
        return predict(team_a_has_priority)
    return (predict(True) + predict(False)) / 2.0

def predict_operational_match(
    match: dict[str, Any],
    *,
    feature_version: str = DEFAULT_FEATURE_VERSION,
    ratings_version: str = DEFAULT_RATINGS_VERSION,
    w20_version: str = DEFAULT_W20_VERSION,
    model_name: str = DEFAULT_MODEL_NAME,
    model_version: str = DEFAULT_MODEL_VERSION,
    include_partial: bool = True,
    team_a_roster_override: dict[str, Any] | None = None,
    team_b_roster_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build and store one operational match prediction without touching others."""
    feature_result = build_features_for_match(
        match,
        feature_version=feature_version,
        ratings_version=ratings_version,
        w20_version=w20_version,
        min_mapping_confidence=0.72,
        team_a_roster_override=team_a_roster_override,
        team_b_roster_override=team_b_roster_override,
    )
    if feature_result["status"] != "ready_player" and not include_partial:
        raise ValueError(
            "operational prediction requires ready player features: "
            + "; ".join(feature_result["missing"])
        )
    map_probability, diagnostics = predict_probability_from_features(feature_result["features"])
    best_of = _normalized_best_of(match.get("best_of"))
    probability = series_probability(map_probability, best_of)
    diagnostics = {
        **diagnostics,
        "map_win_probability": map_probability,
        "series_win_probability": probability,
        "best_of": best_of,
        "prediction_mode": "single-match-operational",
    }
    artifact_id = register_operational_model(
        model_name=model_name,
        model_version=model_version,
        feature_version=feature_version,
        ratings_version=ratings_version,
    )
    canonical_match_id = int(match["id"])
    now = utc_now_iso()
    with transaction() as connection:
        connection.execute(
            """
            UPDATE canonical_predictions
            SET prediction_status = 'stale'
            WHERE canonical_match_id = ? AND prediction_status = 'active'
              AND model_name = ? AND model_version = ?
            """,
            (canonical_match_id, model_name, model_version),
        )
        cursor = connection.execute(
            """
            INSERT INTO canonical_predictions(
                canonical_match_id, model_artifact_id, model_name, model_version,
                predicted_at, prob_a, prob_b, prediction_status, features_version,
                ratings_version, data_cutoff_at, diagnostics_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
            RETURNING id
            """,
            (
                canonical_match_id,
                artifact_id,
                model_name,
                model_version,
                now,
                probability,
                1.0 - probability,
                feature_version,
                ratings_version,
                feature_result["data_cutoff_at"],
                json.dumps(diagnostics, ensure_ascii=False, sort_keys=True),
            ),
        )
        prediction_id = int(cursor.fetchone()["id"])
    return {
        "prediction_id": prediction_id,
        "canonical_match_id": canonical_match_id,
        "prob_a": probability,
        "prob_b": 1.0 - probability,
        "diagnostics": diagnostics,
        "feature_status": feature_result["status"],
    }


def predict_probability_from_features(features: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    player_probs = features.get("player_ratings", {}).get("probabilities", {}) or {}
    player_consensus = player_probs.get("consensus")
    rating_probs = features.get("ratings", {}).get("probabilities", {}) or {}
    team_consensus = rating_probs.get("consensus")
    w20_prob = features.get("w20", {}).get("probability")
    components: dict[str, Any] = {
        "player_rating_consensus": player_consensus,
        "team_rating_consensus": team_consensus,
        "w20_probability": w20_prob,
    }
    weighted_components: list[tuple[str, float, float]] = []
    if player_consensus is not None:
        weighted_components.append(("player_ratings", 0.70, float(player_consensus)))
    if team_consensus is not None:
        weighted_components.append(("team_ratings", 0.20, float(team_consensus)))
    if w20_prob is not None:
        weighted_components.append(("w20", 0.10, float(w20_prob)))
    if not weighted_components:
        return 0.5, {**components, "fallback": "neutral_no_features"}
    total_weight = sum(weight for _, weight, _ in weighted_components)
    weights = {name: weight / total_weight for name, weight, _ in weighted_components}
    raw = sum((weight / total_weight) * value for name, weight, value in weighted_components)
    prob = max(0.03, min(0.97, raw))
    return prob, {**components, "weights": weights, "raw_probability": raw, "clipped_probability": prob}


def generate_hybrid_predictions(
    *,
    base_model_name: str = DEFAULT_MODEL_NAME,
    base_model_version: str = DEFAULT_MODEL_VERSION,
    alpha: float = DEFAULT_HYBRID_ALPHA,
    temperature: float = DEFAULT_HYBRID_TEMPERATURE,
    hybrid_model_name: str = DEFAULT_HYBRID_MODEL_NAME,
    hybrid_model_version: str | None = None,
) -> list[dict[str, Any]]:
    """Blend latest model probabilities with average no-vig bookmaker market.

    Formula mirrors the thesis financial experiments:

    ``p_hybrid = alpha * temperature(model_prob, T) + (1-alpha) * p_market``.
    """

    if not 0 <= alpha <= 1:
        raise ValueError("alpha must be in [0, 1]")
    if hybrid_model_version is None:
        hybrid_model_version = (
            f"{base_model_version}-a{alpha:.2f}-t{temperature:.2f}"
        )
    model_artifact_id = register_hybrid_model(
        base_model_name=base_model_name,
        base_model_version=base_model_version,
        alpha=alpha,
        temperature=temperature,
        model_name=hybrid_model_name,
        version=hybrid_model_version,
    )
    rows = query_df(
        """
        WITH latest_predictions AS (
            SELECT p.*
            FROM canonical_predictions p
            JOIN (
                SELECT canonical_match_id, model_name, model_version, MAX(predicted_at) AS predicted_at
                FROM canonical_predictions
                WHERE prediction_status = 'active' AND model_name = ? AND model_version = ?
                GROUP BY canonical_match_id, model_name, model_version
            ) lp ON lp.canonical_match_id = p.canonical_match_id
                AND lp.model_name = p.model_name
                AND lp.model_version = p.model_version
                AND lp.predicted_at = p.predicted_at
        ), latest_odds AS (
            SELECT os.*
            FROM odds_snapshots os
            JOIN (
                SELECT canonical_match_id, bookmaker_id, MAX(scraped_at) AS scraped_at
                FROM odds_snapshots
                WHERE market_type = 'match_winner' AND COALESCE(is_live, 0) = 0
                GROUP BY canonical_match_id, bookmaker_id
            ) lo ON lo.canonical_match_id = os.canonical_match_id
                 AND lo.bookmaker_id = os.bookmaker_id
                 AND lo.scraped_at = os.scraped_at
        )
        SELECT lp.id AS base_prediction_id, lp.canonical_match_id, lp.prob_a AS model_prob_a,
               lp.features_version, lp.ratings_version, lp.data_cutoff_at,
               cm.normalized_team_a, cm.normalized_team_b,
               os.raw_team_a, os.raw_team_b, os.odds_a, os.odds_b
        FROM latest_predictions lp
        JOIN canonical_matches cm ON cm.id = lp.canonical_match_id
        JOIN latest_odds os ON os.canonical_match_id = lp.canonical_match_id
        """,
        (base_model_name, base_model_version),
    )
    if rows.empty:
        return []
    results: list[dict[str, Any]] = []
    with transaction() as connection:
        connection.execute(
            """
            UPDATE canonical_predictions
            SET prediction_status = 'stale'
            WHERE prediction_status = 'active' AND model_name = ? AND model_version = ?
            """,
            (hybrid_model_name, hybrid_model_version),
        )
        for canonical_match_id, group in rows.groupby("canonical_match_id"):
            market_probs: list[float] = []
            first = group.iloc[0].to_dict()
            for row in group.to_dict("records"):
                aligned = align_snapshot_odds(
                    str(row.get("normalized_team_a") or ""),
                    str(row.get("normalized_team_b") or ""),
                    str(row.get("raw_team_a") or ""),
                    str(row.get("raw_team_b") or ""),
                    row.get("odds_a"),
                    row.get("odds_b"),
                )
                if aligned is None:
                    continue
                odds_a, odds_b = aligned
                if odds_a is None or odds_b is None or float(odds_a) <= 1.0 or float(odds_b) <= 1.0:
                    continue
                market_a, _ = fair_market_probabilities(float(odds_a), float(odds_b))
                market_probs.append(market_a)
            if not market_probs:
                continue
            model_prob = float(first["model_prob_a"])
            model_t = apply_temperature_probability(model_prob, temperature)
            market_prob = sum(market_probs) / len(market_probs)
            hybrid_prob = max(0.001, min(0.999, alpha * model_t + (1.0 - alpha) * market_prob))
            diagnostics = {
                "base_model_name": base_model_name,
                "base_model_version": base_model_version,
                "base_prediction_id": int(first["base_prediction_id"]),
                "alpha": alpha,
                "temperature": temperature,
                "model_prob_a": model_prob,
                "model_prob_a_temperature": model_t,
                "market_prob_a_avg_no_vig": market_prob,
                "bookmakers_used": len(market_probs),
                "formula": "alpha * temp(model) + (1-alpha) * average_no_vig_market",
            }
            cursor = connection.execute(
                """
                INSERT INTO canonical_predictions(
                    canonical_match_id, model_artifact_id, model_name, model_version, predicted_at,
                    prob_a, prob_b, features_version, ratings_version, data_cutoff_at, diagnostics_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(canonical_match_id),
                    model_artifact_id,
                    hybrid_model_name,
                    hybrid_model_version,
                    utc_now_iso(),
                    hybrid_prob,
                    1.0 - hybrid_prob,
                    first.get("features_version"),
                    first.get("ratings_version"),
                    first.get("data_cutoff_at"),
                    json.dumps(diagnostics, ensure_ascii=False, sort_keys=True),
                ),
            )
            results.append(
                {
                    "prediction_id": int(cursor.lastrowid),
                    "canonical_match_id": int(canonical_match_id),
                    "prob_a": hybrid_prob,
                    "prob_b": 1.0 - hybrid_prob,
                    "diagnostics": diagnostics,
                }
            )
    return results


def register_hybrid_model(
    *,
    base_model_name: str,
    base_model_version: str,
    alpha: float,
    temperature: float,
    model_name: str,
    version: str,
) -> int:
    feature_schema = {
        "base_model": f"{base_model_name}/{base_model_version}",
        "market_signal": "average no-vig probability from latest bookmaker odds",
        "formula": "alpha * temperature(base_model_probability) + (1-alpha) * market_probability",
        "historical_reference": "EXP-032/EXP-033/EXP-041 model-market hybrid experiments",
    }
    params = {"alpha": alpha, "temperature": temperature}
    schema_json = json.dumps(feature_schema, ensure_ascii=False, sort_keys=True)
    params_json = json.dumps(params, ensure_ascii=False, sort_keys=True)
    with transaction() as connection:
        connection.execute(
            """
            INSERT INTO model_artifacts(
                model_name, model_version, feature_schema_json, model_params_json, status
            ) VALUES (?, ?, ?, ?, 'active')
            ON CONFLICT(model_name, model_version) DO NOTHING
            """,
            (model_name, version, schema_json, params_json),
        )
        row = connection.execute(
            """
            SELECT id, feature_schema_json, model_params_json, status
            FROM model_artifacts
            WHERE model_name = ? AND model_version = ?
            """,
            (model_name, version),
        ).fetchone()
    if row is None:
        raise RuntimeError("hybrid model artifact was not persisted")
    if (
        row["feature_schema_json"] != schema_json
        or row["model_params_json"] != params_json
        or row["status"] != "active"
    ):
        raise ValueError(
            f"existing hybrid artifact {model_name}/{version} does not match its base-model contract"
        )
    return int(row["id"])

def generate_model_ev_signals(
    *,
    model_name: str = DEFAULT_MODEL_NAME,
    model_version: str = DEFAULT_MODEL_VERSION,
    tax_rate: float = 0.12,
    min_ev: float = 0.0,
    bankroll: float = 100.0,
) -> list[dict[str, Any]]:
    """Generate EV rows for latest predictions and latest odds per bookmaker."""

    rows = query_df(
        """
        WITH latest_predictions AS (
            SELECT p.*
            FROM canonical_predictions p
            JOIN (
                SELECT canonical_match_id, model_name, model_version, MAX(predicted_at) AS predicted_at
                FROM canonical_predictions
                WHERE prediction_status = 'active' AND model_name = ? AND model_version = ?
                GROUP BY canonical_match_id, model_name, model_version
            ) lp ON lp.canonical_match_id = p.canonical_match_id
                AND lp.model_name = p.model_name
                AND lp.model_version = p.model_version
                AND lp.predicted_at = p.predicted_at
        ), latest_odds AS (
            SELECT os.*
            FROM odds_snapshots os
            JOIN (
                SELECT canonical_match_id, bookmaker_id, MAX(scraped_at) AS scraped_at
                FROM odds_snapshots
                WHERE market_type = 'match_winner' AND COALESCE(is_live, 0) = 0
                GROUP BY canonical_match_id, bookmaker_id
            ) lo ON lo.canonical_match_id = os.canonical_match_id
                 AND lo.bookmaker_id = os.bookmaker_id
                 AND lo.scraped_at = os.scraped_at
        )
        SELECT lp.id AS prediction_id, lp.canonical_match_id, lp.prob_a, lp.prob_b,
               lp.diagnostics_json,
               cm.team_a_name, cm.team_b_name, cm.normalized_team_a, cm.normalized_team_b,
               os.id AS odds_snapshot_id, os.bookmaker_id, b.name AS bookmaker,
               os.raw_team_a, os.raw_team_b, os.odds_a, os.odds_b, os.offer_url, os.scraped_at
        FROM latest_predictions lp
        JOIN canonical_matches cm ON cm.id = lp.canonical_match_id
        JOIN latest_odds os ON os.canonical_match_id = lp.canonical_match_id
        JOIN bookmakers b ON b.id = os.bookmaker_id
        """,
        (model_name, model_version),
    )
    generated: list[dict[str, Any]] = []
    with transaction() as connection:
        connection.execute(
            """
            UPDATE model_ev_signals
            SET status = 'stale'
            WHERE status = 'new' AND canonical_prediction_id IN (
                SELECT id FROM canonical_predictions WHERE model_name = ? AND model_version = ?
            )
            """,
            (model_name, model_version),
        )
        for row in rows.to_dict("records"):
            # Skip rows without odds_snapshot_id (no matching odds found)
            if row.get("odds_snapshot_id") is None:
                continue
            aligned = align_snapshot_odds(
                str(row.get("normalized_team_a") or ""),
                str(row.get("normalized_team_b") or ""),
                str(row.get("raw_team_a") or ""),
                str(row.get("raw_team_b") or ""),
                row.get("odds_a"),
                row.get("odds_b"),
            )
            if aligned is None:
                continue
            odds_a, odds_b = aligned
            if odds_a is None or odds_b is None or float(odds_a) <= 1.0 or float(odds_b) <= 1.0:
                continue
            odds_a = float(odds_a)
            odds_b = float(odds_b)
            market_a, market_b = fair_market_probabilities(odds_a, odds_b)
            candidates = [
                ("a", float(row["prob_a"]), odds_a, market_a),
                ("b", float(row["prob_b"]), odds_b, market_b),
            ]
            for side, prob, odds, market_prob in candidates:
                bounds = conformal_bounds_for_side(
                    row.get("diagnostics_json"), side
                )
                if bounds is None:
                    continue
                p_low, p_upper = bounds
                # The contract's uncertainty threshold matches
                # ConformalRiskGater; heuristic probability haircuts are not
                # a substitute for a calibrated interval.
                if p_upper - p_low > 0.08:
                    continue
                ev = expected_value(prob, odds, tax_rate)
                ev_conformal = expected_value(p_low, odds, tax_rate)
                if ev_conformal < min_ev:
                    continue
                stake = fractional_kelly_stake(
                    bankroll,
                    p_low,
                    odds,
                    fraction=0.25,
                    tax_rate=tax_rate,
                )
                cursor = connection.execute(
                    """
                    INSERT INTO model_ev_signals(
                        canonical_match_id, canonical_prediction_id, odds_snapshot_id, bookmaker_id,
                        side, odds, model_prob, market_prob, ev, tax_rate, stake_suggestion, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new')
                    """,
                    (
                        int(row["canonical_match_id"]),
                        int(row["prediction_id"]),
                        int(row["odds_snapshot_id"]),
                        int(row["bookmaker_id"]),
                        side,
                        odds,
                        prob,
                        market_prob,
                        ev_conformal,
                        tax_rate,
                        stake,
                    ),
                )
                generated.append(
                    {
                        "signal_id": int(cursor.lastrowid),
                        "canonical_match_id": int(row["canonical_match_id"]),
                        "match": f"{row.get('team_a_name')} vs {row.get('team_b_name')}",
                        "bookmaker": row.get("bookmaker"),
                        "side": side,
                        "odds": odds,
                        "model_prob": prob,
                        "market_prob": market_prob,
                        "ev": ev_conformal,
                        "stake_suggestion": stake,
                        "offer_url": row.get("offer_url"),
                    }
                )
    return sorted(generated, key=lambda item: item["ev"], reverse=True)


def none_or_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if math.isnan(float(value)):
            return None
    except (TypeError, ValueError):
        return None
    return float(value)
