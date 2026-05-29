"""TOTALbet API scraper for League of Legends prematch match-winner odds."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any

from betting_app.scrapers.base import RawOddsSnapshot


TOTALBET_ESPORT_URL = "https://totalbet.pl/esport"
TOTALBET_EVENTS_API = "https://totalbet.pl/dealer/bdata/v1/bet/events/esport"
SCRAPER_VERSION = "totalbet-api-lol-match-winner-0.1"


class TotalbetApiScraper:
    """API scraper for TOTALbet LoL prematch match-winner markets."""

    bookmaker = "totalbet"
    scraper_version = SCRAPER_VERSION

    def __init__(self, start_url: str = TOTALBET_ESPORT_URL, headless: bool | None = None, pages: int = 8) -> None:
        self.start_url = start_url
        self.headless = headless
        self.pages = pages

    async def scrape_upcoming_matches(self) -> list[RawOddsSnapshot]:
        """Fetch paginated esport events and keep LoL prematch match-winner markets."""

        _ = self.headless
        events: list[dict[str, Any]] = []
        for page in range(1, self.pages + 1):
            batch = self.fetch_events_page(page)
            if not batch:
                break
            events.extend(batch)
        snapshots = [snapshot for event in events if (snapshot := self.parse_event(event))]
        print(f"TOTALbet API captured {len(snapshots)} LoL prematch snapshots from {len(events)} esport events.")
        return snapshots

    def fetch_events_page(self, page: int) -> list[dict[str, Any]]:
        """Fetch one TOTALbet esport events page."""

        url = f"{TOTALBET_EVENTS_API}?{urllib.parse.urlencode({'page': page, 'per_page': 20})}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as response:
            payload = json.load(response)
        return list((payload.get("data") or {}).get("events") or [])

    def parse_event(self, event: dict[str, Any]) -> RawOddsSnapshot | None:
        """Convert one TOTALbet event into a two-sided match-winner snapshot."""

        if event.get("type") == "live" or event.get("status") != "active":
            return None
        path = event.get("path") or []
        if not path or str(path[0].get("name")) != "League of Legends":
            return None
        participants = event.get("participants") or []
        if len(participants) < 2:
            return None
        market = next((m for m in event.get("markets") or [] if str(m.get("name", "")).lower().startswith("zwyci")), None)
        if not market or market.get("market_type") == "live":
            return None
        outcomes = sorted(market.get("outcomes") or [], key=lambda item: int(item.get("sort") or 0))
        if len(outcomes) < 2:
            return None
        odds_a = parse_float(outcomes[0].get("odds"))
        odds_b = parse_float(outcomes[1].get("odds"))
        if odds_a is None or odds_b is None:
            return None
        team_a = str(participants[0].get("name") or outcomes[0].get("name") or "")
        team_b = str(participants[1].get("name") or outcomes[1].get("name") or "")
        event_uuid = str(event.get("uuid"))
        league = " / ".join(str(p.get("name")) for p in path[1:] if p.get("name")) or str(event.get("tournament") or "")
        return RawOddsSnapshot(
            bookmaker=self.bookmaker,
            raw_team_a=team_a,
            raw_team_b=team_b,
            odds_a=odds_a,
            odds_b=odds_b,
            scraped_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
            raw_league=league,
            match_start_time=event.get("start_at"),
            source_url=TOTALBET_EVENTS_API,
            offer_url=f"https://totalbet.pl/esport/event-details/{event_uuid}",
            market_type="match_winner",
            is_live=False,
            scraper_name="totalbet_api_lol_match_winner",
            scraper_version=SCRAPER_VERSION,
            raw_payload={"event": event, "market": market, "outcomes": outcomes[:2]},
        )


def parse_float(value: Any) -> float | None:
    """Parse bookmaker odd value."""

    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
