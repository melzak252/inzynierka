"""Map historical odds by independent team identities; reject ambiguous fixtures.

Date-only matching is retrospective. It does not certify quote availability before
prediction or match start. Existing exports and automatically learned aliases must
not be overwritten or silently treated as trustworthy inputs.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import json
from pathlib import Path
import re

import pandas as pd

BOOKMAKERS = ('betclic', 'betfan', 'efortuna', 'lv_bet', 'sts', 'superbet', 'fuksiarz')
QUOTE_PAIRS = (
    ('avg_odds_home', 'avg_odds_away'),
    ('avg_open_home', 'avg_open_away'),
    *((f'odds1_{book}_{period}', f'odds2_{book}_{period}')
      for book in BOOKMAKERS for period in ('close', 'open')),
)
PROVENANCE_COLUMNS = (
    'source_row', 'source_date', 'source_home_team', 'source_away_team',
    'source_home_result', 'source_away_result', 'source_sides_swapped',
    'date_offset_days', 'mapping_version',
)
OUTPUT_COLUMNS = (
    'golgg_match_id', 'odds_date', 'golgg_date', 'golgg_team1', 'golgg_team2',
    't1_score', 't2_score', 't1_win', 't2_win', 'draw', 'match_type', 'tournament',
    *(column for pair in QUOTE_PAIRS for column in pair), 'oddsportal_url',
    *PROVENANCE_COLUMNS,
)


def normalize_team_name(name: str | None) -> str:
    """Normalize generic organization words, retaining academy and squad identity."""
    if not isinstance(name, str):
        return ''
    name = re.sub(r'\b(esports|gaming|team|club|e-sports|esport)\b', '', name.lower())
    return re.sub(r'[^a-z0-9]', '', name)


def load_aliases(filepath: str | Path) -> dict[str, str]:
    """Load explicitly reviewed aliases; reject the old outcome-learned format.

    Expected JSON: {"reviewed": true, "aliases": {"source name": "target name"}}.
    Review is a human attestation, not proof supplied by this program. Use an empty
    aliases object when identity cannot be established independently of outcomes.
    """
    with Path(filepath).open(encoding='utf-8') as file:
        payload = json.load(file)
    if not isinstance(payload, dict) or payload.get('reviewed') is not True or not isinstance(payload.get('aliases'), dict):
        raise ValueError('Aliases must be explicitly reviewed; legacy learned aliases are unsafe.')
    aliases = {}
    for source, target in payload['aliases'].items():
        key, value = normalize_team_name(source), normalize_team_name(target)
        if not key or not value:
            raise ValueError('Reviewed aliases require nonempty team identities.')
        if key in aliases and aliases[key] != value:
            raise ValueError(f'Conflicting reviewed aliases for {source!r}.')
        aliases[key] = value
    for value in aliases.values():
        if value in aliases and aliases[value] != value:
            raise ValueError('Reviewed aliases must point directly to canonical identities, not chains or cycles.')
    return aliases


def apply_alias(name: str, aliases: dict[str, str]) -> str:
    return aliases.get(name, name)


def map_matches(oddsportal_csv: str | Path, golgg_json: str | Path,
                output_csv: str | Path, aliases_json: str | Path) -> None:
    """Write unique identity-aligned rows and an audit of every accepted/rejected row.

    Both teams must match. Prefer the same date; only if it has no candidate, inspect
    both adjacent dates together. Resolve the entire candidate graph before writing:
    neither outcomes nor consumption order can disambiguate repeated fixtures.
    Results may reject a uniquely identified fixture, but never choose its identity.
    """
    output = Path(output_csv)
    audit_path = output.with_suffix('.audit.json')
    for path in (output, audit_path):
        if path.exists():
            raise FileExistsError(f'Preserve existing evidence; choose a new output path: {path}')
    aliases = load_aliases(aliases_json)
    odds = pd.read_csv(oddsportal_csv)
    with Path(golgg_json).open(encoding='utf-8') as file:
        games = json.load(file)
    by_identity = defaultdict(list)
    seen_ids = set()
    for game in games:
        mid = game['match_id']
        if mid in seen_ids:
            raise ValueError(f'Duplicate GOL.GG match id: {mid}')
        seen_ids.add(mid)
        names = tuple(apply_alias(normalize_team_name(game[key]), aliases) for key in ('name_1', 'name_2'))
        if not all(names) or names[0] == names[1]:
            continue
        day = datetime.strptime(game['date'], '%Y-%m-%d').date()
        by_identity[(day, tuple(sorted(names)))].append((game, names))

    audit = []
    proposals = {}
    for index, row in odds.iterrows():
        entry = {'source_row': int(index), 'source_date': str(row['date']),
                 'source_home_team': str(row['home_team']), 'source_away_team': str(row['away_team']),
                 'oddsportal_url': str(row['url']), 'status': 'unmatched', 'candidate_ids': []}
        audit.append(entry)
        names = tuple(apply_alias(normalize_team_name(row[key]), aliases) for key in ('home_team', 'away_team'))
        if not all(names) or names[0] == names[1]:
            entry['status'] = 'invalid_identity'
            continue
        try:
            day = datetime.strptime(str(row['date'])[:10], '%Y-%m-%d').date()
        except ValueError:
            entry['status'] = 'invalid_date'
            continue
        pair = tuple(sorted(names))
        candidates = [(game, canonical, 0) for game, canonical in by_identity.get((day, pair), ())]
        if not candidates:
            candidates = [(game, canonical, offset) for offset in (-1, 1)
                          for game, canonical in by_identity.get((day + timedelta(days=offset), pair), ())]
        entry['candidate_ids'] = [game['match_id'] for game, _, _ in candidates]
        if len(candidates) != 1:
            if candidates:
                entry['status'] = 'ambiguous_golgg_fixture'
            continue
        game, canonical, offset = candidates[0]
        proposals[index] = (game, names != canonical, offset, day)

    # Count all edges, including ambiguous rows: do not make a candidate unique by
    # first discarding or consuming another competing observation.
    claims = Counter(mid for entry in audit for mid in entry['candidate_ids'])
    results = []
    for index, (game, swapped, offset, day) in proposals.items():
        entry = audit[index]
        if claims[game['match_id']] != 1:
            entry['status'] = 'ambiguous_odds_fixture'
            continue
        row = odds.loc[index]
        first, second = (row['awayResult'], row['homeResult']) if swapped else (row['homeResult'], row['awayResult'])
        if pd.isna(first) or pd.isna(second):
            entry['status'] = 'missing_source_result'
            continue
        if (first > second) != bool(game['t1_win']) or (second > first) != bool(game['t2_win']):
            entry['status'] = 'result_mismatch'
            continue
        if (first, second) != (game['score_1'], game['score_2']):
            entry['status'] = 'score_mismatch'
            continue
        record = {'golgg_match_id': game['match_id'], 'odds_date': day.isoformat(),
                  'golgg_date': game['date'], 'golgg_team1': game['name_1'], 'golgg_team2': game['name_2'],
                  't1_score': game['score_1'], 't2_score': game['score_2'],
                  't1_win': game['t1_win'], 't2_win': game['t2_win'], 'draw': game['draw'],
                  'match_type': 'identity_exact' if offset == 0 else 'identity_date_offset',
                  'tournament': row['tournament'], 'oddsportal_url': row['url'],
                  'source_row': index, 'source_date': row['date'],
                  'source_home_team': row['home_team'], 'source_away_team': row['away_team'],
                  'source_home_result': row['homeResult'], 'source_away_result': row['awayResult'],
                  'source_sides_swapped': swapped, 'date_offset_days': offset,
                  'mapping_version': 'identity-only-v3'}
        for left, right in QUOTE_PAIRS:
            record[left], record[right] = (row[right], row[left]) if swapped else (row[left], row[right])
        results.append(record)
        entry.update(status='matched', golgg_match_id=game['match_id'], source_sides_swapped=swapped,
                     date_offset_days=offset)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8', newline='') as file:
        pd.DataFrame(results, columns=OUTPUT_COLUMNS).to_csv(file, index=False)
    summary = dict(Counter(entry['status'] for entry in audit))
    with audit_path.open('x', encoding='utf-8') as file:
        json.dump({'mapping_version': 'identity-only-v3', 'summary': summary,
                   'timing': 'Date-only retrospective mapping; quote availability uncertified.',
                   'rows': audit}, file, indent=2)
    print(json.dumps({'output': str(output), 'audit': str(audit_path), 'summary': summary}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--oddsportal-csv', required=True)
    parser.add_argument('--golgg-json', required=True)
    parser.add_argument('--output-csv', required=True)
    parser.add_argument('--aliases-json', required=True, help='Explicitly reviewed alias document; never an old learned alias map.')
    args = parser.parse_args()
    map_matches(args.oddsportal_csv, args.golgg_json, args.output_csv, args.aliases_json)
