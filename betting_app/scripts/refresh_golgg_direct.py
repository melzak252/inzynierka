"""Incrementally refresh finished GOL.GG matches directly into TimescaleDB.

Unlike refresh_golgg_results.py, this script skips the JSON cache entirely:
- Existing match IDs are read from the golgg_matches table
- Newly fetched match game data is written directly to the DB via import_golgg_batch()
- After import, newly added matches are auto-mapped to canonical_matches
  by date + team name proximity
- No golgg_matches.json file is read or written

Intended to be run periodically (every 6-12 hours) via the scheduler.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import logging

from betting_app.scrapers.golgg import GolggScraper

try:
    from tqdm.asyncio import tqdm
except ImportError:
    tqdm = None

# Reuse helpers from the JSON-based refresh script
from betting_app.scripts.refresh_golgg_results import (
    deduplicate_by_key,
    enrich_match_with_nested_game_metadata,
    expected_games_for_match,
    should_fetch_games,
    select_tournaments_to_fetch,
    get_tournament_matches,
    get_matches_with_games,
    CONCURRENCY_LIMIT as _REFRESH_CONCURRENCY,
)

# Import the DB writer
from betting_app.services.golgg_import_service import import_golgg_batch

# Import mapping for auto-match
from betting_app.services.mapping_service import suggest_mapping, load_golgg_team_candidates

# -------------------------------------------------------------------- #
#  Auto-mapping: link imported GOL.GG results to canonical_matches     #
# -------------------------------------------------------------------- #

def auto_map_new_matches(match_ids: list[str]) -> dict:
    """Find canonical_matches that correspond to newly imported golgg matches.

    For each golgg match ID, query the DB for the match's team names + date,
    then search canonical_matches for a match with the same teams (via suggest_mapping)
    and a nearby start_time_normalized.

    Returns a dict with stats about what was mapped.
    """
    from betting_app.core.db import query_df, get_session
    from sqlalchemy import text as _sql_text

    if not match_ids:
        return {"checked": 0, "mapped": 0, "already_mapped": 0, "errors": 0}

    # Build WHERE clause for match IDs
    import json as _json
    ids_str = ",".join(f"'{mid}'" for mid in match_ids)
    
    # Fetch newly imported golgg matches with team names + date
    df = query_df(f"""
        SELECT match_id, team1_name, team2_name, date, tournament_name
        FROM golgg_matches
        WHERE match_id IN ({ids_str})
    """)
    
    if df.empty:
        return {"checked": 0, "mapped": 0, "already_mapped": 0, "errors": 0}
    
    mapped = 0
    already_mapped = 0
    errors = 0
    checked = len(df)

    for _, row in df.iterrows():
        try:
            gmid = str(row["match_id"])
            team1 = str(row["team1_name"])
            team2 = str(row["team2_name"])
            match_date = str(row["date"]) if row.get("date") else ""
            tournament = str(row["tournament_name"]) if row.get("tournament_name") else ""

            # Check if already mapped
            existing = query_df(f"""
                SELECT id FROM golgg_match_mappings
                WHERE golgg_match_id = '{gmid}'
            """)
            if not existing.empty:
                already_mapped += 1
                continue

            # For each golgg team, find the mapped canonical name
            # try both orientations
            g1_canonical, _ = suggest_mapping(team1)
            g2_canonical, _ = suggest_mapping(team2)
            if not g1_canonical or not g2_canonical:
                errors += 1
                continue

            # Search canonical_matches for matching teams + nearby date
            # Normalize both sides using normalize_team_name() to ensure consistent
            # stop-word removal (e.g., "Team Liquid" → "liquid") and comparison
            # against canonical_matches.normalized_team_a (which was also normalized).
            # Try both orientations: (team_a, team_b) and (team_b, team_a)
            from betting_app.core.matching import normalize_team_name as _ntn
            start_date = match_date[:10] if len(match_date) >= 10 else match_date
            g1_lower = _ntn(g1_canonical).replace("'", "''")
            g2_lower = _ntn(g2_canonical).replace("'", "''")

            candidates = query_df(f"""
                SELECT id, normalized_team_a, normalized_team_b, 
                       start_time_normalized, league, status
                FROM canonical_matches
                WHERE (LOWER(normalized_team_a) = '{g1_lower}' 
                       AND LOWER(normalized_team_b) = '{g2_lower}')
                   OR (LOWER(normalized_team_a) = '{g2_lower}' 
                       AND LOWER(normalized_team_b) = '{g1_lower}')
            """)

            if candidates.empty:
                errors += 1
                continue

            # Pick the best match by date proximity
            best_id = None
            best_diff = 999999
            for _, c in candidates.iterrows():
                cid = c["id"]
                cdate = str(c.get("start_time_normalized", ""))[:10]
                if start_date and cdate:
                    try:
                        from datetime import datetime as _dt
                        gd = _dt.strptime(start_date, "%Y-%m-%d")
                        cd = _dt.strptime(cdate, "%Y-%m-%d") if cdate else gd
                        diff = abs((gd - cd).days)
                        if diff < best_diff:
                            best_diff = diff
                            best_id = cid
                    except ValueError:
                        if best_id is None:
                            best_id = cid

            if best_id is None:
                errors += 1
                continue

            # Create mapping record
            with get_session() as session:
                session.execute(_sql_text(f"""
                    INSERT INTO golgg_match_mappings 
                        (canonical_match_id, golgg_match_id, confidence, mapped_by)
                    VALUES ({best_id}, '{gmid}', 1.0, 'auto')
                    ON CONFLICT (golgg_match_id) DO NOTHING
                """))
                session.commit()
            mapped += 1

        except Exception as exc:
            logger.warning(f"Auto-map error for match_id {row.get('match_id')}: {exc}")
            errors += 1

    return {
        "checked": checked,
        "mapped": mapped,
        "already_mapped": already_mapped,
        "errors": errors,
    }


logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Incrementally refresh GOL.GG finished matches directly into TimescaleDB"
    )
    parser.add_argument("--max-pages", type=int, default=40)
    parser.add_argument("--concurrency", type=int, default=24)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument(
        "--refresh-matches",
        action="store_true",
        help="Fetch match lists for all tournaments instead of only tournaments with missing games.",
    )
    parser.add_argument(
        "--include-incomplete-existing",
        action="store_true",
        help="Also fetch games for existing matches whose nested games are incomplete.",
    )
    parser.add_argument(
        "--refetch-games",
        action="store_true",
        help="Refetch games for selected matches even if they already look complete.",
    )
    parser.add_argument("--match-id", help="Fetch/refetch only one match ID.")
    parser.add_argument("--dry-run", action="store_true", help="Discover missing matches but do not write to DB.")
    return parser.parse_args()


def load_db_match_ids() -> set[str]:
    """Return set of match_id strings already in golgg_matches."""
    from betting_app.core.db import query_df

    df = query_df("SELECT match_id FROM golgg_matches WHERE match_id IS NOT NULL")
    if df.empty:
        return set()
    return {str(row["match_id"]) for _, row in df.iterrows()}


def load_db_games_per_tournament() -> dict[str, int]:
    """Return dict of tournament_name -> nested game count from DB."""
    from betting_app.core.db import query_df

    df = query_df(
        """
        SELECT gm.tournament_name, COUNT(gg.game_id) AS game_count
        FROM golgg_matches gm
        LEFT JOIN golgg_games gg ON gg.match_id = gm.match_id
        GROUP BY gm.tournament_name
        """
    )
    if df.empty:
        return {}
    return {str(row["tournament_name"]): int(row["game_count"]) for _, row in df.iterrows()}


def load_db_games_per_match() -> dict[str, int]:
    """Return dict of match_id -> nested game count from DB."""
    from betting_app.core.db import query_df

    df = query_df(
        """
        SELECT gm.match_id, COUNT(gg.game_id) AS game_count
        FROM golgg_matches gm
        LEFT JOIN golgg_games gg ON gg.match_id = gm.match_id
        GROUP BY gm.match_id
        """
    )
    if df.empty:
        return {}
    return {str(row["match_id"]): int(row["game_count"]) for _, row in df.iterrows()}


async def fetch_and_save_games(
    scraper: GolggScraper,
    selected_matches: list[dict],
    *,
    batch_size: int,
    concurrency: int,
) -> int:
    """Fetch games for selected matches and write each batch directly to DB.

    Returns the total number of matches whose games were successfully written.
    """
    fetched_total = 0
    for start in range(0, len(selected_matches), batch_size):
        batch = selected_matches[start : start + batch_size]
        print(
            f"Fetching batch {start // batch_size + 1}: "
            f"{start + 1}-{start + len(batch)} / {len(selected_matches)}"
        )
        fetched_match_docs = await get_matches_with_games(batch, scraper, concurrency=concurrency)
        fetched_match_docs = [
            m for m in fetched_match_docs if m.get("match_id") and m.get("games")
        ]
        if not fetched_match_docs:
            print("  No game data fetched in this batch.")
            continue

        # Write directly to DB
        try:
            stats = import_golgg_batch(fetched_match_docs)
            fetched_total += len(fetched_match_docs)
            print(
                f"  DB insert OK: {stats['matches']} matches, "
                f"{stats['games']} games, {stats['players']} players"
            )
        except Exception as exc:
            print(f"  DB insert FAILED for batch: {exc}")
            # Re-raise so caller knows something went wrong
            raise

    return fetched_total


async def main() -> None:
    args = parse_args()

    print(f"[{datetime.now(timezone.utc).isoformat()}] Starting GOL.GG direct refresh...")

    # ------------------------------------------------------------------ #
    # 1. Load existing state from DB
    # ------------------------------------------------------------------ #
    print("Loading existing GOL.GG match IDs from TimescaleDB...")
    known_existing_ids = load_db_match_ids()
    games_per_tournament = load_db_games_per_tournament()
    games_per_match = load_db_games_per_match()
    total_games = sum(games_per_match.values())
    print(f"DB state: {len(known_existing_ids)} matches, {total_games} nested games")

    # ------------------------------------------------------------------ #
    # 2. Fetch tournament index and discover new matches
    # ------------------------------------------------------------------ #
    async with GolggScraper(max_pages=args.max_pages) as scraper:
        print("Fetching GOL.GG tournament index...")
        all_tournaments = await scraper.get_all_tournaments()
        tournaments_to_fetch = select_tournaments_to_fetch(
            all_tournaments,
            games_per_tournament,
            refresh_matches=args.refresh_matches,
        )
        print(
            f"Tournament lists to scan: {len(tournaments_to_fetch)} / {len(all_tournaments)} "
            "(only tournaments with missing/new games unless --refresh-matches)"
        )

        discovered_matches = (
            await get_tournament_matches(scraper, tournaments_to_fetch)
            if tournaments_to_fetch
            else []
        )
        new_matches = [
            match
            for match in deduplicate_by_key(discovered_matches, "match_id")
            if match.get("match_id") and str(match["match_id"]) not in known_existing_ids
        ]
        if args.match_id:
            new_matches = [
                m for m in new_matches
                if str(m.get("match_id")) == str(args.match_id)
            ]

        print(f"Discovered new match IDs: {len(new_matches)}")

        if args.dry_run:
            print("Dry run: would fetch games for the following new matches:")
            for m in new_matches:
                print(f"  {m.get('match_id')}: {m.get('sname_t1')} vs {m.get('sname_t2')} ({m.get('date')})")

        # ------------------------------------------------------------------ #
        # 3. Build the list of matches that need game data
        # ------------------------------------------------------------------ #
        # For the first run, we don't have match objects in memory (they're in DB).
        # We only process newly discovered matches (or refetches).
        # Build minimal match stubs from discovered_matches for the DB-fetched ones.
        selected_matches = [
            match
            for match in deduplicate_by_key(discovered_matches, "match_id")
            if should_fetch_games(
                match,
                known_existing_ids,
                games_per_match,
                include_incomplete_existing=args.include_incomplete_existing,
                refetch_games=args.refetch_games,
                match_id=args.match_id,
            )
        ]
        if args.dry_run:
            # Only consider newly discovered matches for dry run
            selected_new_ids = {
                str(m["match_id"]) for m in new_matches if m.get("match_id")
            }
            selected_matches = [
                m for m in selected_matches
                if str(m.get("match_id")) in selected_new_ids
            ]

        if not selected_matches:
            print("No matches need game data. All up to date.")
            return

        print(
            f"Fetching nested games for {len(selected_matches)} matches "
            "(new only by default; existing incomplete only with --include-incomplete-existing)."
        )
        if args.dry_run:
            print("Dry run: stopping before downloading/saving nested games.")
            return

        # ------------------------------------------------------------------ #
        # 4. Fetch games and write directly to DB in batches
        # ------------------------------------------------------------------ #
        fetched_total = await fetch_and_save_games(
            scraper,
            selected_matches,
            batch_size=max(1, args.batch_size),
            concurrency=args.concurrency,
        )

        print(
            f"[{datetime.now(timezone.utc).isoformat()}] "
            f"Finished. Wrote game data for {fetched_total} matches."
        )

        # ------------------------------------------------------------------ #
        # 5. Auto-map newly imported matches to canonical_matches
        # ------------------------------------------------------------------ #
        print("Auto-mapping newly imported GOL.GG matches to canonical_matches...")
        new_match_ids = [
            str(m["match_id"]) for m in fetched_match_docs
            if m.get("match_id") and m.get("games")
        ]
        if new_match_ids:
            map_stats = auto_map_new_matches(new_match_ids)
            print(
                f"Auto-mapping result: checked={map_stats['checked']}, "
                f"mapped={map_stats['mapped']}, "
                f"already_mapped={map_stats['already_mapped']}, "
                f"unmatched={map_stats['errors']}"
            )

        print(
            f"[{datetime.now(timezone.utc).isoformat()}] "
            f"GOL.GG direct refresh complete."
        )


if __name__ == "__main__":
    asyncio.run(main())
