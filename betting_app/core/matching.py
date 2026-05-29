"""Team-name normalization and fuzzy matching."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher


STOP_WORDS = {"esports", "esport", "gaming", "team", "lol", "leagueoflegends"}


def normalize_team_name(name: str) -> str:
    """Normalize a bookmaker/GOL.GG team name for matching."""

    ascii_name = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode("ascii")
    ascii_name = ascii_name.lower()
    ascii_name = re.sub(r"[^a-z0-9]+", " ", ascii_name)
    tokens = [token for token in ascii_name.split() if token and token not in STOP_WORDS]
    return " ".join(tokens).strip()


def similarity(left: str, right: str) -> float:
    """Return normalized fuzzy similarity in [0, 1]."""

    norm_left = normalize_team_name(left)
    norm_right = normalize_team_name(right)
    if not norm_left or not norm_right:
        return 0.0
    if norm_left == norm_right:
        return 1.0
    token_left = set(norm_left.split())
    token_right = set(norm_right.split())
    token_score = len(token_left & token_right) / max(len(token_left | token_right), 1)
    seq_score = SequenceMatcher(None, norm_left, norm_right).ratio()
    return max(seq_score, token_score)


def best_match(raw_name: str, candidates: list[str], min_confidence: float = 0.72) -> tuple[str | None, float]:
    """Find the best candidate team name for a raw bookmaker name."""

    if not candidates:
        return None, 0.0
    scored = [(candidate, similarity(raw_name, candidate)) for candidate in candidates]
    candidate, score = max(scored, key=lambda item: item[1])
    if score < min_confidence:
        return None, score
    return candidate, score
