"""Lebull API scraper for League of Legends prematch match-winner odds."""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any

from betting_app.scrapers.base import RawOddsSnapshot


LEBULL_ESPORT_URL = "https://www.lebull.pl/pl/zaklady-sportowe?page=/esport"
LEBULL_SSR_URL = "https://lebullpl-ssr.boxwebcdn.work/pl/esport?currency=PLN&parent=www.lebull.pl&&1"
LEBULL_API_BASE = "https://betting-platform.prod.sbteam.xyz"
SCRAPER_VERSION = "lebull-api-lol-match-winner-0.1"


class LebullApiScraper:
    """API scraper for Lebull LoL prematch match-winner markets."""

    bookmaker = "lebull"
    scraper_version = SCRAPER_VERSION

    def __init__(self, start_url: str = LEBULL_ESPORT_URL, headless: bool | None = None) -> None:
        self.start_url = start_url
        self.headless = headless
        self.tenant_id: str | None = None

    async def scrape_upcoming_matches(self) -> list[RawOddsSnapshot]:
        """Fetch LoL league IDs, then event details for match-winner odds."""

        _ = self.headless
        self.tenant_id = self.fetch_tenant_id()
        league_ids = self.fetch_lol_league_ids()
        games: list[dict[str, Any]] = []
        for league_id in league_ids:
            games.extend(self.fetch_league_games(league_id))
        snapshots: list[RawOddsSnapshot] = []
        seen: set[int] = set()
        for game in games:
            event_id = int(game.get("eventId") or 0)
            if not event_id or event_id in seen or game.get("isLive"):
                continue
            seen.add(event_id)
            detail = self.fetch_event_detail(event_id)
            snapshot = self.parse_event_detail(detail)
            if snapshot:
                snapshots.append(snapshot)
        print(f"Lebull API captured {len(snapshots)} LoL prematch snapshots from {len(league_ids)} leagues.")
        return snapshots

    def fetch_tenant_id(self) -> str:
        """Read public tenant id from Lebull SSR env block."""

        req = urllib.request.Request(LEBULL_SSR_URL, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html,*/*"})
        with urllib.request.urlopen(req, timeout=30) as response:
            text = response.read().decode("utf-8", "replace")
        match = re.search(r'"BETTING_PLATFORM_SVC_TENANT_ID"\s*:\s*"([^"]+)"', text)
        if not match:
            raise RuntimeError("Could not find Lebull tenant id in SSR page")
        return match.group(1)

    def request_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET Lebull betting-platform JSON with tenant header."""

        if not self.tenant_id:
            raise RuntimeError("Lebull tenant_id is not initialized")
        query = urllib.parse.urlencode(params or {})
        url = f"{LEBULL_API_BASE}{path}" + (f"?{query}" if query else "")
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json,text/plain,*/*",
                "Origin": "https://www.lebull.pl",
                "Referer": "https://www.lebull.pl/",
                "X-Auth-Tenant-Id": self.tenant_id,
            },
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)

    def fetch_lol_league_ids(self) -> list[int]:
        """Return Lebull League of Legends league IDs from sports tree."""

        data = self.request_json("/sports", {"currency": "PLN", "language": "pl"})
        sports = data.get("sports") if isinstance(data, dict) else []
        league_ids: list[int] = []
        for sport in sports or []:
            if int(sport.get("sportId") or 0) != 53:
                continue
            for country in sport.get("countries") or []:
                if str(country.get("countryName")) != "League of Legends":
                    continue
                for league in country.get("leagues") or []:
                    league_id = int(league.get("leagueId") or 0)
                    if league_id:
                        league_ids.append(league_id)
        return league_ids

    def fetch_league_games(self, league_id: int) -> list[dict[str, Any]]:
        """Fetch all games for one LoL league."""

        data = self.request_json(f"/sports/53/leagues/{league_id}/games", {"currency": "PLN"})
        return list(data or [])

    def fetch_event_detail(self, event_id: int) -> dict[str, Any]:
        """Fetch prematch event detail with markets."""

        return dict(self.request_json(f"/games/{event_id}/prematch", {"currency": "PLN"}) or {})

    def parse_event_detail(self, event: dict[str, Any]) -> RawOddsSnapshot | None:
        """Parse Lebull event detail into RawOddsSnapshot."""

        if not event or event.get("isLive") or str(event.get("countryName")) != "League of Legends":
            return None
        market = next(
            (st for st in event.get("stakeTypes") or [] if str(st.get("stakeTypeName", "")).lower() in {"result (2 way)", "winner"}),
            None,
        )
        if not market:
            return None
        stakes = sorted(market.get("stakes") or [], key=lambda item: int(item.get("stakeCode") or 0))
        active = [stake for stake in stakes if stake.get("isActive") and not stake.get("isDeleted")]
        if len(active) < 2:
            return None
        odds_a = parse_float(active[0].get("betFactor"))
        odds_b = parse_float(active[1].get("betFactor"))
        if odds_a is None or odds_b is None:
            return None
        event_id = str(event.get("eventId"))
        detail_api = f"{LEBULL_API_BASE}/games/{event_id}/prematch?currency=PLN"
        return RawOddsSnapshot(
            bookmaker=self.bookmaker,
            raw_team_a=str(event.get("teamA") or active[0].get("stakeName") or ""),
            raw_team_b=str(event.get("teamB") or active[1].get("stakeName") or ""),
            odds_a=odds_a,
            odds_b=odds_b,
            scraped_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
            raw_league=str(event.get("leagueName") or ""),
            match_start_time=parse_timestamp(event.get("timestamp")) or str(event.get("date") or ""),
            source_url=LEBULL_API_BASE,
            offer_url=detail_api,
            market_type="match_winner",
            is_live=False,
            scraper_name="lebull_api_lol_match_winner",
            scraper_version=SCRAPER_VERSION,
            raw_payload={"event": event, "market": market, "stakes": active[:2]},
        )


def parse_float(value: Any) -> float | None:
    """Parse bookmaker odd value."""

    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def parse_timestamp(value: Any) -> str | None:
    """Convert Lebull millisecond timestamp to UTC ISO string."""

    try:
        timestamp = int(value) / 1000
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(timestamp, tz=UTC).replace(microsecond=0).isoformat()
