"""Betclic NoDriver scraper for League of Legends prematch match-winner odds."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from betting_app.scrapers.base import RawOddsSnapshot
from betting_app.scrapers.betclic_parser import (
    BETCLIC_LOL_URL,
    ParsedBetclicOffer,
    extract_event_links,
    parse_betclic_lol_offers,
)
from betting_app.scrapers.nodriver_client import NoDriverClient


SCRAPER_VERSION = "betclic-nodriver-0.1"


class BetclicNoDriverScraper:
    """NoDriver-based scraper for Betclic League of Legends match-winner markets."""

    bookmaker = "betclic"

    def __init__(self, start_url: str = BETCLIC_LOL_URL, headless: bool | None = None) -> None:
        self.start_url = start_url
        self.headless = headless

    async def scrape_upcoming_matches(self) -> list[RawOddsSnapshot]:
        """Open Betclic and return normalized LoL odds snapshots."""

        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        async with NoDriverClient(headless=self.headless) as client:
            tab = await client.open(self.start_url)
            await self.wait_for_render(tab)
            await self.accept_cookies(tab)
            html_path, screenshot_path = await client.save_debug_artifacts(tab, f"betclic_{timestamp}")
            body_text = await self.extract_body_text(tab)
            body_path = client.debug_dir / f"betclic_{timestamp}_body.txt"
            body_path.write_text(body_text, encoding="utf-8")
            cards = await self.extract_match_cards(tab, body_text=body_text)
            event_links = await self.extract_event_links(tab)
            if not event_links and html_path:
                event_links = self.extract_event_links_from_html(Path(html_path))
            cards = self.attach_offer_links(cards, event_links)
            snapshots = [
                snapshot
                for card in cards
                if (snapshot := self.parse_match_card(card, html_path or str(body_path), screenshot_path))
            ]

        print(
            f"Betclic scraper captured {len(snapshots)} snapshots. "
            f"Debug html={html_path}, body={body_path}, screenshot={screenshot_path}"
        )
        return snapshots

    async def wait_for_render(self, tab: Any, seconds: float = 8.0) -> None:
        """Wait for Betclic SPA to render content."""

        import asyncio

        _ = tab
        await asyncio.sleep(seconds)

    async def accept_cookies(self, tab: Any) -> None:
        """Best-effort cookie modal acceptance."""

        try:
            await tab.evaluate(
                """Array.from(document.querySelectorAll('button'))
                .find(button => button.innerText && button.innerText.includes('Zaakceptuj'))?.click()"""
            )
        except Exception:
            return

    async def extract_body_text(self, tab: Any) -> str:
        """Return rendered page body text."""

        body_text = await tab.evaluate("document.body ? document.body.innerText : ''")
        return str(body_text or "")

    async def extract_match_cards(self, tab: Any, body_text: str | None = None) -> list[ParsedBetclicOffer]:
        """Extract parsed Betclic LoL match cards from rendered text."""

        _ = tab
        return parse_betclic_lol_offers(body_text or "")

    async def extract_event_links(self, tab: Any) -> list[dict[str, str]]:
        """Extract Betclic event deep links from rendered HTML via parsel."""

        try:
            html = await tab.get_content()
        except Exception:
            return []
        return [{"text": text, "href": href} for text, href in extract_event_links(str(html or ""))]

    def extract_event_links_from_html(self, html_path: Path) -> list[dict[str, str]]:
        """Fallback event-link extraction from saved Betclic SSR/debug HTML."""

        try:
            html = html_path.read_text(encoding="utf-8")
        except OSError:
            return []
        return [{"text": text, "href": href} for text, href in extract_event_links(html)]

    def attach_offer_links(
        self,
        cards: list[ParsedBetclicOffer],
        event_links: list[dict[str, str]],
    ) -> list[ParsedBetclicOffer]:
        """Attach per-event Betclic URLs to cards parsed from body text."""

        enriched: list[ParsedBetclicOffer] = []
        used_hrefs: set[str] = set()
        for card in cards:
            if card.source_url != BETCLIC_LOL_URL:
                enriched.append(card)
                continue
            match = self.find_link_for_card(card, event_links, used_hrefs)
            if match is None:
                enriched.append(card)
                continue
            href = str(match.get("href"))
            used_hrefs.add(href)
            enriched.append(replace(card, source_url=href, bookmaker_event_id=self.extract_match_id(href)))
        return enriched

    @staticmethod
    def find_link_for_card(
        card: ParsedBetclicOffer,
        event_links: list[dict[str, str]],
        used_hrefs: set[str],
    ) -> dict[str, str] | None:
        """Find a DOM link whose visible text contains both teams."""

        team_a = card.raw_team_a.lower()
        team_b = card.raw_team_b.lower()
        team_a_compact = compact_text(card.raw_team_a)
        team_b_compact = compact_text(card.raw_team_b)
        for item in event_links:
            href = str(item.get("href") or "")
            if href in used_hrefs:
                continue
            text = str(item.get("text") or "").lower()
            compact = compact_text(text)
            if (team_a in text and team_b in text) or (team_a_compact in compact and team_b_compact in compact):
                return item
        return None

    @staticmethod
    def extract_match_id(url: str) -> str | None:
        """Extract Betclic numeric match ID from an event URL."""

        match = re.search(r"-m(?P<id>\d+)(?:$|[/?#])", url)
        return match.group("id") if match else None

    def parse_match_card(
        self,
        card: ParsedBetclicOffer,
        html_path: str | None = None,
        screenshot_path: str | None = None,
    ) -> RawOddsSnapshot | None:
        """Parse one Betclic match card into the common snapshot format."""

        start_label = " ".join(part for part in [card.date_label, card.start_time_label] if part) or None
        offer_url = card.source_url if card.source_url != BETCLIC_LOL_URL else None
        raw_payload = {
            "bookmaker_event_id": card.bookmaker_event_id,
            "market_count_label": card.market_count_label,
            "raw_text": card.raw_text,
            "source_url": self.start_url,
            "offer_url": offer_url,
        }
        return RawOddsSnapshot(
            bookmaker=self.bookmaker,
            raw_team_a=card.raw_team_a,
            raw_team_b=card.raw_team_b,
            odds_a=card.odds_a,
            odds_b=card.odds_b,
            scraped_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
            raw_league=card.league,
            match_start_time=start_label,
            source_url=self.start_url,
            offer_url=offer_url,
            market_type="match_winner",
            is_live=False,
            scraper_name="betclic_nodriver_lol_match_winner",
            scraper_version=SCRAPER_VERSION,
            raw_payload=raw_payload,
            page_html_path=str(html_path) if html_path else None,
            screenshot_path=str(screenshot_path) if screenshot_path else None,
        )


def compact_text(value: str) -> str:
    """Normalize text for matching team names split by DOM line wraps."""

    return re.sub(r"\s+", "", value.lower())
