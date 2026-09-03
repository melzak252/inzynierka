"""Read-only team and player rating leaderboards."""

from __future__ import annotations

import calendar
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query

from betting_app.api.deps import get_db, query_df, query_one
from betting_app.api.schemas import RankingEntry, RankingsResponse

router = APIRouter(tags=["rankings"])

RatingSystem = Literal["unified", "elo", "gl", "ts", "os", "pl", "tm"]
EntityType = Literal["team", "player"]
SquadScope = Literal["main", "development", "all"]


def _subtract_months(value: date, months: int) -> date:
    target_index = value.year * 12 + value.month - 1 - months
    year, zero_based_month = divmod(target_index, 12)
    month = zero_based_month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


@router.get("/rankings", response_model=RankingsResponse)
def get_rankings(
    entity_type: EntityType = "team",
    rating_system: RatingSystem = "unified",
    search: str | None = Query(default=None, max_length=100),
    min_games: int = Query(default=1, ge=0, le=10_000),
    active_within_months: int = Query(default=6, ge=0, le=120),
    squad_scope: SquadScope = "main",
    limit: int = Query(default=100, ge=1, le=500),
    db=Depends(get_db),
) -> RankingsResponse:
    """Return one leaderboard from the most recent completed rating run."""
    run = query_one(
        db,
        """
        SELECT ratings_version, data_cutoff_at
        FROM rating_runs
        WHERE status = 'completed'
        ORDER BY finished_at DESC NULLS LAST, id DESC
        LIMIT 1
        """,
    )
    if run is None:
        return RankingsResponse(
            entity_type=entity_type,
            rating_system=rating_system,
            total=0,
        )

    cutoff_date = date.fromisoformat(str(run["data_cutoff_at"])[:10])
    active_since = _subtract_months(cutoff_date, active_within_months) if active_within_months else None

    ratings_version = str(run["ratings_version"])
    available_rows = query_df(
        db,
        """
        SELECT DISTINCT rating_system
        FROM entity_ratings
        WHERE ratings_version = :ratings_version
          AND entity_type = :entity_type
          AND rating_value IS NOT NULL
        ORDER BY rating_system
        """,
        {"ratings_version": ratings_version, "entity_type": entity_type},
    )
    available_rating_systems = [str(row["rating_system"]) for row in available_rows]
    params: dict[str, object] = {
        "ratings_version": ratings_version,
        "entity_type": entity_type,
        "rating_system": rating_system,
        "min_games": min_games,
        "limit": limit,
    }
    cohort_filter = ""
    if active_since is not None:
        cohort_filter += " AND last_match_at IS NOT NULL AND SUBSTR(last_match_at, 1, 10) >= :active_since"
        params["active_since"] = active_since.isoformat()
    if squad_scope != "all":
        development_label = """
            LOWER(
                CASE
                    WHEN entity_type = 'team' THEN entity_name
                    ELSE COALESCE(team_name, '')
                END
            ) LIKE '%academy%'
            OR LOWER(
                CASE
                    WHEN entity_type = 'team' THEN entity_name
                    ELSE COALESCE(team_name, '')
                END
            ) LIKE '%challenger%'
            OR LOWER(
                CASE
                    WHEN entity_type = 'team' THEN entity_name
                    ELSE COALESCE(team_name, '')
                END
            ) LIKE '%youth%'
            OR LOWER(
                CASE
                    WHEN entity_type = 'team' THEN entity_name
                    ELSE COALESCE(team_name, '')
                END
            ) LIKE '%junior%'
            OR LOWER(
                CASE
                    WHEN entity_type = 'team' THEN entity_name
                    ELSE COALESCE(team_name, '')
                END
            ) LIKE '%development%'
        """
        cohort_filter += f" AND {'(' if squad_scope == 'development' else 'NOT ('}{development_label})"
    normalized_search = (search or "").strip().lower()
    search_filter = ""
    if normalized_search:
        search_filter = "WHERE LOWER(entity_name) LIKE :search"
        params["search"] = f"%{normalized_search}%"

    if rating_system == "unified":
        params["system_count"] = len(available_rating_systems)
        leaderboard_cte = f"""
            WITH system_positions AS (
                SELECT
                    entity_type,
                    entity_name,
                    normalized_entity_name,
                    team_name,
                    role,
                    rating_system,
                    games_played,
                    last_match_at,
                    snapshot_at,
                    RANK() OVER (
                        PARTITION BY rating_system
                        ORDER BY rating_value DESC, games_played DESC, normalized_entity_name ASC
                    ) AS system_rank,
                    COUNT(*) OVER (PARTITION BY rating_system) AS system_total
                FROM entity_ratings
                WHERE ratings_version = :ratings_version
                  AND entity_type = :entity_type
                  AND rating_value IS NOT NULL
                  AND games_played >= :min_games
                  {cohort_filter}
            ),
            consensus AS (
                SELECT
                    entity_type,
                    MAX(entity_name) AS entity_name,
                    normalized_entity_name,
                    MAX(team_name) AS team_name,
                    MAX(role) AS role,
                    'unified' AS rating_system,
                    AVG(
                        CASE
                            WHEN system_total = 1 THEN 100.0
                            ELSE 100.0 * (system_total - system_rank) / (system_total - 1)
                        END
                    ) AS rating_value,
                    NULL AS rd,
                    NULL AS sigma,
                    MIN(games_played) AS games_played,
                    MAX(last_match_at) AS last_match_at,
                    MAX(snapshot_at) AS snapshot_at,
                    COUNT(DISTINCT rating_system) AS system_count
                FROM system_positions
                GROUP BY entity_type, normalized_entity_name
                HAVING COUNT(DISTINCT rating_system) = :system_count
            ),
            ranked AS (
                SELECT
                    ROW_NUMBER() OVER (
                        ORDER BY rating_value DESC, games_played DESC, normalized_entity_name ASC
                    ) AS rank,
                    *
                FROM consensus
            )
        """
    else:
        leaderboard_cte = f"""
            WITH ranked AS (
                SELECT
                    ROW_NUMBER() OVER (
                        ORDER BY rating_value DESC, games_played DESC, normalized_entity_name ASC
                    ) AS rank,
                    entity_type,
                    entity_name,
                    normalized_entity_name,
                    team_name,
                    role,
                    rating_system,
                    rating_value,
                    rd,
                    sigma,
                    games_played,
                    last_match_at,
                    snapshot_at,
                    1 AS system_count
                FROM entity_ratings
                WHERE ratings_version = :ratings_version
                  AND entity_type = :entity_type
                  AND rating_system = :rating_system
                  AND rating_value IS NOT NULL
                  AND games_played >= :min_games
                  {cohort_filter}
            )
        """

    count = query_one(
        db,
        f"{leaderboard_cte} SELECT COUNT(*) AS total FROM ranked {search_filter}",
        params,
    )
    rows = query_df(
        db,
        f"""
        {leaderboard_cte}
        SELECT *
        FROM ranked
        {search_filter}
        ORDER BY rank
        LIMIT :limit
        """,
        params,
    )
    snapshot_at = next((str(row["snapshot_at"]) for row in rows if row.get("snapshot_at")), None)

    return RankingsResponse(
        entity_type=entity_type,
        rating_system=rating_system,
        ratings_version=ratings_version,
        data_cutoff_at=run.get("data_cutoff_at"),
        active_since=active_since.isoformat() if active_since else None,
        squad_scope=squad_scope,
        snapshot_at=snapshot_at,
        total=int(count["total"] if count else 0),
        available_rating_systems=available_rating_systems,
        rankings=[RankingEntry(**row) for row in rows],
    )
