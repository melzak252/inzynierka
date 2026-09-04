#!/usr/bin/env python3
"""Build the single ``ratings-v2`` snapshot used by the regional successor.

The snapshot contains one row per raw Elo/TrueSkill/OpenSkill/Plackett--Luce/
Thurstone system and exactly one ``gl`` row produced by FamilyCalibratedGlicko2.
Regional location is learned once by the Glicko engine, then projected into the
other systems only when an upcoming matchup is built.

This intentionally performs a deterministic full rebuild.  The historical
source can receive late corrections on an already processed calendar date;
replaying all completed dates preserves the frozen-period Glicko invariant and
keeps every rating system in the same snapshot contract.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from betting_app.scripts.rebuild_calibrated_ratings import (
    RebuildMetadata,
    _commit_snapshot,
    _record_failure,
    _start_run,
    load_matches,
    materialize_entity_rows,
    process_matches,
)
from betting_app.scripts.rebuild_ratings import RATING_SYSTEM_PARAMS, entity_rating_rows
from src.ratings.family_calibrated_glicko2 import FamilyCalibratedGlicko2
from src.ratings.manager import RatingManager

REGIONAL_RATINGS_VERSION = "ratings-v2"
REGIONAL_SOURCE = "regional-ratings-v2"
RAW_RATING_SYSTEMS = ("elo", "ts", "os", "pl", "tm")
GLICKO_SYSTEM = "gl"
ALL_RATING_SYSTEMS = (*RAW_RATING_SYSTEMS, GLICKO_SYSTEM)


def _apply_raw_system_updates(
    manager: RatingManager,
    matches: Sequence[Any],
) -> None:
    """Replay local-skill updates without constructing a legacy Glicko state."""

    if GLICKO_SYSTEM in manager.systems:
        raise ValueError("regional snapshot must not construct legacy Glicko")
    for match in matches:
        players_a = [player.player_id for player in match.players_a]
        players_b = [player.player_id for player in match.players_b]
        manager.update_before_match(
            match.team_a_id,
            match.team_b_id,
            players_a,
            players_b,
            match.event_date,
        )
        for score_a in match.scores:
            manager.update_after_game(
                match.team_a_id,
                match.team_b_id,
                players_a,
                players_b,
                int(score_a),
                1 - int(score_a),
            )


def _raw_entity_rows(
    manager: RatingManager,
    metadata: RebuildMetadata,
    *,
    run_id: int,
    version: str,
    snapshot_at: str,
) -> list[tuple[Any, ...]]:
    player_teams = {
        player_id: metadata.team_names.get(team_id, team_id)
        for player_id, team_id in metadata.player_team_ids.items()
    }
    return entity_rating_rows(
        manager=manager,
        version=version,
        run_id=run_id,
        snapshot_at=snapshot_at,
        team_names=metadata.team_names,
        player_names=metadata.player_names,
        player_teams=player_teams,
        team_games=metadata.team_games,
        player_games=metadata.player_games,
        team_last_match=metadata.team_last_activity,
        player_last_match=metadata.player_last_activity,
    )


def _systems_payload(
    engine: FamilyCalibratedGlicko2,
    metadata: RebuildMetadata,
) -> str:
    """Persist the one contract and its one regional posterior for auditability."""

    return json.dumps(
        {
            "contract_version": REGIONAL_RATINGS_VERSION,
            "raw_systems": {
                name: {"parameters": RATING_SYSTEM_PARAMS[name], "regional_projection": "shared"}
                for name in RAW_RATING_SYSTEMS
            },
            GLICKO_SYSTEM: {
                "engine": "family-calibrated-glicko2-v1",
                "state": engine.to_state(),
                "metadata": metadata.to_state(),
                "regional_projection": "source_of_truth",
            },
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def rebuild_regional_ratings(
    *,
    version: str = REGIONAL_RATINGS_VERSION,
    source: str = REGIONAL_SOURCE,
    until_date: str | None = None,
) -> dict[str, Any]:
    """Atomically replace one complete unified regional ratings snapshot."""

    if until_date is not None:
        date.fromisoformat(until_date)
    start = _start_run(version, source)
    try:
        matches = load_matches(until_date=until_date)
        if not matches:
            raise ValueError("regional ratings rebuild found no eligible matches")

        regional_glicko = FamilyCalibratedGlicko2()
        metadata = RebuildMetadata()
        process_matches(regional_glicko, metadata, matches)

        raw_manager = RatingManager(RATING_SYSTEM_PARAMS, include_glicko=False)
        _apply_raw_system_updates(raw_manager, matches)
        cutoff = max(match.event_date for match in matches).isoformat()
        raw_rows = _raw_entity_rows(
            raw_manager,
            metadata,
            run_id=start.run_id,
            version=version,
            snapshot_at=cutoff,
        )
        regional_gl_rows = materialize_entity_rows(
            engine=regional_glicko,
            metadata=metadata,
            run_id=start.run_id,
            version=version,
            snapshot_at=cutoff,
            rating_system=GLICKO_SYSTEM,
        )
        rows = [*raw_rows, *regional_gl_rows]
        systems = {str(row[8]) for row in rows}
        if systems != set(ALL_RATING_SYSTEMS):
            raise RuntimeError(f"unified snapshot has unexpected rating systems: {sorted(systems)}")

        _commit_snapshot(
            start=start,
            version=version,
            source=source,
            cutoff=cutoff,
            rows=rows,
            systems_json=_systems_payload(regional_glicko, metadata),
            metadata=metadata,
            players_processed=len(regional_glicko.player_ids),
        )
    except Exception as error:
        _record_failure(start, error)
        raise

    return {
        "version": version,
        "matches": len(matches),
        "games": sum(len(match.scores) for match in matches),
        "players": len(regional_glicko.player_ids),
        "entities": len(rows),
        "rows": len(rows),
        "data_cutoff_at": cutoff,
        "rating_systems": list(ALL_RATING_SYSTEMS),
    }


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--until", dest="until_date", help="Include complete dates through YYYY-MM-DD.")
    parser.add_argument("--ratings-version", default=REGIONAL_RATINGS_VERSION)
    parser.add_argument("--source", default=REGIONAL_SOURCE)
    args = parser.parse_args(argv)
    stats = rebuild_regional_ratings(
        version=args.ratings_version,
        source=args.source,
        until_date=args.until_date,
    )
    print(
        "Rebuilt unified regional ratings:",
        f"version={stats['version']}",
        f"matches={stats['matches']}",
        f"games={stats['games']}",
        f"players={stats['players']}",
        f"rows={stats['rows']}",
        f"cutoff={stats['data_cutoff_at']}",
    )


if __name__ == "__main__":
    main()
