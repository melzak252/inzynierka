import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def normalize_team_name(name: str | None) -> str:
    """Normalize a team name for fuzzy cross-source matching.

    Args:
        name: Raw team name from GOL.GG or OddsPortal.

    Returns:
        Lowercase alphanumeric identifier with common esports suffixes removed.
    """
    if not name:
        return ""
    name = str(name).lower()
    name = re.sub(
        r"\b(esports|gaming|challengers|academy|team|club|e-sports|esport|academy|challengers|pro|squad)\b",
        "",
        name,
    )
    name = re.sub(r"[^a-z0-9]", "", name)
    return name


def load_aliases(filepath: str | Path) -> dict[str, str]:
    """Load manually curated team-name aliases.

    Args:
        filepath: Path to the JSON alias file.

    Returns:
        Alias dictionary mapping normalized source names to normalized target names.
    """
    path = Path(filepath)
    if path.exists():
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    return {
        "tsm": "teamsolomid",
        "clg": "counterlogicgaming",
        "c9": "cloud9",
        "tl": "teamliquid",
        "t1": "skt1",
        "skt": "skt1",
        "sktelecomt1": "skt1",
        "g2": "g2esports",
        "fnc": "fnatic",
        "ig": "invictusgaming",
        "rng": "royalnevergiveup",
        "edg": "edwardgaming",
        "dwg": "damwongaming",
        "dk": "damwongaming",
        "gen": "geng",
        "fly": "flyquest",
        "nrg": "nrgesports",
        "100t": "100thieves",
        "msf": "misfits",
        "vit": "vitality",
        "rge": "rogue",
        "mad": "madlions",
        "ast": "astralis",
        "xl": "excel",
        "sk": "skgaming",
        "th": "teamheretics",
        "gx": "giantx",
        "kc": "karminecorp",
        "m8": "m80",
        "dig": "dignitas",
        "sr": "shopifyrebellion",
        "lyon": "lyon",
    }


def save_aliases(aliases: dict[str, str], filepath: str | Path) -> None:
    """Save team-name aliases to JSON.

    Args:
        aliases: Alias dictionary to persist.
        filepath: Target JSON path.
    """
    path = Path(filepath)
    with path.open("w", encoding="utf-8") as file:
        json.dump(aliases, file, indent=4)


def apply_alias(name: str, aliases: dict[str, str]) -> str:
    """Apply an alias mapping to a normalized team name.

    Args:
        name: Normalized team name.
        aliases: Alias dictionary.

    Returns:
        Alias target if available, otherwise the original name.
    """
    return aliases.get(name, name)


def map_matches(
    oddsportal_csv: str | Path,
    golgg_json: str | Path,
    output_csv: str | Path,
    aliases_json: str | Path,
) -> None:
    """Map OddsPortal rows to GOL.GG match identifiers.

    Args:
        oddsportal_csv: Raw OddsPortal CSV export.
        golgg_json: Parsed GOL.GG match dataset.
        output_csv: Target path for mapped odds rows.
        aliases_json: JSON file used to persist discovered name aliases.
    """
    print(f"Loading {oddsportal_csv}...")
    df_odds = pd.read_csv(oddsportal_csv)

    print(f"Loading {golgg_json}...")
    with Path(golgg_json).open("r", encoding="utf-8") as file:
        golgg_data: list[dict[str, Any]] = json.load(file)

    aliases = load_aliases(aliases_json)

    golgg_by_date = {}
    for match in golgg_data:
        date = match["date"]
        if date not in golgg_by_date:
            golgg_by_date[date] = []
        golgg_by_date[date].append(match)

    results = []
    matched_odds_indices = set()
    matched_golgg_ids = set()

    unmatched_odds = []
    for idx, row in df_odds.iterrows():
        date_val = str(row["date"])
        odds_date_str = date_val.split(" ")[0]
        try:
            odds_date = datetime.strptime(odds_date_str, "%Y-%m-%d")
        except ValueError:
            continue

        unmatched_odds.append(
            {
                "idx": idx,
                "row": row,
                "odds_date": odds_date,
                "odds_date_str": odds_date_str,
            }
        )

    def add_match(odds_item, golgg_match, offset, new_aliases=None, swapped=False):
        if new_aliases:
            for k, v in new_aliases.items():
                if k and v and k != v:
                    aliases[k] = v

        row = odds_item["row"]

        # Determine which odds to use for which team
        if not swapped:
            o1_suffix = "home"
            o2_suffix = "away"
            o1_prefix = "odds1"
            o2_prefix = "odds2"
        else:
            o1_suffix = "away"
            o2_suffix = "home"
            o1_prefix = "odds2"
            o2_prefix = "odds1"

        results.append(
            {
                "golgg_match_id": golgg_match["match_id"],
                "odds_date": odds_item["odds_date_str"],
                "golgg_date": golgg_match["date"],
                "golgg_team1": golgg_match["name_1"],
                "golgg_team2": golgg_match["name_2"],
                "t1_score": golgg_match["score_1"],
                "t2_score": golgg_match["score_2"],
                "t1_win": golgg_match["t1_win"],
                "t2_win": golgg_match["t2_win"],
                "draw": golgg_match["draw"],
                "match_type": "exact" if offset == 0 else "date_offset",
                "tournament": row["tournament"],
                "avg_odds_home": row[f"avg_odds_{o1_suffix}"],
                "avg_odds_away": row[f"avg_odds_{o2_suffix}"],
                "avg_open_home": row[f"avg_open_{o1_suffix}"],
                "avg_open_away": row[f"avg_open_{o2_suffix}"],
                "odds1_betclic_close": row[f"{o1_prefix}_betclic_close"],
                "odds1_betclic_open": row[f"{o1_prefix}_betclic_open"],
                "odds2_betclic_close": row[f"{o2_prefix}_betclic_close"],
                "odds2_betclic_open": row[f"{o2_prefix}_betclic_open"],
                "odds1_betfan_close": row[f"{o1_prefix}_betfan_close"],
                "odds1_betfan_open": row[f"{o1_prefix}_betfan_open"],
                "odds2_betfan_close": row[f"{o2_prefix}_betfan_close"],
                "odds2_betfan_open": row[f"{o2_prefix}_betfan_open"],
                "odds1_efortuna_close": row[f"{o1_prefix}_efortuna_close"],
                "odds1_efortuna_open": row[f"{o1_prefix}_efortuna_open"],
                "odds2_efortuna_close": row[f"{o2_prefix}_efortuna_close"],
                "odds2_efortuna_open": row[f"{o2_prefix}_efortuna_open"],
                "odds1_lv_bet_close": row[f"{o1_prefix}_lv_bet_close"],
                "odds1_lv_bet_open": row[f"{o1_prefix}_lv_bet_open"],
                "odds2_lv_bet_close": row[f"{o2_prefix}_lv_bet_close"],
                "odds2_lv_bet_open": row[f"{o2_prefix}_lv_bet_open"],
                "odds1_sts_close": row[f"{o1_prefix}_sts_close"],
                "odds1_sts_open": row[f"{o1_prefix}_sts_open"],
                "odds2_sts_close": row[f"{o2_prefix}_sts_close"],
                "odds2_sts_open": row[f"{o2_prefix}_sts_open"],
                "odds1_superbet_close": row[f"{o1_prefix}_superbet_close"],
                "odds1_superbet_open": row[f"{o1_prefix}_superbet_open"],
                "odds2_superbet_close": row[f"{o2_prefix}_superbet_close"],
                "odds2_superbet_open": row[f"{o2_prefix}_superbet_open"],
                "odds1_fuksiarz_close": row[f"{o1_prefix}_fuksiarz_close"],
                "odds1_fuksiarz_open": row[f"{o1_prefix}_fuksiarz_open"],
                "odds2_fuksiarz_close": row[f"{o2_prefix}_fuksiarz_close"],
                "odds2_fuksiarz_open": row[f"{o2_prefix}_fuksiarz_open"],
                "oddsportal_url": row["url"],
            }
        )
        matched_odds_indices.add(odds_item["idx"])
        matched_golgg_ids.add(golgg_match["match_id"])

    # Pass 1: Exact match
    print("Pass 1: Exact matches...")
    for item in unmatched_odds:
        if item["idx"] in matched_odds_indices:
            continue

        row = item["row"]
        t1_raw = normalize_team_name(row["home_team"])
        t2_raw = normalize_team_name(row["away_team"])
        t1_odds = apply_alias(t1_raw, aliases)
        t2_odds = apply_alias(t2_raw, aliases)

        match_found = False
        for offset in [0, -1, 1]:
            if match_found:
                break
            current_date = (item["odds_date"] + timedelta(days=offset)).strftime(
                "%Y-%m-%d"
            )
            if current_date not in golgg_by_date:
                continue

            for m in golgg_by_date[current_date]:
                if m["match_id"] in matched_golgg_ids:
                    continue

                m_t1_raw = normalize_team_name(m["name_1"])
                m_t2_raw = normalize_team_name(m["name_2"])
                m_t1 = apply_alias(m_t1_raw, aliases)
                m_t2 = apply_alias(m_t2_raw, aliases)

                if t1_odds == m_t1 and t2_odds == m_t2:
                    add_match(item, m, offset, swapped=False)
                    match_found = True
                    break
                if t1_odds == m_t2 and t2_odds == m_t1:
                    add_match(item, m, offset, swapped=True)
                    match_found = True
                    break

    # Pass 2: Partial match (one team + score)
    print("Pass 2: Partial matches (one team + score)...")
    for item in unmatched_odds:
        if item["idx"] in matched_odds_indices:
            continue

        row = item["row"]
        t1_raw = normalize_team_name(row["home_team"])
        t2_raw = normalize_team_name(row["away_team"])
        t1_odds = apply_alias(t1_raw, aliases)
        t2_odds = apply_alias(t2_raw, aliases)
        s1_odds = row["homeResult"]
        s2_odds = row["awayResult"]

        match_found = False
        for offset in [0, -1, 1]:
            if match_found:
                break
            current_date = (item["odds_date"] + timedelta(days=offset)).strftime(
                "%Y-%m-%d"
            )
            if current_date not in golgg_by_date:
                continue

            for m in golgg_by_date[current_date]:
                if m["match_id"] in matched_golgg_ids:
                    continue

                m_t1_raw = normalize_team_name(m["name_1"])
                m_t2_raw = normalize_team_name(m["name_2"])
                m_t1 = apply_alias(m_t1_raw, aliases)
                m_t2 = apply_alias(m_t2_raw, aliases)
                m_s1 = m["score_1"]
                m_s2 = m["score_2"]

                if t1_odds == m_t1 and s1_odds == m_s1 and s2_odds == m_s2:
                    add_match(item, m, offset, {t2_raw: m_t2_raw}, swapped=False)
                    match_found = True
                    break
                if t1_odds == m_t2 and s1_odds == m_s2 and s2_odds == m_s1:
                    add_match(item, m, offset, {t2_raw: m_t1_raw}, swapped=True)
                    match_found = True
                    break
                if t2_odds == m_t2 and s1_odds == m_s1 and s2_odds == m_s2:
                    add_match(item, m, offset, {t1_raw: m_t1_raw}, swapped=False)
                    match_found = True
                    break
                if t2_odds == m_t1 and s1_odds == m_s2 and s2_odds == m_s1:
                    add_match(item, m, offset, {t1_raw: m_t2_raw}, swapped=True)
                    match_found = True
                    break

    # Pass 3: Unique score match per day
    print("Pass 3: Unique score matches per day...")
    # Group unmatched odds by date and score
    for offset in [0, -1, 1]:
        unmatched_odds_current = [
            item for item in unmatched_odds if item["idx"] not in matched_odds_indices
        ]

        odds_by_date_score = {}
        for item in unmatched_odds_current:
            date_key = (item["odds_date"] + timedelta(days=offset)).strftime("%Y-%m-%d")
            s1 = item["row"]["homeResult"]
            s2 = item["row"]["awayResult"]
            score_key = tuple(sorted([s1, s2]))

            key = (date_key, score_key)
            if key not in odds_by_date_score:
                odds_by_date_score[key] = []
            odds_by_date_score[key].append(item)

        for key, odds_items in odds_by_date_score.items():
            if len(odds_items) == 1:
                date_key, score_key = key
                if date_key in golgg_by_date:
                    # Find unmatched golgg matches with this score
                    matching_golgg = []
                    for m in golgg_by_date[date_key]:
                        if m["match_id"] in matched_golgg_ids:
                            continue
                        m_score_key = tuple(sorted([m["score_1"], m["score_2"]]))
                        if m_score_key == score_key:
                            matching_golgg.append(m)

                    if len(matching_golgg) == 1:
                        item = odds_items[0]
                        m = matching_golgg[0]

                        row = item["row"]
                        t1_raw = normalize_team_name(row["home_team"])
                        t2_raw = normalize_team_name(row["away_team"])
                        s1_odds = row["homeResult"]
                        s2_odds = row["awayResult"]

                        m_t1_raw = normalize_team_name(m["name_1"])
                        m_t2_raw = normalize_team_name(m["name_2"])
                        m_s1 = m["score_1"]
                        m_s2 = m["score_2"]

                        new_aliases = {}
                        if s1_odds == m_s1 and s2_odds == m_s2:
                            if s1_odds != s2_odds:
                                new_aliases[t1_raw] = m_t1_raw
                                new_aliases[t2_raw] = m_t2_raw
                            else:
                                new_aliases[t1_raw] = m_t1_raw
                                new_aliases[t2_raw] = m_t2_raw
                            add_match(item, m, offset, new_aliases, swapped=False)
                        elif s1_odds == m_s2 and s2_odds == m_s1:
                            new_aliases[t1_raw] = m_t2_raw
                            new_aliases[t2_raw] = m_t1_raw
                            add_match(item, m, offset, new_aliases, swapped=True)


    # Pass 4: Exact match again with new aliases
    print("Pass 4: Exact matches with new aliases...")
    for item in unmatched_odds:
        if item["idx"] in matched_odds_indices:
            continue

        row = item["row"]
        t1_raw = normalize_team_name(row["home_team"])
        t2_raw = normalize_team_name(row["away_team"])
        t1_odds = apply_alias(t1_raw, aliases)
        t2_odds = apply_alias(t2_raw, aliases)

        match_found = False
        for offset in [0, -1, 1]:
            if match_found:
                break
            current_date = (item["odds_date"] + timedelta(days=offset)).strftime(
                "%Y-%m-%d"
            )
            if current_date not in golgg_by_date:
                continue

            for m in golgg_by_date[current_date]:
                if m["match_id"] in matched_golgg_ids:
                    continue

                m_t1_raw = normalize_team_name(m["name_1"])
                m_t2_raw = normalize_team_name(m["name_2"])
                m_t1 = apply_alias(m_t1_raw, aliases)
                m_t2 = apply_alias(m_t2_raw, aliases)

                if t1_odds == m_t1 and t2_odds == m_t2:
                    add_match(item, m, offset, swapped=False)
                    match_found = True
                    break
                if t1_odds == m_t2 and t2_odds == m_t1:
                    add_match(item, m, offset, swapped=True)
                    match_found = True
                    break

    total_odds = len(df_odds)
    matched_count = len(matched_odds_indices)
    match_percentage = (matched_count / total_odds) * 100 if total_odds > 0 else 0

    print(
        f"Matched {matched_count} out of {total_odds} matches ({match_percentage:.2f}%)."
    )

    save_aliases(aliases, aliases_json)
    print(f"Aliases saved to {aliases_json}")

    mapping_df = pd.DataFrame(results)
    mapping_df.to_csv(output_csv, index=False)
    print(f"Mapping saved to {output_csv}")


if __name__ == "__main__":
    map_matches(
        PROJECT_ROOT / "data" / "oddsportal_matches.csv",
        PROJECT_ROOT / "data" / "golgg_matches.json",
        PROJECT_ROOT / "data" / "odds.csv",
        PROJECT_ROOT / "data" / "aliases.json",
    )
