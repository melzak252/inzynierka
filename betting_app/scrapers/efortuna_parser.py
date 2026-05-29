"""Parser utilities for eFortuna League of Legends prematch pages."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit


EFORTUNA_LOL_URL = "https://www.efortuna.pl/zaklady-bukmacherskie/esport-lol"

EFORTUNA_LOL_LEAGUE_URLS = [
    "https://www.efortuna.pl/zaklady-bukmacherskie/esport-lol/miedzynarodowe-4/lec?tab=matches&filter=all",
    "https://www.efortuna.pl/zaklady-bukmacherskie/esport-lol/miedzynarodowe-4/lck?tab=matches&filter=all",
    "https://www.efortuna.pl/zaklady-bukmacherskie/esport-lol/miedzynarodowe-4/lpl?tab=matches&filter=all",
    "https://www.efortuna.pl/zaklady-bukmacherskie/esport-lol/miedzynarodowe-4/lcs-na?tab=matches&filter=all",
    "https://www.efortuna.pl/zaklady-bukmacherskie/esport-lol/miedzynarodowe-4/lcp?tab=matches&filter=all",
    "https://www.efortuna.pl/zaklady-bukmacherskie/esport-lol/miedzynarodowe-4/lvp?tab=matches&filter=all",
    "https://www.efortuna.pl/zaklady-bukmacherskie/esport-lol/miedzynarodowe-4/lfl?tab=matches&filter=all",
    "https://www.efortuna.pl/zaklady-bukmacherskie/esport-lol/miedzynarodowe-4/nacl?tab=matches&filter=all",
    "https://www.efortuna.pl/zaklady-bukmacherskie/esport-lol/miedzynarodowe-4/prime-league?tab=matches&filter=all",
    "https://www.efortuna.pl/zaklady-bukmacherskie/esport-lol/lol/italian-tournament?tab=matches&filter=all",
    "https://www.efortuna.pl/zaklady-bukmacherskie/esport-lol/lol/lplol?tab=matches&filter=all",
]


@dataclass(frozen=True)
class ParsedEFortunaOffer:
    """One parsed eFortuna LoL match-winner offer."""

    league: str
    raw_team_a: str
    raw_team_b: str
    odds_a: float
    odds_b: float
    source_url: str
    offer_url: str | None = None
    start_time_label: str | None = None
    raw_text: str | None = None


TIME_RE = re.compile(r"^(dzisiaj|jutro)\s+\d{1,2}:\d{2}$", re.IGNORECASE)
FULL_DATE_RE = re.compile(r"^[a-ząćęłńóśźż]{2,8}\.,\s*\d{1,2}\.\d{2}\.\d{4},\s*\d{1,2}:\d{2}$", re.IGNORECASE)
ODD_RE = re.compile(r"^\d+[,.]\d{2}$")


def parse_efortuna_lol_offers(text: str, *, source_url: str, offer_url: str | None = None) -> list[ParsedEFortunaOffer]:
    """Parse visible eFortuna LoL match-winner offers from rendered text."""

    lines = [normalize_space(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    league = infer_league(lines, source_url)
    offers: list[ParsedEFortunaOffer] = []
    i = 0
    while i < len(lines) - 7:
        if not is_start_time(lines[i]):
            i += 1
            continue
        start = lines[i]
        team_a = lines[i + 1]
        team_b = lines[i + 2]
        if lines[i + 3].lower() != "zwycięzca meczu":
            i += 1
            continue
        if lines[i + 4] != team_a or not ODD_RE.match(lines[i + 5]) or lines[i + 6] != team_b or not ODD_RE.match(lines[i + 7]):
            i += 1
            continue
        offers.append(
            ParsedEFortunaOffer(
                league=league,
                raw_team_a=team_a,
                raw_team_b=team_b,
                odds_a=parse_decimal_odd(lines[i + 5]),
                odds_b=parse_decimal_odd(lines[i + 7]),
                source_url=source_url,
                offer_url=offer_url or build_offer_url(source_url, team_a, team_b),
                start_time_label=start,
                raw_text="\n".join(lines[i : i + 8]),
            )
        )
        i += 8
    return offers


def infer_league(lines: list[str], source_url: str) -> str:
    """Infer league label from visible breadcrumb or URL."""

    slug = source_url.rstrip("/").split("/")[-1].split("?")[0]
    slug_map = {
        "lec": "LEC",
        "lck": "LCK",
        "lpl": "LPL",
        "lcs-na": "LCS NA",
        "lcp": "LCP",
        "lvp": "LES",
        "lfl": "LFL",
        "nacl": "NACL",
        "prime-league": "Prime League",
        "italian-tournament": "LIT",
        "lplol": "LPLOL",
    }
    if slug in slug_map:
        return slug_map[slug]

    for i, line in enumerate(lines[:-1]):
        if line == "Esport LOL" and i + 3 < len(lines):
            # Shape on league pages: Esport LOL / Międzynarodowe LCK LCK ...
            candidates = [candidate for candidate in lines[i + 1 : i + 8] if candidate not in {"/", "Międzynarodowe", "LOL", "Wszystko"}]
            if candidates:
                return candidates[0]
    return slug.replace("-", " ").upper() if slug else "Esport LOL"


def is_start_time(line: str) -> bool:
    """Detect Fortuna prematch start labels."""

    return bool(TIME_RE.match(line) or FULL_DATE_RE.match(line))


def parse_decimal_odd(value: str) -> float:
    """Parse decimal odd."""

    return float(value.replace(",", "."))


def build_offer_url(source_url: str, team_a: str, team_b: str) -> str:
    """Build eFortuna event details URL used after clicking a fixture card."""

    parts = urlsplit(source_url)
    base_path = parts.path.rstrip("/")
    slug = slugify(f"{team_a}-{team_b}")
    if not slug:
        return source_url
    return urlunsplit((parts.scheme, parts.netloc, f"{base_path}/{slug}", "tab=offer&filter=all", ""))


def slugify(value: str) -> str:
    """Approximate eFortuna route slug for fixture detail pages."""

    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_value = ascii_value.replace(".", "-")
    ascii_value = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value.lower())
    return re.sub(r"-+", "-", ascii_value).strip("-")


def normalize_space(value: str) -> str:
    """Collapse whitespace."""

    return re.sub(r"\s+", " ", value).strip()
