#!/usr/bin/env python3
"""Materialize the immutable ``ratings-v2`` regional multi-rating snapshot.

The snapshot shares one chronological match cohort across all six public systems:
Elo, family-calibrated Glicko-2 (``gl``), TrueSkill, OpenSkill,
Plackett-Luce, and Thurstone-Mosteller.  The ``gl`` state is the sole
regional posterior; inference projects that posterior onto the five raw
systems exactly once for cross-family predictions.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from typing import Any, Sequence

from betting_app.scripts import rebuild_calibrated_ratings as calibrated
from betting_app.scripts import rebuild_ratings as raw
from src.ratings.manager import RatingManager

RATINGS_VERSION = "ratings-v2"
DEFAULT_SOURCE = "regional-ratings-v2"
REGIONAL_ENGINE = "family-calibrated-glicko2-v1"
RAW_SYSTEMS = ("elo", "ts", "os", "pl", "tm")
PUBLIC_SYSTEMS = ("elo", "gl", "ts", "os", "pl", "tm")


def _raw_rows(
    *,
    manager: RatingManager,
    metadata: calibrated.RebuildMetadata,
    run_id: int,
    version: str,
    snapshot_at: str,
) -> list[tuple[Any, ...]]:
    """Serialize non-Glicko systems against calibrated roster metadata."""
    rows: list[tuple[Any, ...]] = []
    for system_name in RAW_SYSTEMS:
        system = manager.systems[system_name]
        for team_id, rating in sorted(system.team_ratings.items()):
            team_key = str(team_id)
            team_name = metadata.team_names[team_key]
            rows.append(
                raw.entity_rating_row(
                    run_id,
                    version,
                    snapshot_at,
                    "team",
                    team_name,
                    calibrated.normalize_team_name(team_name),
                    team_name,
                    None,
                    system_name,
                    rating,
                    metadata.team_games[team_key],
                    metadata.team_last_activity.get(team_key),
                    {"team_id": team_key},
                )
            )
        for player_id, rating in sorted(system.player_ratings.items()):
            player_key = str(player_id)
            team_id = metadata.player_team_ids.get(player_key)
            team_name = metadata.team_names.get(team_id, team_id) if team_id else None
            rows.append(
                raw.entity_rating_row(
                    run_id,
                    version,
                    snapshot_at,
                    "player",
                    metadata.player_names[player_key],
                    player_key,
                    team_name,
                    metadata.player_roles.get(player_key),
                    system_name,
                    rating,
                    metadata.player_games[player_key],
                    metadata.player_last_activity.get(player_key),
                    {"player_id": player_key},
                )
            )
    return rows


def _replay_raw_systems(
    matches: Sequence[calibrated.LoadedMatch],
) -> RatingManager:
    """Replay the same complete-date ordered matches used by regional Glicko."""
    manager = RatingManager(raw.RATING_SYSTEM_PARAMS)
    for match in matches:
        players_a = [player.player_id for player in match.players_a]
        players_b = [player.player_id for player in match.players_b]
        for score_a in match.scores:
            for system_name in RAW_SYSTEMS:
                system = manager.systems[system_name]
                system.update_team(
                    match.team_a_id,
                    match.team_b_id,
                    score_a,
                    1 - score_a,
                )
                system.update_player(
                    players_a,
                    players_b,
                    score_a,
                    1 - score_a,
                )
    return manager


def _systems_payload(
    *,
    engine: calibrated.FamilyCalibratedGlicko2,
    metadata: calibrated.RebuildMetadata,
    checkpoint: dict[str, Any],
) -> dict[str, Any]:
    return {
        "contract_version": RATINGS_VERSION,
        "public_systems": list(PUBLIC_SYSTEMS),
        "raw_systems": {
            system: raw.RATING_SYSTEM_PARAMS[system] for system in RAW_SYSTEMS
        },
        "gl": {
            "engine": REGIONAL_ENGINE,
            "parameters": calibrated.SYSTEM_PARAMETERS,
            "state": engine.to_state(),
            "metadata": metadata.to_state(),
            "checkpoint": checkpoint,
        },
    }


def _validate_rows(rows: Sequence[tuple[Any, ...]]) -> None:
    systems = {str(row[8]) for row in rows}
    if systems != set(PUBLIC_SYSTEMS):
        raise RuntimeError(
            "ratings-v2 materialization has an invalid public system set: "
            f"{sorted(systems)!r}"
        )
    identities = {(str(row[3]), str(row[5])) for row in rows if row[8] == "gl"}
    for system in RAW_SYSTEMS:
        current = {(str(row[3]), str(row[5])) for row in rows if row[8] == system}
        if current != identities:
            raise RuntimeError(
                f"ratings-v2 {system} rows do not match the regional Glicko cohort"
            )


def rebuild_regional_ratings(
    *,
    version: str = RATINGS_VERSION,
    source: str = DEFAULT_SOURCE,
    until_date: str | None = None,
) -> dict[str, Any]:
    """Fully replay and atomically replace a regional multi-rating snapshot.

    Partial and incremental rebuilds are intentionally unsupported: every public
    rating system must have the same cohort and regional posterior.
    """
    if version != RATINGS_VERSION:
        raise ValueError(
            f"regional rebuild requires immutable version {RATINGS_VERSION!r}, got {version!r}"
        )
    if until_date is not None:
        date.fromisoformat(until_date)

    start = calibrated._start_run(version, source)
    try:
        matches = calibrated.load_matches(until_date=until_date)
        if not matches:
            raise ValueError("regional ratings rebuild found no eligible matches")
        engine = calibrated.FamilyCalibratedGlicko2()
        metadata = calibrated.RebuildMetadata()
        checkpoint = calibrated.process_matches(engine, metadata, matches)
        if checkpoint is None:
            raise RuntimeError("regional ratings rebuild did not produce a cutoff checkpoint")
        raw_manager = _replay_raw_systems(matches)
        cutoff = max(match.event_date for match in matches).isoformat()
        rows = calibrated.materialize_entity_rows(
            engine=engine,
            metadata=metadata,
            run_id=start.run_id,
            version=version,
            snapshot_at=cutoff,
            rating_system="gl",
            competition_calibration=REGIONAL_ENGINE,
        )
        rows.extend(
            _raw_rows(
                manager=raw_manager,
                metadata=metadata,
                run_id=start.run_id,
                version=version,
                snapshot_at=cutoff,
            )
        )
        _validate_rows(rows)
        calibrated._commit_snapshot(
            start=start,
            version=version,
            source=source,
            cutoff=cutoff,
            rows=rows,
            systems_json=json.dumps(
                _systems_payload(
                    engine=engine, metadata=metadata, checkpoint=checkpoint
                ),
                ensure_ascii=False,
                sort_keys=True,
            ),
            metadata=metadata,
            players_processed=len(tuple(engine.player_ids)),
        )
    except Exception as error:
        calibrated._record_failure(start, error)
        raise

    return {
        "version": version,
        "mode": "full",
        "matches": len(matches),
        "games": sum(len(match.scores) for match in matches),
        "players": len(tuple(engine.player_ids)),
        "entities": len({(str(row[3]), str(row[5])) for row in rows}),
        "rows": len(rows),
        "data_cutoff_at": cutoff,
    }


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--until", dest="until_date", help="Include complete dates through YYYY-MM-DD.")
    parser.add_argument("--ratings-version", default=RATINGS_VERSION)
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    args = parser.parse_args(argv)
    stats = rebuild_regional_ratings(
        version=args.ratings_version,
        source=args.source,
        until_date=args.until_date,
    )
    print(
        "Rebuilt regional ratings:",
        f"version={stats['version']}",
        f"matches={stats['matches']}",
        f"games={stats['games']}",
        f"players={stats['players']}",
        f"rows={stats['rows']}",
        f"cutoff={stats['data_cutoff_at']}",
    )


if __name__ == "__main__":
    main()
