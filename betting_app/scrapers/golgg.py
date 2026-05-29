"""Async GOL.GG scraper vendored into the betting app.

This module is based on the scraper that previously lived in
`/home/melzak/dev/embedded-rift/src/utils/scrapers/golgg.py`.  Keeping it here
removes the runtime dependency on the external `embedded-rift` checkout when the
betting app runs unattended on a laptop/container.
"""

from __future__ import annotations

import asyncio
import re
from typing import Self
from urllib.parse import quote, urljoin

import httpx
import parsel


GOLGG_URL = "https://gol.gg"
GOLGG_TOURNAMENT_API = "https://gol.gg/tournament/ajax.trlist.php"
INDEX_TO_ROLE = {
    0: "TOP",
    1: "JUNGLE",
    2: "MID",
    3: "ADC",
    4: "SUPPORT",
}
GAME_FETCH_RETRIES = 3


def extract_champion_from_player_row(player_row: parsel.Selector) -> dict:
    """Extract champion metadata from a GOL.GG player row."""

    champion_links = player_row.css('a[href*="champion/champion-stats"]')
    if not champion_links:
        return {"champion_id": None, "champion_name": None, "champion_image": None}

    champion_link = champion_links[0]
    champion_href = champion_link.css("::attr(href)").get()
    champion_img = champion_link.css("img")
    champion_name = champion_img.css("::attr(alt)").get()
    champion_image = champion_img.css("::attr(src)").get()

    champion_id = None
    match = re.search(r"champion-stats/(\d+)/", champion_href or "")
    if match:
        champion_id = match.group(1)

    return {
        "champion_id": champion_id,
        "champion_name": champion_name,
        "champion_image": urljoin(GOLGG_URL, champion_image) if champion_image else None,
    }


def infer_best_of(t1_score: int, t2_score: int) -> int | None:
    """Infer best-of from a completed match score."""

    if t1_score == t2_score:
        games_played = t1_score + t2_score
        return games_played if games_played > 0 else None
    wins_needed = max(t1_score, t2_score)
    if wins_needed <= 0:
        return None
    return (wins_needed * 2) - 1


class GolggScraper:
    """Async HTTP/parsel scraper for GOL.GG tournaments, matches and games."""

    def __init__(self, max_pages: int = 20):
        self.semaphore = asyncio.Semaphore(max_pages)
        self.client: httpx.AsyncClient | None = None

    async def start(self, headless: bool = True) -> Self:
        self.client = httpx.AsyncClient(
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko)",
            },
            follow_redirects=True,
            timeout=30.0,
            limits=httpx.Limits(
                max_connections=max(100, self.semaphore._value * 4),
                max_keepalive_connections=max(20, self.semaphore._value),
            ),
        )
        return self

    async def stop(self) -> None:
        if self.client:
            await self.client.aclose()

    async def __aenter__(self) -> Self:
        return await self.start()

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.stop()

    async def get_tournaments_in_season(self, season: int = 9) -> list[dict]:
        if not self.client:
            raise RuntimeError("GolggScraper is not started")
        response = await self.client.post(GOLGG_TOURNAMENT_API, data={"season": f"S{season}"})
        response.raise_for_status()
        return response.json()

    async def get_all_tournaments(self) -> list[dict]:
        result = []
        for season in range(2, 17):
            result.extend(await self.get_tournaments_in_season(season))
        return result

    async def get_matches_in_tournament(self, tournament_name: str) -> list[dict]:
        """Return completed match metadata for one tournament."""

        if not self.client:
            raise RuntimeError("GolggScraper is not started")
        failed = []
        url = f"{GOLGG_URL}/tournament/tournament-matchlist/{quote(tournament_name)}/"
        response = await self.client.get(url)
        response.raise_for_status()
        sel = parsel.Selector(text=response.content.decode("utf-8"))
        tables = sel.css(".table_list")
        matches_table = next((table for table in tables if "data-sort" in table.attrib), None)
        if not matches_table:
            print("Couldn't find games table in", url)
            return []

        matches = []
        for row in matches_table.css("tbody tr"):
            try:
                href = row.css("a::attr(href)").get()
                if not href:
                    continue
                link_text = row.css("a::text").get()
                if not link_text or " vs " not in link_text:
                    continue
                match = re.search(r"stats/(\d+)/", href)
                if not match:
                    print("Couldn't extract match id from", href)
                    continue

                match_id = match.group(1)
                team_a, team_b = [part.strip() for part in link_text.split(" vs ", 1)]
                won = row.css("td.text_victory::text").get()
                lost = row.css("td.text_defeat::text").get()
                score = row.css("td:nth-child(3)::text").get()
                if not score or "-" not in score:
                    continue
                score_left_raw, score_right_raw = score.strip().split("-", 1)
                score_left = int(score_left_raw.strip())
                score_right = int(score_right_raw.strip())

                # GOL.GG renders score as winner-loser, not always team_a-team_b.
                if won == team_a:
                    team_a_score, team_b_score = score_left, score_right
                elif won == team_b:
                    team_a_score, team_b_score = score_right, score_left
                else:
                    team_a_score, team_b_score = score_left, score_right

                matches.append(
                    {
                        "match_id": match_id,
                        "tournament_name": tournament_name,
                        "link": href,
                        "sname_t1": team_a,
                        "sname_t2": team_b,
                        "won": won,
                        "lost": lost,
                        "score": score.strip(),
                        "t1_score": team_a_score,
                        "t2_score": team_b_score,
                        "games_played": team_a_score + team_b_score,
                        "t1_win": team_a_score > team_b_score,
                        "t2_win": team_b_score > team_a_score,
                        "draw": team_a_score == team_b_score,
                        "best_of": infer_best_of(team_a_score, team_b_score),
                        "patch": row.css("td:nth-child(6)::text").get(),
                        "date": row.css("td:nth-child(7)::text").get(),
                    }
                )
            except Exception as exc:
                print("Error processing row:", exc)
                failed.append(row.get())
                continue
        if failed:
            print(f"Skipped {len(failed)} malformed rows for tournament {tournament_name}")
        return matches

    async def get_game_selector(self, game_id: str) -> parsel.Selector:
        if not self.client:
            raise RuntimeError("GolggScraper is not started")
        url = f"{GOLGG_URL}/game/stats/{game_id}/page-game/"
        async with self.semaphore:
            response = await self.client.get(url)
        response.raise_for_status()
        return parsel.Selector(text=response.content.decode("utf-8"))

    async def get_players_stats(self, game_id: str) -> dict[str, dict]:
        if not self.client:
            raise RuntimeError("GolggScraper is not started")
        url = f"{GOLGG_URL}/game/stats/{game_id}/page-fullstats/"
        async with self.semaphore:
            response = await self.client.get(url)
        response.raise_for_status()
        sel = parsel.Selector(text=response.content.decode("utf-8"))
        rows = sel.css(".completestats").xpath("./tr")
        result = {
            "blue": {role: {} for role in INDEX_TO_ROLE.values()},
            "red": {role: {} for role in INDEX_TO_ROLE.values()},
        }

        for row in rows:
            tds = row.css("td::text").getall()
            if not tds:
                continue
            title, *stats = tds
            title = title.strip().replace(" ", "_").replace(":", "").replace("'", "").lower()
            if len(stats) != 10:
                stats = [None] * 10
            if title.endswith("%"):
                parsed_stats = [float(s[:-1]) / 100 if s else None for s in stats]
            else:
                parsed_stats = [float(s) if s and s.replace("-", "").replace(".", "").isnumeric() else s for s in stats]

            for i, (blue_stat, red_stat) in enumerate(zip(parsed_stats[:5], parsed_stats[5:])):
                role = INDEX_TO_ROLE.get(i, "UNKNOWN")
                result["blue"][role][title] = blue_stat
                result["red"][role][title] = red_stat
        return result

    async def get_players_in_game(self, game_sel: parsel.Selector) -> dict[str, dict]:
        """Return players by GOL.GG team id and role for one game page."""

        team_table = game_sel.css(".col-cadre")[0]
        team_row = team_table.xpath("./*")[1]
        team_1_block, team_2_block = team_row.xpath("./*")
        team_1_link = team_1_block.xpath("./*")[0].css("a::attr(href)").get()
        team_2_link = team_2_block.xpath("./*")[0].css("a::attr(href)").get()
        team_1_id = re.search(r"teams/team-stats/(\d+)/", team_1_link).group(1)
        team_2_id = re.search(r"teams/team-stats/(\d+)/", team_2_link).group(1)
        t1_players_table, t2_players_table = game_sel.css(".playersInfosLine")

        def parse_players(rows: list[parsel.Selector]) -> dict[str, dict]:
            players = {}
            for i, player in enumerate(rows):
                player_td = player.css("td")[0]
                champion_data = extract_champion_from_player_row(player)
                player_link = player_td.css("a")[1]
                href = player_link.css("::attr(href)").get()
                player_id_match = re.search(r"player-stats/(\d+)/", href or "")
                role = INDEX_TO_ROLE.get(i, "UNKNOWN")
                players[role] = {
                    "player_id": player_id_match.group(1) if player_id_match else None,
                    "player_name": player_link.css("::text").get(),
                    **champion_data,
                }
            return players

        return {
            team_1_id: parse_players(t1_players_table.xpath("./tr")),
            team_2_id: parse_players(t2_players_table.xpath("./tr")),
        }

    async def get_team_stats(self, game_sel: parsel.Selector) -> dict[str, dict]:
        result = {
            "blue_id": None,
            "red_id": None,
            "gameDuration": 0,
            "blue": {"kills": 0, "towers": 0, "dragons": 0, "nashors": 0, "gold": 0},
            "red": {"kills": 0, "towers": 0, "dragons": 0, "nashors": 0, "gold": 0},
        }

        team_info = game_sel.css(".col-cadre")[0]
        dur_row, stats_row = team_info.xpath("./div")
        dur_text = (dur_row.css("h1::text").get() or "").strip()
        if dur_text and ":" in dur_text:
            minutes, seconds = dur_text.split(":", 1)
            result["gameDuration"] = int(minutes) * 60 + int(seconds)

        blue, red = stats_row.xpath("./*")
        bteam, bstats, _champions = blue.xpath("./*")
        rteam, rstats, _ = red.xpath("./*")
        result["blue_id"] = re.search(r"teams/team-stats/(\d+)/", bteam.css("a::attr(href)").get().strip()).group(1)
        result["red_id"] = re.search(r"teams/team-stats/(\d+)/", rteam.css("a::attr(href)").get().strip()).group(1)

        def parse_side(stats_block: parsel.Selector, gold_uses_span: bool = False) -> dict:
            kills, towers, dragons, nashors, gold, _ = stats_block.xpath("./*")
            dragons_text = dragons.css("span::text").get()
            nashors_text = nashors.css("span::text").get()
            gold_text = (gold.css("span::text").get() if gold_uses_span else gold.css("::text").get()) or ""
            gold_text = gold_text.strip()
            return {
                "kills": int((kills.css("span::text").get() or "0").strip() or 0),
                "towers": int((towers.css("span::text").get() or "0").strip() or 0),
                "dragons": int(dragons_text.strip()) if dragons_text else 0,
                "nashors": int(nashors_text.strip()) if nashors_text else None,
                "gold": float(gold_text[:-1]) * 1000 if gold_text else 0,
            }

        result["blue"] = parse_side(bstats, gold_uses_span=False)
        result["red"] = parse_side(rstats, gold_uses_span=True)
        return result

    async def get_games_in_match(self, match_id: str) -> list[dict]:
        """Return nested game documents for one match id."""

        if not self.client:
            raise RuntimeError("GolggScraper is not started")
        url = f"{GOLGG_URL}/game/stats/{match_id}/page-summary/"
        async with self.semaphore:
            response = await self.client.get(url)
        response.raise_for_status()
        sel = parsel.Selector(text=response.content.decode("utf-8"))
        navbar = sel.css("#gameMenuToggler")
        if not navbar:
            print("Couldn't find navbar in", url)
            return []

        game_links = [el for el in navbar.css("li > a") if (el.css("::text").get() or "").strip().lower().startswith("game")]
        match_tables = sel.css(".col-cadre")
        if not match_tables:
            print("Couldn't find match table in", url)
            return []
        teams, *games_sel = match_tables[0].xpath("./*")
        t1_link, t2_link = teams.css("a")
        t1_id = re.search(r"teams/team-stats/(\d+)/", t1_link.css("::attr(href)").get()).group(1)
        t2_id = re.search(r"teams/team-stats/(\d+)/", t2_link.css("::attr(href)").get()).group(1)
        t1_name = t1_link.css("::text").get()
        t2_name = t2_link.css("::text").get()

        async def process_game(i: int, game_sel: parsel.Selector) -> dict | None:
            for attempt in range(1, GAME_FETCH_RETRIES + 1):
                try:
                    return await process_game_attempt(i, game_sel)
                except Exception as exc:
                    print(f"Error processing game {i + 1} in match {match_id} attempt {attempt}/{GAME_FETCH_RETRIES}: {exc}")
                    if attempt < GAME_FETCH_RETRIES:
                        await asyncio.sleep(attempt)
            return None

        async def process_game_attempt(i: int, game_sel: parsel.Selector) -> dict | None:
            if i >= len(game_links):
                print(f"Missing game link {i + 1} for match {match_id}")
                return None
            team_1, _, _team_2 = game_sel.xpath("./*")
            game_href = game_links[i].css("::attr(href)").get()
            game_match = re.search(r"game/stats/(\d+)/", game_href or "")
            if not game_match:
                print("Couldn't extract game id from", game_href)
                return None
            game_id = game_match.group(1)
            t1_win = bool(team_1.css(".text_victory"))

            game_page_sel, pstats = await asyncio.gather(
                self.get_game_selector(game_id),
                self.get_players_stats(game_id=game_id),
            )
            tstats = await self.get_team_stats(game_sel=game_page_sel)
            t1_side = "blue" if t1_id == tstats["blue_id"] else "red"
            t2_side = "red" if t1_side == "blue" else "blue"
            players = await self.get_players_in_game(game_sel=game_page_sel)
            for role, player in players[t1_id].items():
                player["stats"] = pstats[t1_side][role]
            for role, player in players[t2_id].items():
                player["stats"] = pstats[t2_side][role]

            return {
                "game_id": game_id,
                "match_id": match_id,
                "t1_id": t1_id,
                "t2_id": t2_id,
                "t1_name": t1_name,
                "t2_name": t2_name,
                "t1_win": t1_win,
                "t2_win": not t1_win,
                "draw": False,
                "t1_side": t1_side,
                "t2_side": t2_side,
                "t1_players": players[t1_id],
                "t2_players": players[t2_id],
                "t1_stats": tstats[t1_side],
                "t2_stats": tstats[t2_side],
                "game_duration": tstats["gameDuration"],
            }

        game_results = await asyncio.gather(*(process_game(i, game_sel) for i, game_sel in enumerate(games_sel)))
        return [game for game in game_results if game]

    async def get_team_players(self, team_id: str) -> list[dict]:
        """Return up to five current players for a team page."""

        if not self.client:
            raise RuntimeError("GolggScraper is not started")
        url = f"{GOLGG_URL}/teams/team-stats/{team_id}/split-ALL/tournament-ALL/"
        async with self.semaphore:
            response = await self.client.get(url)
        response.raise_for_status()
        sel = parsel.Selector(text=response.content.decode("utf-8"))
        players_table = sel.css(".table_list")[-1]
        team_players = []
        for player in players_table.xpath("./tbody/tr"):
            if len(player.css("td")) < 2 or len(team_players) >= 5:
                continue
            player_tds = player.css("td")
            href = player_tds[1].css("a::attr(href)").get()
            match = re.search(r"player-stats/(\d+)/", href or "")
            team_players.append(
                {
                    "role": (player_tds[0].css("::text").get() or "").strip(),
                    "player_id": match.group(1) if match else None,
                    "name": player_tds[1].css("a::text").get(),
                }
            )
        return team_players
