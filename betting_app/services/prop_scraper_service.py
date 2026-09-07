"""Service for running and orchestrating proposition odds scrapers across bookmakers (IDEA-018).

Coordinates STS, eFortuna, Betclic, and Superbet prop scrapers, matches events to
canonical matches, persists prop lines into `prop_odds_snapshots`, and triggers
statistical model evaluation.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from betting_app.core.db import get_session
from betting_app.scrapers.betclic_props_scraper import BetclicPropsScraper
from betting_app.scrapers.efortuna_props_scraper import EFortunaPropsScraper
from betting_app.scrapers.props_parser import ParsedMatchProps
from betting_app.scrapers.sts_props_scraper import STSPropsScraper
from betting_app.scrapers.superbet_props_scraper import SuperbetPropsScraper
from betting_app.services.canonical_match_service import resolve_canonical_match
from betting_app.services.prop_odds_service import evaluate_match_props, save_prop_snapshots


SCRAPERS_REGISTRY = {
    "sts": STSPropsScraper,
    "efortuna": EFortunaPropsScraper,
    "betclic": BetclicPropsScraper,
    "superbet": SuperbetPropsScraper,
}


class PropScraperService:
    """Orchestrator for multi-bookmaker proposition odds scraping."""

    def __init__(self, headless: bool | None = None) -> None:
        self.headless = headless

    async def scrape_bookmaker(
        self,
        bookmaker: str,
        max_matches: int = 10,
    ) -> list[ParsedMatchProps]:
        """Run prop scraper for a specific bookmaker."""
        scraper_cls = SCRAPERS_REGISTRY.get(bookmaker.lower())
        if not scraper_cls:
            raise ValueError(f"Unknown or unsupported bookmaker: '{bookmaker}'. Supported: {list(SCRAPERS_REGISTRY.keys())}")

        scraper = scraper_cls(headless=self.headless)
        return await scraper.scrape_upcoming_props(max_matches=max_matches)

    def process_and_persist_props(
        self,
        match_props_list: list[ParsedMatchProps],
        db_session=None,
        evaluate_models: bool = True,
    ) -> dict[str, Any]:
        """Match scraped proposition lines to canonical matches and persist in database."""
        sess = db_session or get_session()
        own_session = db_session is None

        summary = {
            "total_matches_processed": len(match_props_list),
            "matched_to_canonical": 0,
            "total_lines_persisted": 0,
            "predictions_generated": 0,
            "details": [],
        }

        try:
            for mp in match_props_list:
                # 1. Resolve canonical match
                canon_res = resolve_canonical_match(
                    raw_team_a=mp.raw_team_a,
                    raw_team_b=mp.raw_team_b,
                    start_time=None,
                    league=None,
                    db=sess,
                )

                canonical_match_id: int | None = None
                if canon_res and getattr(canon_res, "canonical_match_id", None):
                    canonical_match_id = int(canon_res.canonical_match_id)
                else:
                    # Fallback fuzzy match against active upcoming matches
                    cm = sess.execute(
                        text("""
                            SELECT id, team_a_name, team_b_name, league
                            FROM canonical_matches
                            WHERE status = 'upcoming'
                            AND (
                                LOWER(team_a_name) LIKE :team_a OR LOWER(team_b_name) LIKE :team_a
                                OR LOWER(team_a_name) LIKE :team_b OR LOWER(team_b_name) LIKE :team_b
                            )
                            ORDER BY id DESC LIMIT 1
                        """),
                        {
                            "team_a": f"%{mp.raw_team_a[:4].lower()}%",
                            "team_b": f"%{mp.raw_team_b[:4].lower()}%",
                        },
                    ).fetchone()
                    if cm:
                        canonical_match_id = cm.id

                if not canonical_match_id:
                    summary["details"].append({
                        "bookmaker": mp.bookmaker,
                        "teams": f"{mp.raw_team_a} vs {mp.raw_team_b}",
                        "status": "unmatched_to_canonical",
                        "lines_count": len(mp.lines),
                    })
                    continue

                summary["matched_to_canonical"] += 1

                # 2. Persist prop lines
                inserted = save_prop_snapshots(
                    match_props=mp,
                    canonical_match_id=canonical_match_id,
                    db_session=sess,
                )
                summary["total_lines_persisted"] += len(inserted)

                # 3. Trigger statistical evaluation
                pred_id = None
                if evaluate_models and inserted:
                    try:
                        eval_res = evaluate_match_props(
                            canonical_match_id=canonical_match_id,
                            map_number=mp.map_number,
                            persist_prediction=True,
                            db_session=sess,
                        )
                        pred_id = eval_res.get("saved_prediction_id")
                        if pred_id:
                            summary["predictions_generated"] += 1
                    except Exception as err:
                        print(f"Failed to evaluate prop models for match {canonical_match_id}: {err}")

                summary["details"].append({
                    "bookmaker": mp.bookmaker,
                    "canonical_match_id": canonical_match_id,
                    "teams": f"{mp.raw_team_a} vs {mp.raw_team_b}",
                    "map_number": mp.map_number,
                    "status": "persisted",
                    "inserted_snapshots": len(inserted),
                    "saved_prediction_id": pred_id,
                })

            if own_session:
                sess.commit()

            return summary
        finally:
            if own_session:
                sess.close()


async def run_all_prop_scrapers(
    bookmakers: list[str] | None = None,
    max_matches_per_bookmaker: int = 10,
    headless: bool | None = None,
    db_session=None,
) -> dict[str, Any]:
    """Execute prop scraping for all selected bookmakers and persist results."""
    target_books = [b.lower() for b in bookmakers] if bookmakers else list(SCRAPERS_REGISTRY.keys())
    service = PropScraperService(headless=headless)

    overall_results: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "bookmakers": target_books,
        "results": {},
    }

    all_scraped_props: list[ParsedMatchProps] = []

    for book in target_books:
        try:
            props = await service.scrape_bookmaker(book, max_matches=max_matches_per_bookmaker)
            all_scraped_props.extend(props)
            overall_results["results"][book] = {
                "status": "success",
                "scraped_matches": len(props),
                "total_lines": sum(len(p.lines) for p in props),
            }
        except Exception as e:
            overall_results["results"][book] = {
                "status": "error",
                "error": str(e),
            }

    # Persist and evaluate
    if all_scraped_props:
        persist_summary = service.process_and_persist_props(
            all_scraped_props,
            db_session=db_session,
            evaluate_models=True,
        )
        overall_results["persistence"] = persist_summary

    return overall_results
