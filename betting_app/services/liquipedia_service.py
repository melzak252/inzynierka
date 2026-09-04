"""Client and synchronizer for fetching upcoming matches and Best-of format from Liquipedia API."""

from __future__ import annotations

import gzip
import json
import logging
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Sequence

from bs4 import BeautifulSoup

from betting_app.core.db import connect, transaction
from betting_app.services.canonical_match_service import canonical_team_key

logger = logging.getLogger(__name__)

LIQUIPEDIA_API_URL = "https://liquipedia.net/leagueoflegends/api.php"
DEFAULT_USER_AGENT = "EnsembleLegendsResearch/1.0 (academic research; melzacki.jakubl@gmail.com)"


@dataclass(frozen=True)
class LiquipediaMatch:
    team1: str
    team2: str
    best_of: int | None
    tournament: str | None
    start_time: datetime | None


class LiquipediaClient:
    """Client for querying the Liquipedia MediaWiki API using template expansion."""

    def __init__(self, api_url: str = LIQUIPEDIA_API_URL, user_agent: str = DEFAULT_USER_AGENT):
        self.api_url = api_url
        self.user_agent = user_agent

    def fetch_recent_and_upcoming_matches(self, limit: int = 50) -> list[LiquipediaMatch]:
        """Fetch matches parsed from the Match/Ticker/Container widget template."""
        params = {
            "action": "expandtemplates",
            "text": f"{{{{#invoke:Lua|invoke|module=Widget/Factory|fn=fromTemplate|widget=Match/Ticker/Container|limit={limit}}}}}",
            "prop": "wikitext",
            "format": "json",
        }
        url = f"{self.api_url}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept-Encoding": "gzip",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
                if resp.info().get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                data = json.loads(raw.decode("utf-8"))
        except Exception as e:
            logger.error("Failed to fetch matches from Liquipedia: %s", e)
            return []

        html = data.get("expandtemplates", {}).get("wikitext", "")
        if not html:
            return []

        return self._parse_matches_html(html)

    def _parse_matches_html(self, html: str) -> list[LiquipediaMatch]:
        soup = BeautifulSoup(html, "html.parser")
        matches: list[LiquipediaMatch] = []

        for block in soup.find_all("div", class_="match-info"):
            time_div = block.find("span", class_="timer-object")
            start_time = None
            if time_div and time_div.get("data-timestamp"):
                try:
                    ts = int(time_div["data-timestamp"])
                    start_time = datetime.fromtimestamp(ts, tz=UTC)
                except (ValueError, TypeError):
                    pass

            header = block.find("div", class_="match-info-header")
            if not header:
                continue

            opp_left = header.find("div", class_="match-info-header-opponent-left")
            opp_right_candidates = header.find_all("div", class_="match-info-header-opponent")
            opp_right = opp_right_candidates[1] if len(opp_right_candidates) > 1 else None

            scoreholder = header.find("div", class_="match-info-header-scoreholder")
            best_of = None
            if scoreholder:
                bo_match = re.search(r"\(Bo(\d)\)", scoreholder.get_text())
                if bo_match:
                    try:
                        best_of = int(bo_match.group(1))
                    except ValueError:
                        pass

            tourn = block.find("div", class_="match-info-tournament")
            tourn_name = None
            if tourn:
                clean_tourn = tourn.get_text(strip=True)
                clean_tourn = re.sub(r"\[\[File:[^\]]+\]\]", "", clean_tourn)
                clean_tourn = re.sub(r"\[\[[^\|\]]+\|([^\]]+)\]\]", r"\1", clean_tourn)
                tourn_name = clean_tourn.strip() or None

            if opp_left and opp_right:
                team1 = self._clean_team_text(opp_left.get_text(strip=True))
                team2 = self._clean_team_text(opp_right.get_text(strip=True))
                if team1 and team2:
                    matches.append(
                        LiquipediaMatch(
                            team1=team1,
                            team2=team2,
                            best_of=best_of,
                            tournament=tourn_name,
                            start_time=start_time,
                        )
                    )

        return matches

    @staticmethod
    def _clean_team_text(text: str) -> str:
        text = re.sub(r"\[\[File:[^\]]+\]\]", "", text)
        m = re.search(r"\[\[([^\|\]]+)(?:\|([^\]]+))?\]\]", text)
        if m:
            return m.group(1).strip()
        return text.strip()


def sync_liquipedia_best_of(limit: int = 50) -> dict[str, Any]:
    """Fetch recent/upcoming matches from Liquipedia and update canonical_matches.best_of when missing or divergent."""
    client = LiquipediaClient()
    lq_matches = client.fetch_recent_and_upcoming_matches(limit=limit)
    if not lq_matches:
        return {"fetched": 0, "matched": 0, "updated": 0}

    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, normalized_team_a, normalized_team_b, best_of, start_time_normalized, status
            FROM canonical_matches
            WHERE status IN ('upcoming', 'live', 'finished', 'completed')
            ORDER BY id DESC
            LIMIT 500
            """
        ).fetchall()

    canonical_list = [dict(r) for r in rows]
    updated_count = 0
    matched_count = 0

    to_update: list[tuple[int, int]] = []

    for lq in lq_matches:
        if not lq.best_of:
            continue

        lq_k1 = canonical_team_key(lq.team1)
        lq_k2 = canonical_team_key(lq.team2)
        if not lq_k1 or not lq_k2:
            continue

        for cm in canonical_list:
            cm_k1 = canonical_team_key(cm.get("normalized_team_a") or "")
            cm_k2 = canonical_team_key(cm.get("normalized_team_b") or "")

            if (lq_k1 == cm_k1 and lq_k2 == cm_k2) or (lq_k1 == cm_k2 and lq_k2 == cm_k1):
                matched_count += 1
                if cm.get("best_of") != lq.best_of:
                    to_update.append((lq.best_of, int(cm["id"])))
                    cm["best_of"] = lq.best_of
                break

    if to_update:
        with transaction() as conn:
            for bo, cid in to_update:
                conn.execute(
                    "UPDATE canonical_matches SET best_of = ? WHERE id = ?",
                    (bo, cid),
                )
                updated_count += 1

    logger.info(
        "Liquipedia BoN sync: fetched=%d matched=%d updated=%d",
        len(lq_matches),
        matched_count,
        updated_count,
    )
    return {
        "fetched": len(lq_matches),
        "matched": matched_count,
        "updated": updated_count,
    }
