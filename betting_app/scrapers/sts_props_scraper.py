"""STS League of Legends proposition odds scraper (IDEA-018).

Extracts in-game markets (total kills, team kills, handicaps, duration,
first blood, first dragon, first baron, first tower, map winner, total maps)
from STS Angular SSR transfer state and event detail pages.
"""

from __future__ import annotations

from datetime import UTC, datetime
import re
from typing import Any

from betting_app.scrapers.base import RawOddsSnapshot
from betting_app.scrapers.nodriver_client import NoDriverClient
from betting_app.scrapers.props_parser import (
    LINE_RE,
    MarketType,
    ParsedMatchProps,
    ParsedPropLine,
    compute_novig_two_way,
    extract_line_number,
)

STS_LOL_URL = "https://www.sts.pl/zaklady/esport/league-of-legends"
SCRAPER_VERSION = "sts-props-0.1"


def classify_sts_market(name: str) -> tuple[MarketType | None, int]:
    """Classify STS market name into MarketType and map_number."""
    n = name.strip().lower()

    # Determine map number (default to 1)
    map_number = 1
    map_match = re.search(r"(\d+)\.\s*map[a-ząćęłńóśźż]*|map[a-ząćęłńóśźż]*\s*(\d+)", n)
    if map_match:
        try:
            val = map_match.group(1) or map_match.group(2)
            if val:
                map_number = int(val)
        except ValueError:
            map_number = 1

    # Classify market type
    if "suma map" in n or "liczba map" in n:
        return "total_maps", 1
    if "handicap map" in n or "handicap (mapy)" in n:
        return "map_handicap", 1
    if "zwycięzca meczu" in n:
        return None, 1
    if "zwycięzca" in n and ("map" in n or "mapy" in n):
        return "map_winner", map_number

    # Kills
    if "handicap" in n and ("zabójstw" in n or "frag" in n or "kill" in n):
        return "handicap_kills", map_number
    if ("liczba zabójstw drużyn" in n) or (re.search(r"-\s*liczba zabójstw", n)):
        return "team_kills", map_number
    if "suma zabójstw" in n or "liczba zabójstw" in n or "ilość zabójstw" in n:
        return "total_kills", map_number

    # Duration
    if "czas trwania" in n or "czas gry" in n or "minut" in n:
        return "duration", map_number

    # First objectives
    if "1. krew" in n or "pierwsza krew" in n or "first blood" in n:
        return "first_blood", map_number
    if "1. smok" in n or "pierwszy smok" in n or "first dragon" in n:
        return "first_dragon", map_number
    if "1. baron" in n or "pierwszy baron" in n or "first baron" in n:
        return "first_baron", map_number
    if "1. wieża" in n or "pierwsza wieża" in n or "first tower" in n or "first turret" in n:
        return "first_tower", map_number
    if "wyścig do" in n:
        return "race_to_kills", map_number

    return None, map_number


class STSPropsScraper:
    """Scraper and parser for STS League of Legends proposition markets."""

    bookmaker: str = "sts"
    scraper_version: str = SCRAPER_VERSION

    def __init__(self, start_url: str = STS_LOL_URL, headless: bool | None = None) -> None:
        self.start_url = start_url
        self.headless = headless

    def parse_event_props(
        self,
        payload: dict[str, Any],
        match_info: dict[str, Any] | None = None,
    ) -> list[ParsedMatchProps]:
        """Parse STS SBK SSR transfer state payload or event detail dictionary into ParsedMatchProps."""
        info = match_info or {}
        home_default = info.get("team_a") or info.get("home") or ""
        away_default = info.get("team_b") or info.get("away") or ""

        # Check if this is the root transfer state dictionary (with tournaments and offers)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        tournaments = data.get("T") or data.get("tournaments") or {}
        offers = data.get("O") or data.get("offers") or {}

        # If it's already a single fixture structure
        if "H" in data and "A" in data:
            return self._parse_single_fixture_dict(
                fixture_id=str(data.get("id", "1")),
                fixture=data,
                offers=offers,
                home_default=home_default,
                away_default=away_default,
            )

        results: list[ParsedMatchProps] = []
        for tour_id, tournament in tournaments.items():
            fixtures = tournament.get("FX") or tournament.get("F") or {}
            for fix_id, fixture in fixtures.items():
                parsed_fixtures = self._parse_single_fixture_dict(
                    fixture_id=str(fix_id),
                    fixture=fixture,
                    offers=offers,
                    home_default=home_default,
                    away_default=away_default,
                )
                results.extend(parsed_fixtures)

        return results

    def _parse_single_fixture_dict(
        self,
        fixture_id: str,
        fixture: dict[str, Any],
        offers: dict[str, Any],
        home_default: str = "",
        away_default: str = "",
    ) -> list[ParsedMatchProps]:
        """Parse all proposition lines from a single fixture."""
        home = self._name(fixture.get("H")) or home_default or "Team A"
        away = self._name(fixture.get("A")) or away_default or "Team B"

        offer_ids = list((fixture.get("a") or {}).keys())
        # Also check direct markets if nested
        direct_markets = fixture.get("markets") or {}

        # Group lines by map_number
        lines_by_map: dict[int, list[ParsedPropLine]] = {}

        def add_line(m_num: int, line_obj: ParsedPropLine) -> None:
            if m_num not in lines_by_map:
                lines_by_map[m_num] = []
            lines_by_map[m_num].append(line_obj)

        # Process offers
        for offer_id in offer_ids:
            offer = offers.get(offer_id) or {}
            markets = offer.get("m") or {}
            self._extract_markets_into_lines(markets, home, away, add_line)

        if direct_markets:
            self._extract_markets_into_lines(direct_markets, home, away, add_line)

        # Build ParsedMatchProps per map
        match_props_list: list[ParsedMatchProps] = []
        for map_num, lines in sorted(lines_by_map.items()):
            if lines:
                match_props_list.append(
                    ParsedMatchProps(
                        bookmaker=self.bookmaker,
                        raw_team_a=home,
                        raw_team_b=away,
                        map_number=map_num,
                        lines=lines,
                    )
                )

        return match_props_list

    def _extract_markets_into_lines(
        self,
        markets: dict[str, Any] | list[dict[str, Any]],
        home: str,
        away: str,
        add_fn: Any,
    ) -> None:
        """Extract prop lines from market definitions."""
        market_items = markets.values() if isinstance(markets, dict) else markets
        for market in market_items:
            if not isinstance(market, dict):
                continue
            lines = market.get("l") or market.get("lines") or {}
            line_items = lines.values() if isinstance(lines, dict) else lines
            for line in line_items:
                if not isinstance(line, dict):
                    continue
                market_name = str(line.get("n") or market.get("n") or "")
                market_type, map_num = classify_sts_market(market_name)
                if not market_type:
                    continue

                outcomes = line.get("o") or line.get("outcomes") or {}
                outcome_list: list[dict[str, Any]] = []
                if isinstance(outcomes, dict):
                    for oid, o_data in outcomes.items():
                        if isinstance(o_data, dict):
                            o_copy = dict(o_data)
                            o_copy["id"] = str(oid)
                            outcome_list.append(o_copy)
                elif isinstance(outcomes, list):
                    outcome_list = [o for o in outcomes if isinstance(o, dict)]

                parsed_line = self._parse_line_outcomes(
                    market_type=market_type,
                    market_name=market_name,
                    outcomes=outcome_list,
                    home=home,
                    away=away,
                )
                if parsed_line:
                    add_fn(map_num, parsed_line)

    def _parse_line_outcomes(
        self,
        market_type: MarketType,
        market_name: str,
        outcomes: list[dict[str, Any]],
        home: str,
        away: str,
    ) -> ParsedPropLine | None:
        """Construct ParsedPropLine from outcomes."""
        extracted_num = extract_line_number(market_name)
        line_val = extracted_num if extracted_num is not None else 0.0

        odds_over: float | None = None
        odds_under: float | None = None
        odds_cover_a: float | None = None
        odds_cover_b: float | None = None

        for o in outcomes:
            name = str(o.get("n") or o.get("name") or "").lower()
            odds = float(o.get("O") or o.get("odds") or 0.0)
            if odds <= 1.0:
                continue

            # Check Over/Under
            if any(k in name for k in ["powyżej", "over", "+", "więcej"]):
                odds_over = odds
                num = extract_line_number(name)
                if num is not None:
                    line_val = num
            elif any(k in name for k in ["poniżej", "under", "-", "mniej"]):
                odds_under = odds
                num = extract_line_number(name)
                if num is not None:
                    line_val = num
            elif home.lower() in name or "1" in name or "home" in name:
                odds_cover_a = odds
            elif away.lower() in name or "2" in name or "away" in name:
                odds_cover_b = odds

        # If two-way Over/Under
        if odds_over and odds_under:
            p_o, p_u, margin = compute_novig_two_way(odds_over, odds_under)
            return ParsedPropLine(
                market_type=market_type,
                line=line_val,
                odds_over=odds_over,
                odds_under=odds_under,
                novig_prob_over=p_o,
                novig_prob_under=p_u,
                margin=margin,
                raw_market_name=market_name,
            )

        # If two-way Team A vs Team B (First objectives, map winner)
        if odds_cover_a and odds_cover_b:
            p_a, p_b, margin = compute_novig_two_way(odds_cover_a, odds_cover_b)
            return ParsedPropLine(
                market_type=market_type,
                line=line_val,
                odds_cover_a=odds_cover_a,
                odds_cover_b=odds_cover_b,
                novig_prob_cover_a=p_a,
                novig_prob_cover_b=p_b,
                margin=margin,
                raw_market_name=market_name,
            )

        return None

    async def scrape_upcoming_props(self, max_matches: int = 10) -> list[ParsedMatchProps]:
        """Scrape STS LoL upcoming match proposition markets via NoDriver."""
        props_results: list[ParsedMatchProps] = []
        async with NoDriverClient(headless=self.headless) as client:
            tab = await client.open(self.start_url)
            await self._wait_for_render(tab, 6.0)
            data = await self._extract_ssr_data(tab)
            if data:
                props_results.extend(self.parse_event_props(data))

        return props_results[:max_matches]

    async def _wait_for_render(self, tab: Any, seconds: float = 6.0) -> None:
        import asyncio
        await asyncio.sleep(seconds)

    async def _extract_ssr_data(self, tab: Any) -> dict[str, Any] | None:
        import json
        js = """
        (() => {
            const scripts = document.querySelectorAll('script');
            for (const s of scripts) {
                try {
                    const text = s.textContent.trim();
                    if (text.startsWith('{') && text.includes('sbk-exporter')) {
                        const parsed = JSON.parse(text);
                        const key = 'sbk-exporter-sports-ssr';
                        if (key in parsed) return JSON.stringify(parsed[key]);
                        if ('B' in parsed && 'P' in parsed) return JSON.stringify(parsed);
                    }
                } catch(e) {}
            }
            return null;
        })()
        """
        raw = await tab.evaluate(js)
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                return None
        return None

    def _name(self, value: Any) -> str:
        if isinstance(value, dict):
            return str(value.get("N") or value.get("n") or "")
        return str(value or "")
