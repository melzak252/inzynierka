"""STS League of Legends prematch scraper.

The current implementation uses the same prematch snapshot that the STS web
frontend uses for initial offer hydration:

    https://sbk.sts.pl/sbk-exporter/v1/sports/ssr

Despite the historic filename, this scraper does not need NoDriver. It fetches
the public frontend configuration, extracts the SBK exporter headers at runtime,
downloads the compressed sports snapshot, and parses LoL match-winner markets.

Scope for the betting MVP: prematch League of Legends, market "Zwycięzca meczu"
only. The scraper returns both:

* atomic outcome snapshots for odds history / CLV tracking, and
* a legacy two-sided RawOddsSnapshot so the current EV signal MVP can use it.
"""

from __future__ import annotations

import json
import re
import urllib.request
import unicodedata
from datetime import UTC, datetime
from typing import Any

from betting_app.scrapers.base import RawOddsSnapshot, RawOutcomeOddsSnapshot


STS_LOL_URL = "https://www.sts.pl/zaklady-bukmacherskie/esport/league-of-legends/156/992"
STS_FRONTEND_CONFIG_URL = "https://www.sts.pl/nextweb-assets/chunk-OL6G7E66.js"
STS_SBK_EXPORTER_URL = "https://sbk.sts.pl/sbk-exporter/v1/sports/ssr"
STS_ESPORT_SPORT_ID = "156"
STS_LOL_CATEGORY_ID = "992"
STS_LOL_CATEGORY_NAME = "League of Legends"
STS_ESPORT_SPORT_NAME = "Esport"
STS_MATCH_WINNER_MARKET_NAME = "Zwycięzca meczu"
SCRAPER_VERSION = "sts-sbk-ssr-lol-match-winner-0.1"


class STSNoDriverScraper:
    """Scrape STS LoL prematch match-winner odds from SBK SSR snapshot."""

    bookmaker = "sts"
    scraper_version = SCRAPER_VERSION

    def __init__(
        self,
        start_url: str = STS_LOL_URL,
        headless: bool | None = None,
        *,
        sport_id: str = STS_ESPORT_SPORT_ID,
        category_id: str = STS_LOL_CATEGORY_ID,
        include_legacy_pair_snapshots: bool = True,
    ) -> None:
        self.start_url = start_url or STS_LOL_URL
        self.headless = headless  # kept for CLI compatibility
        self.sport_id = sport_id
        self.category_id = category_id
        self.include_legacy_pair_snapshots = include_legacy_pair_snapshots
        self.last_request_url: str | None = None
        self.last_total_count: int = 0
        self.last_fixture_count: int = 0

    async def scrape_upcoming_matches(self) -> list[RawOddsSnapshot | RawOutcomeOddsSnapshot]:
        """Fetch STS SBK snapshot and return LoL prematch match-winner odds."""

        _ = self.headless
        scraped_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        headers = self.build_sbk_headers()
        self.last_request_url = STS_SBK_EXPORTER_URL
        data = self.fetch_json(STS_SBK_EXPORTER_URL, headers=headers)
        snapshots = self.parse_lol_match_winner_snapshot(
            data,
            scraped_at=scraped_at,
            source_url=STS_SBK_EXPORTER_URL,
        )
        outcome_count = sum(isinstance(snapshot, RawOutcomeOddsSnapshot) for snapshot in snapshots)
        pair_count = sum(isinstance(snapshot, RawOddsSnapshot) for snapshot in snapshots)
        print(
            "STS SBK SSR captured "
            f"{self.last_fixture_count} LoL fixtures, {outcome_count} outcome odds, "
            f"{pair_count} two-sided match-winner snapshots. URL={STS_SBK_EXPORTER_URL}"
        )
        return snapshots

    def build_sbk_headers(self) -> dict[str, str]:
        """Build browser-like headers required by STS SBK exporter.

        The auth-like values are public frontend config values. They are extracted
        at runtime instead of being hardcoded in the repository.
        """

        config_text = self.fetch_text(STS_FRONTEND_CONFIG_URL)
        match = re.search(
            r'offer:\{sbkExporter:\{api:vt,token:"([^"]+)",cfAccessClientId:"([^"]+)",cfAccessClientSecret:"([^"]+)"\}',
            config_text,
        )
        if not match:
            raise RuntimeError("Could not extract STS SBK exporter headers from frontend config")
        token, cf_access_client_id, cf_access_client_secret = match.groups()
        return {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
            "Accept": "application/json,text/plain,*/*",
            "Origin": "https://www.sts.pl",
            "Referer": self.start_url,
            "Content-Type": "application/json",
            "X-Api-Key": token,
            "CF-Access-Client-Id": cf_access_client_id,
            "CF-Access-Client-Secret": cf_access_client_secret,
        }

    def fetch_text(self, url: str, headers: dict[str, str] | None = None) -> str:
        """Fetch text with browser-like headers."""

        request_headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
            "Accept": "text/javascript,text/plain,*/*",
            "Referer": self.start_url,
        }
        if headers:
            request_headers.update(headers)
        request = urllib.request.Request(url, headers=request_headers)
        with urllib.request.urlopen(request, timeout=45) as response:
            return response.read().decode("utf-8", errors="replace")

    def fetch_json(self, url: str, headers: dict[str, str]) -> dict[str, Any]:
        """Fetch and parse JSON from STS."""

        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8", errors="replace")
        parsed = json.loads(body)
        if not isinstance(parsed, dict):
            raise ValueError(f"Unexpected STS response type: {type(parsed).__name__}")
        return parsed

    def parse_lol_match_winner_snapshot(
        self,
        data: dict[str, Any],
        *,
        scraped_at: str,
        source_url: str,
    ) -> list[RawOddsSnapshot | RawOutcomeOddsSnapshot]:
        """Parse LoL fixtures and match-winner markets from SBK SSR payload."""

        offers = data.get("P") or {}
        sports = ((data.get("B") or {}).get("S") or {})
        esport = sports.get(self.sport_id) or {}
        category = (esport.get("C") or {}).get(self.category_id) or {}
        tournaments = category.get("T") or {}
        snapshots: list[RawOddsSnapshot | RawOutcomeOddsSnapshot] = []
        fixture_count = 0

        for tournament_id, tournament in tournaments.items():
            league_name = self._name(tournament) or str(tournament_id)
            fixtures = tournament.get("FX") or tournament.get("F") or {}
            for fixture_id, fixture in fixtures.items():
                fixture_count += 1
                parsed = self.parse_fixture_match_winner(
                    fixture_id=str(fixture_id),
                    fixture=fixture,
                    offers=offers,
                    tournament_id=str(tournament_id),
                    league_name=league_name,
                    scraped_at=scraped_at,
                    source_url=source_url,
                )
                snapshots.extend(parsed)

        self.last_fixture_count = fixture_count
        self.last_total_count = len(snapshots)
        return snapshots

    def parse_fixture_match_winner(
        self,
        *,
        fixture_id: str,
        fixture: dict[str, Any],
        offers: dict[str, Any],
        tournament_id: str,
        league_name: str,
        scraped_at: str,
        source_url: str,
    ) -> list[RawOddsSnapshot | RawOutcomeOddsSnapshot]:
        """Parse match winner outcomes for one fixture."""

        home = self._name(fixture.get("H")) or ""
        away = self._name(fixture.get("A")) or ""
        starts_at = fixture.get("t") or fixture.get("T")
        offer_url = self.build_offer_url(home=home, away=away, fixture_id=fixture_id)
        offer_ids = list((fixture.get("a") or {}).keys())
        snapshots: list[RawOddsSnapshot | RawOutcomeOddsSnapshot] = []

        for offer_id in offer_ids:
            offer = offers.get(offer_id) or {}
            markets = offer.get("m") or {}
            for market_id, market in markets.items():
                lines = market.get("l") or {}
                for line_id, line in lines.items():
                    market_name = str(line.get("n") or market.get("n") or "")
                    if not self.is_match_winner_market(market_name):
                        continue
                    outcomes = line.get("o") or {}
                    if not outcomes:
                        continue
                    outcome_snapshots: list[RawOutcomeOddsSnapshot] = []
                    odds_by_side: dict[str, float] = {}
                    for outcome_id, outcome in outcomes.items():
                        if not isinstance(outcome, dict) or outcome.get("O") is None:
                            continue
                        outcome_side = self.infer_outcome_side(str(outcome_id))
                        decimal_odds = float(outcome["O"])
                        if outcome_side:
                            odds_by_side[outcome_side] = decimal_odds
                        outcome_name = self.outcome_name(outcome_id=str(outcome_id), outcome_side=outcome_side, home=home, away=away)
                        snapshot = RawOutcomeOddsSnapshot(
                            bookmaker=self.bookmaker,
                            bookmaker_event_id=fixture_id,
                            raw_team_a=home,
                            raw_team_b=away,
                            decimal_odds=decimal_odds,
                            outcome_key=f"{offer_id}:{market_id}:{line_id}:{outcome_id}",
                            outcome_name=outcome_name,
                            outcome_side=outcome_side,
                            market_key=f"{offer_id}:{market_id}:{line_id}",
                            market_name=market_name or STS_MATCH_WINNER_MARKET_NAME,
                            line_id=str(line_id),
                            line_name=market_name or STS_MATCH_WINNER_MARKET_NAME,
                            is_extra_market=False,
                            scraped_at=scraped_at,
                            match_start_time=starts_at,
                            sport_id=self.sport_id,
                            sport_name=STS_ESPORT_SPORT_NAME,
                            category_id=self.category_id,
                            category_name=STS_LOL_CATEGORY_NAME,
                            league_id=tournament_id,
                            league_name=league_name,
                            source_url=source_url,
                            offer_url=offer_url,
                            scraper_name="sts_sbk_ssr_lol_match_winner",
                            scraper_version=SCRAPER_VERSION,
                            raw_payload={
                                "fixture_id": fixture_id,
                                "offer_id": offer_id,
                                "market_id": market_id,
                                "line_id": line_id,
                                "outcome_id": outcome_id,
                                "fixture": fixture,
                                "outcome": outcome,
                            },
                        )
                        outcome_snapshots.append(snapshot)

                    snapshots.extend(outcome_snapshots)
                    if self.include_legacy_pair_snapshots and "a" in odds_by_side and "b" in odds_by_side:
                        snapshots.append(
                            RawOddsSnapshot(
                                bookmaker=self.bookmaker,
                                raw_team_a=home,
                                raw_team_b=away,
                                odds_a=odds_by_side["a"],
                                odds_b=odds_by_side["b"],
                                scraped_at=scraped_at,
                                raw_league=league_name,
                                match_start_time=starts_at,
                                source_url=source_url,
                                offer_url=offer_url,
                                market_type="match_winner",
                                is_live=False,
                                scraper_name="sts_sbk_ssr_lol_match_winner",
                                scraper_version=SCRAPER_VERSION,
                                raw_payload={
                                    "fixture_id": fixture_id,
                                    "offer_id": offer_id,
                                    "market_id": market_id,
                                    "line_id": line_id,
                                    "offer_url": offer_url,
                                    "home": home,
                                    "away": away,
                                },
                            )
                        )
        return snapshots

    @staticmethod
    def build_offer_url(*, home: str, away: str, fixture_id: str) -> str:
        """Build the STS prematch detail URL used for manual close-odds checks."""

        team_slug = slugify(f"{home} {away}") or "mecz"
        return f"https://www.sts.pl/kursy/{team_slug}/{fixture_id}"

    @staticmethod
    def _name(value: Any) -> str | None:
        """Extract display name from STS compact objects."""

        if isinstance(value, dict):
            return value.get("n") or value.get("N")
        if value is None:
            return None
        return str(value)

    @staticmethod
    def is_match_winner_market(market_name: str) -> bool:
        """Return True for STS match-winner market labels."""

        normalized = market_name.strip().lower()
        return normalized in {"zwycięzca meczu", "zwyciezca meczu", "mecz"}

    @staticmethod
    def infer_outcome_side(outcome_id: str) -> str | None:
        """Infer side for STS esports match-winner outcome IDs.

        In observed LoL prematch data outcome id 4 corresponds to home/team A,
        and outcome id 5 corresponds to away/team B. Football 1X2 uses other IDs,
        but LoL match winner is two-sided and currently uses 4/5.
        """

        if str(outcome_id) == "4":
            return "a"
        if str(outcome_id) == "5":
            return "b"
        return None

    @staticmethod
    def outcome_name(*, outcome_id: str, outcome_side: str | None, home: str, away: str) -> str:
        """Build readable outcome name."""

        if outcome_side == "a":
            return home or "1"
        if outcome_side == "b":
            return away or "2"
        return str(outcome_id)


def slugify(value: str) -> str:
    """Create a simple STS-compatible-ish URL slug from team names."""

    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value.lower()).strip("-")
    return re.sub(r"-+", "-", slug)
