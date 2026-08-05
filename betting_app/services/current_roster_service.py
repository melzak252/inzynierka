"""Durable current team rosters, shared by GOL.GG ingestion and manual edits."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from betting_app.core.matching import normalize_team_name


ROLE_ORDER = {"TOP": 1, "JUNGLE": 2, "MID": 3, "ADC": 4, "SUPPORT": 5}


def upsert_current_roster(
    db: Any,
    *,
    team_name: str,
    players: list[dict[str, Any]],
    source: str,
    source_match_id: str | None = None,
    source_game_id: str | None = None,
    source_match_date: str | None = None,
    team_id: str | None = None,
) -> bool:
    """Replace a complete role roster if its source is newer than stored data.

    A manual confirmation is timestamped at confirmation time, so delayed
    historical imports cannot undo it.  A genuinely later GOL.GG match does
    replace it, which is exactly the desired automatic behaviour.
    """
    normalized = normalize_team_name(team_name)
    normalized_players = [
        {
            "player_id": str(player.get("player_id") or ""),
            "player_name": player.get("player_name"),
            "role": str(player.get("role") or "").upper(),
        }
        for player in players
        if player.get("player_id") and str(player.get("role") or "").upper() in ROLE_ORDER
    ]
    if len(normalized_players) != 5 or len({p["role"] for p in normalized_players}) != 5:
        return False
    stamp = source_match_date or datetime.now(UTC).isoformat()
    current = db.execute(
        text(
            """
            SELECT source_match_date FROM team_current_roster_players
            WHERE normalized_team_name=:normalized
            ORDER BY source_match_date DESC NULLS LAST LIMIT 1
            """
        ),
        {"normalized": normalized},
    ).mappings().first()
    if current and current.get("source_match_date") and str(current["source_match_date"]) > stamp:
        return False

    now = datetime.now(UTC).isoformat()
    for player in normalized_players:
        db.execute(
            text(
                """
                INSERT INTO team_current_roster_players(
                    team_id, team_name, normalized_team_name, player_id, player_name,
                    role, source, source_match_id, source_game_id, source_match_date, updated_at
                ) VALUES (
                    :team_id, :team_name, :normalized, :player_id, :player_name,
                    :role, :source, :source_match_id, :source_game_id, :source_match_date, :updated_at
                )
                ON CONFLICT (normalized_team_name, role) DO UPDATE SET
                    team_id=EXCLUDED.team_id, team_name=EXCLUDED.team_name,
                    player_id=EXCLUDED.player_id, player_name=EXCLUDED.player_name,
                    source=EXCLUDED.source, source_match_id=EXCLUDED.source_match_id,
                    source_game_id=EXCLUDED.source_game_id, source_match_date=EXCLUDED.source_match_date,
                    updated_at=EXCLUDED.updated_at
                """
            ),
            {**player, "team_id": team_id, "team_name": team_name, "normalized": normalized,
             "source": source, "source_match_id": source_match_id, "source_game_id": source_game_id,
             "source_match_date": stamp, "updated_at": now},
        )
    return True
