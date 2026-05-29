"""Rebuild canonical cross-bookmaker match links for stored odds snapshots."""

from __future__ import annotations

import argparse

from betting_app.core.database import init_db, transaction
from betting_app.services.canonical_match_service import canonical_match_overview, resolve_canonical_match


def main() -> None:
    """CLI entrypoint."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Clear canonical_matches and rebuild all links from upcoming_matches from scratch.",
    )
    args = parser.parse_args()

    init_db()
    if args.rebuild:
        reset_canonical_matches()
    updated = rematch_odds_snapshots()
    print(f"Rematched odds snapshots: {updated}")
    overview = canonical_match_overview(limit=20)
    if not overview.empty:
        print(overview.to_string(index=False))


def rematch_odds_snapshots() -> int:
    """Resolve canonical_match_id for existing upcoming_matches and odds_snapshots."""

    with transaction() as connection:
        rows = connection.execute(
            """
            SELECT id, raw_team_a, raw_team_b, match_start_time, league
            FROM upcoming_matches
            """
        ).fetchall()
    updated = 0
    for row in rows:
        canonical_match_id = resolve_canonical_match(
            raw_team_a=row["raw_team_a"],
            raw_team_b=row["raw_team_b"],
            match_start_time=row["match_start_time"],
            league=row["league"],
        )
        with transaction() as connection:
            connection.execute(
                "UPDATE upcoming_matches SET canonical_match_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (canonical_match_id, row["id"]),
            )
            connection.execute(
                "UPDATE odds_snapshots SET canonical_match_id = ? WHERE match_id = ?",
                (canonical_match_id, row["id"]),
            )
            connection.execute(
                "UPDATE bookmaker_events SET canonical_match_id = ? WHERE match_id = ?",
                (canonical_match_id, row["id"]),
            )
        updated += 1
    return updated


def reset_canonical_matches() -> None:
    """Remove stale/duplicate canonical groups before a full rebuild."""

    with transaction() as connection:
        # Downstream objects reference canonical_matches.  They are rebuilt by
        # run_upcoming_prediction_pipeline immediately after rematching, so it
        # is safer to clear them than to keep predictions tied to stale IDs.
        connection.execute("DELETE FROM model_ev_signals")
        connection.execute("DELETE FROM canonical_predictions")
        connection.execute("DELETE FROM upcoming_match_features")
        connection.execute("UPDATE odds_snapshots SET canonical_match_id = NULL")
        connection.execute("UPDATE upcoming_matches SET canonical_match_id = NULL")
        connection.execute("UPDATE bookmaker_events SET canonical_match_id = NULL")
        connection.execute("DELETE FROM canonical_matches")


if __name__ == "__main__":
    main()
