"""Historical odds must be linked by independent identities, never by outcomes."""
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

PATH = Path(__file__).resolve().parents[2] / 'scripts/03_dane_pipeline/00_map_matches.py'
spec = importlib.util.spec_from_file_location('historical_odds_mapper', PATH)
mapper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mapper)


def match(mid, first, second, score=(2, 0)):
    return {'match_id': mid, 'date': '2025-02-01', 'name_1': first, 'name_2': second,
            'score_1': score[0], 'score_2': score[1], 't1_win': score[0] > score[1],
            't2_win': score[1] > score[0], 'draw': score[0] == score[1]}


def quote(first, second, url='https://example.test/fixture', score=(2, 0)):
    row = {'date': '2025-02-01 18:00:00', 'home_team': first, 'away_team': second,
           'homeResult': score[0], 'awayResult': score[1], 'url': url, 'tournament': 'test',
           'avg_odds_home': 1.5, 'avg_odds_away': 3.0, 'avg_open_home': 1.4, 'avg_open_away': 3.2}
    for book in ('betclic', 'betfan', 'efortuna', 'lv_bet', 'sts', 'superbet', 'fuksiarz'):
        row.update({f'odds1_{book}_close': 1.5, f'odds2_{book}_close': 3.0,
                    f'odds1_{book}_open': 1.4, f'odds2_{book}_open': 3.2})
    return row


def run(tmp_path, games, prices, aliases=None):
    raw = tmp_path / 'raw.csv'; golgg = tmp_path / 'matches.json'
    output = tmp_path / 'mapped.csv'; alias_path = tmp_path / 'aliases.json'
    pd.DataFrame(prices).to_csv(raw, index=False)
    golgg.write_text(json.dumps(games))
    alias_path.write_text(json.dumps({'reviewed': True, 'aliases': aliases or {}}))
    before = json.loads(alias_path.read_text())
    mapper.map_matches(raw, golgg, output, alias_path)
    assert json.loads(alias_path.read_text()) == before
    return pd.read_csv(output)


@pytest.mark.parametrize('first,second', [('Unrelated A', 'Unrelated B'), ('Alpha', 'Unrelated B')])
def test_matching_scores_do_not_establish_fixture_identity(tmp_path, first, second):
    result = run(tmp_path, [match(1, 'Alpha', 'Beta')], [quote(first, second)])
    assert result.empty


def test_academy_and_main_squad_are_not_the_same_identity(tmp_path):
    result = run(tmp_path, [match(1, 'Alpha', 'Beta'), match(2, 'Alpha Academy', 'Beta')],
                 [quote('Alpha Academy', 'Beta')])
    assert result.golgg_match_id.tolist() == [2]


def test_repeated_same_day_pair_is_not_resolved_by_score_or_input_order(tmp_path):
    result = run(tmp_path, [match(1, 'Alpha', 'Beta'), match(2, 'Alpha', 'Beta', (0, 2))],
                 [quote('Alpha', 'Beta'), quote('Alpha', 'Beta', url='https://example.test/other', score=(0, 2))])
    assert result.empty


def test_duplicate_raw_candidates_do_not_consume_a_single_fixture(tmp_path):
    result = run(tmp_path, [match(1, 'Alpha', 'Beta')],
                 [quote('Alpha', 'Beta'), quote('Alpha', 'Beta', url='https://example.test/other')])
    assert result.empty


def test_reversed_identity_swaps_every_quote_and_retains_raw_provenance(tmp_path):
    result = run(tmp_path, [match(1, 'Beta', 'Alpha', (0, 2))], [quote('Alpha', 'Beta')])
    row = result.iloc[0]
    assert row.avg_odds_home == 3.0 and row.avg_odds_away == 1.5
    assert row.avg_open_home == 3.2 and row.avg_open_away == 1.4
    for book in ('betclic', 'betfan', 'efortuna', 'lv_bet', 'sts', 'superbet', 'fuksiarz'):
        assert row[f'odds1_{book}_close'] == 3.0
        assert row[f'odds2_{book}_close'] == 1.5
        assert row[f'odds1_{book}_open'] == 3.2
        assert row[f'odds2_{book}_open'] == 1.4
    assert row.source_home_team == 'Alpha' and row.source_away_team == 'Beta'
    assert bool(row.source_sides_swapped)


def test_legacy_learned_aliases_are_not_silently_treated_as_reviewed(tmp_path):
    path = tmp_path / 'aliases.json'
    path.write_text(json.dumps({'alpha': 'unrelated'}))
    with pytest.raises(ValueError, match='reviewed'):
        mapper.load_aliases(path)


def test_both_adjacent_dates_are_considered_before_resolving_identity(tmp_path):
    games = [match(1, 'Alpha', 'Beta'), match(2, 'Alpha', 'Beta')]
    games[0]['date'] = '2025-01-31'
    games[1]['date'] = '2025-02-02'
    result = run(tmp_path, games, [quote('Alpha', 'Beta')])
    assert result.empty


def test_result_contradiction_rejects_but_never_changes_identity(tmp_path):
    result = run(tmp_path, [match(1, 'Alpha', 'Beta')], [quote('Alpha', 'Beta', score=(0, 2))])
    assert result.empty
    audit = json.loads((tmp_path / 'mapped.audit.json').read_text())
    assert audit['rows'][0]['candidate_ids'] == [1]
    assert audit['rows'][0]['status'] == 'result_mismatch'


def test_matching_winner_does_not_clear_conflicting_series_score(tmp_path):
    result = run(tmp_path, [match(1, 'Alpha', 'Beta', score=(2, 0))],
                 [quote('Alpha', 'Beta', score=(2, 1))])
    assert result.empty
    audit = json.loads((tmp_path / 'mapped.audit.json').read_text())
    assert audit['rows'][0]['candidate_ids'] == [1]
    assert audit['rows'][0]['status'] == 'score_mismatch'


def test_reviewed_alias_can_align_both_independent_identities(tmp_path):
    result = run(tmp_path, [match(1, 'Alpha', 'Beta')], [quote('A', 'B')],
                 aliases={'A': 'Alpha', 'B': 'Beta'})
    assert result.golgg_match_id.tolist() == [1]


def test_existing_mapping_evidence_is_never_overwritten(tmp_path):
    run(tmp_path, [match(1, 'Alpha', 'Beta')], [quote('Alpha', 'Beta')])
    output = tmp_path / 'mapped.csv'
    before = output.read_bytes()
    with pytest.raises(FileExistsError):
        mapper.map_matches(tmp_path / 'raw.csv', tmp_path / 'matches.json', output, tmp_path / 'aliases.json')
    assert output.read_bytes() == before
