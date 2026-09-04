from __future__ import annotations

from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from betting_app.ml.backtesting import HistoricalPrediction, MatchLabel, OddsQuote, compare_predictions_to_market, run_backtest
from betting_app.ml.backtesting import loaders as backtest_loaders
from betting_app.ml.backtesting.odds_selection import select_quotes_for_match
from betting_app.ml.backtesting.horizons import HorizonSpec, select_horizon_quotes
from betting_app.ml.config import BacktestConfig, StakingConfig
from betting_app.ml.metrics import (
    brier_score,
    expected_calibration_error,
    max_drawdown,
    roc_auc_score,
    roi,
)
from betting_app.scripts.backtest_exp039_db_market import (
    aggregate_market,
    build_mapping_audit,
    resolve_source_outcome,
)
from betting_app.scripts import benchmark_model_roi
from betting_app.scripts.benchmark_model_roi import (
    _validate_temporal_prediction_contract,
    load_csv_predictions,
)
from betting_app.scripts.rebuild_ratings import MatchForRatings


UTC = timezone.utc


def dt(hour: int) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


def test_benchmark_csv_requires_explicit_proxy_for_missing_timestamps(
    tmp_path,
) -> None:
    path = tmp_path / "predictions.csv"
    pd.DataFrame(
        [{"canonical_match_id": 1, "prob_a": 0.60}]
    ).to_csv(path, index=False)

    kwargs = {
        "model_name": "candidate",
        "model_version": "v1",
        "probability_column": "prob_a",
        "probability_b_column": None,
        "predicted_at_column": "predicted_at",
        "data_cutoff_column": "data_cutoff_at",
        "outcome_column": None,
        "eligibility_columns": [],
    }
    with pytest.raises(
        ValueError,
        match="Missing required prediction CSV columns",
    ):
        load_csv_predictions(
            path,
            allow_retrospective_proxy=False,
            **kwargs,
        )

    predictions, _records, source = load_csv_predictions(
        path,
        allow_retrospective_proxy=True,
        **kwargs,
    )
    assert predictions[0].predicted_at is None
    assert predictions[0].data_cutoff_at is None
    assert source["rows_after_eligibility"] == 1


def test_benchmark_csv_filters_and_validates_timestamped_predictions(
    tmp_path,
) -> None:
    path = tmp_path / "predictions.csv"
    pd.DataFrame(
        [
            {
                "canonical_match_id": 1,
                "prob_a": 0.60,
                "predicted_at": "2026-01-01T10:00:00Z",
                "data_cutoff_at": "2026-01-01T09:00:00Z",
                "eligible": True,
            },
            {
                "canonical_match_id": 2,
                "prob_a": 0.55,
                "predicted_at": "2026-01-01T10:00:00Z",
                "data_cutoff_at": "2026-01-01T09:00:00Z",
                "eligible": False,
            },
        ]
    ).to_csv(path, index=False)

    predictions, records, source = load_csv_predictions(
        path,
        model_name="candidate",
        model_version="v1",
        probability_column="prob_a",
        probability_b_column=None,
        predicted_at_column="predicted_at",
        data_cutoff_column="data_cutoff_at",
        outcome_column=None,
        eligibility_columns=["eligible"],
        allow_retrospective_proxy=False,
    )

    assert len(predictions) == 1
    assert predictions[0].canonical_match_id == 1
    assert predictions[0].prob_b == pytest.approx(0.40)
    assert predictions[0].predicted_at == dt(10)
    assert set(records) == {1}
    assert source["eligibility_exclusions"] == {"eligible": 1}
    _validate_temporal_prediction_contract(
        predictions,
        [
            MatchLabel(
                canonical_match_id=1,
                winner_side="a",
                start_time=dt(18),
                result_available_at=dt(20),
            )
        ],
        allow_retrospective_proxy=False,
    )


def test_benchmark_rejects_prediction_at_or_after_match_start() -> None:
    prediction = HistoricalPrediction(
        canonical_match_id=1,
        model_name="candidate",
        model_version="v1",
        prob_a=0.60,
        prob_b=0.40,
        predicted_at=dt(18),
        data_cutoff_at=dt(17),
    )

    with pytest.raises(ValueError, match="invalid order"):
        _validate_temporal_prediction_contract(
            [prediction],
            [
                MatchLabel(
                    canonical_match_id=1,
                    winner_side="a",
                    start_time=dt(18),
                    result_available_at=dt(20),
                )
            ],
            allow_retrospective_proxy=False,
        )


def test_benchmark_database_mode_uses_strict_timestamped_predictions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prediction = HistoricalPrediction(
        canonical_match_id=1,
        model_name="candidate",
        model_version="v1",
        prob_a=0.60,
        prob_b=0.40,
        predicted_at=dt(10),
        data_cutoff_at=dt(9),
        prediction_id=101,
    )
    label = MatchLabel(
        canonical_match_id=1,
        winner_side="a",
        start_time=dt(18),
        result_available_at=dt(20),
        league="Test League",
    )
    quote = OddsQuote(1, 10, "book-a", 2.00, 2.00, dt(11), 201)
    monkeypatch.setattr(
        benchmark_model_roi,
        "get_session",
        lambda: nullcontext(object()),
    )
    monkeypatch.setattr(
        benchmark_model_roi,
        "load_finished_match_labels",
        lambda **_kwargs: [label],
    )
    monkeypatch.setattr(
        benchmark_model_roi,
        "load_predictions",
        lambda **_kwargs: [prediction],
    )
    monkeypatch.setattr(
        benchmark_model_roi,
        "load_odds_quotes",
        lambda **_kwargs: [quote],
    )
    args = benchmark_model_roi.build_parser().parse_args(
        ["--model-name", "candidate", "--model-version", "v1"]
    )

    inputs = benchmark_model_roi.load_benchmark_inputs(args)

    assert inputs.predictions == [prediction]
    assert inputs.labels == [label]
    assert inputs.odds == [quote]
    assert inputs.source["kind"] == "canonical_predictions"
    assert inputs.source["retrospective_proxy"] is False
    assert inputs.cohort_by_id[1]["start_time_normalized"] == dt(18).isoformat()


def test_latest_pre_match_selects_latest_quote_per_bookmaker() -> None:
    label = MatchLabel(canonical_match_id=1, winner_side="a", start_time=dt(18))
    quotes = [
        OddsQuote(1, 10, "book-a", 2.10, 1.70, dt(10), 101),
        OddsQuote(1, 10, "book-a", 2.20, 1.65, dt(12), 102),
        OddsQuote(1, 10, "book-a", 2.25, 1.62, dt(14), 104),
        OddsQuote(1, 11, "book-b", 2.05, 1.75, dt(11), 201),
        OddsQuote(1, 12, "invalid", 1.00, 14.0, dt(11), 301),
        OddsQuote(1, 10, "at-kickoff", 2.50, 1.50, dt(18), 105),
        OddsQuote(1, 10, "too-late", 2.50, 1.50, dt(19), 103),
    ]

    selected = select_quotes_for_match(quotes, label, BacktestConfig())
    opened = select_quotes_for_match(
        quotes, label, BacktestConfig(odds_policy="open_pre_match")
    )
    midpoint = select_quotes_for_match(
        quotes, label, BacktestConfig(odds_policy="mid_pre_match")
    )

    assert {quote.odds_snapshot_id for quote in selected} == {104, 201}
    assert {quote.odds_snapshot_id for quote in opened} == {101, 201}
    assert {quote.odds_snapshot_id for quote in midpoint} == {102, 201}


def test_odds_loader_aligns_raw_bookmaker_side_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        backtest_loaders,
        "query_df",
        lambda *_args, **_kwargs: pd.DataFrame(
            [
                {
                    "odds_snapshot_id": 101,
                    "canonical_match_id": 1,
                    "bookmaker_id": 10,
                    "bookmaker_name": "book-a",
                    "raw_team_a": "Beta",
                    "raw_team_b": "Alpha",
                    "odds_a": 1.50,
                    "odds_b": 3.00,
                    "scraped_at": "2026-01-01T12:00:00+00:00",
                    "offer_url": None,
                    "team_a_name": "Alpha",
                    "team_b_name": "Beta",
                }
            ]
        ),
    )

    quotes = backtest_loaders.load_odds_quotes(
        canonical_match_ids={1},
        session=object(),  # type: ignore[arg-type]
    )

    assert len(quotes) == 1
    assert quotes[0].odds_a == 3.00
    assert quotes[0].odds_b == 1.50


def test_backtest_places_highest_ev_bet_and_settles_with_tax() -> None:
    result = run_backtest(
        predictions=[
            HistoricalPrediction(
                canonical_match_id=1,
                model_name="test",
                model_version="v1",
                prob_a=0.60,
                prob_b=0.40,
                predicted_at=dt(10),
            )
        ],
        labels=[
            MatchLabel(
                canonical_match_id=1,
                winner_side="a",
                start_time=dt(18),
                result_available_at=dt(20),
            )
        ],
        odds_quotes=[OddsQuote(1, 10, "book-a", 2.20, 1.70, dt(12), 102)],
        config=BacktestConfig(
            bankroll_start=1_000.0,
            min_ev=0.0,
            staking=StakingConfig(strategy="fixed", fixed_stake=10.0),
        ),
    )

    assert len(result.bets) == 1
    bet = result.bets[0]
    assert bet.side == "a"
    assert bet.result == "won"
    assert bet.stake == 10.0
    assert bet.profit == pytest.approx(10.0 * (2.20 * 0.88 - 1.0))
    assert bet.expected_profit == pytest.approx(10.0 * bet.ev)
    assert bet.settled_at == dt(20)
    assert result.bankroll_end == pytest.approx(1_000.0 + bet.profit)
    assert result.roi == pytest.approx(bet.profit / bet.stake)
    assert result.bankroll_return == pytest.approx(bet.profit / 1_000.0)


def test_backtest_can_require_odds_after_prediction_time() -> None:
    result = run_backtest(
        predictions=[
            HistoricalPrediction(
                1,
                "test",
                "v1",
                prob_a=0.60,
                prob_b=0.40,
                predicted_at=dt(10),
                data_cutoff_at=dt(9),
            )
        ],
        labels=[
            MatchLabel(
                1,
                "a",
                start_time=dt(18),
                result_available_at=dt(20),
            )
        ],
        odds_quotes=[
            OddsQuote(1, 10, "book-a", 2.50, 1.50, dt(9), 101),
            OddsQuote(1, 10, "book-a", 2.10, 1.70, dt(11), 102),
        ],
        config=BacktestConfig(
            bankroll_start=1_000.0,
            min_ev=0.0,
            require_prediction_before_odds=True,
            staking=StakingConfig(strategy="fixed", fixed_stake=10.0),
        ),
    )

    assert len(result.bets) == 1
    assert result.bets[0].odds_snapshot_id == 102


def test_backtest_reserves_stakes_until_overlapping_matches_settle() -> None:
    result = run_backtest(
        predictions=[
            HistoricalPrediction(1, "test", "v1", prob_a=0.75, prob_b=0.25),
            HistoricalPrediction(2, "test", "v1", prob_a=0.75, prob_b=0.25),
        ],
        labels=[
            MatchLabel(1, "a", start_time=dt(18), result_available_at=dt(22)),
            MatchLabel(2, "b", start_time=dt(19), result_available_at=dt(23)),
        ],
        odds_quotes=[
            OddsQuote(1, 10, "book-a", 2.00, 2.00, dt(10), 101),
            OddsQuote(2, 10, "book-a", 2.00, 2.00, dt(11), 102),
        ],
        config=BacktestConfig(
            bankroll_start=20.0,
            min_ev=0.05,
            tax_rate=0.0,
            staking=StakingConfig(strategy="fixed", fixed_stake=15.0),
        ),
    )
    assert result.total_staked == 20.0
    assert result.expected_profit == 10.0
    assert result.expected_yield == 0.5
    assert result.roi == 0.5
    assert result.bankroll_return == 0.5
    assert result.turnover == 1.0

    assert [bet.stake for bet in result.bets] == [15.0, 5.0]
    assert result.bets[1].available_bankroll_before == 5.0
    assert result.max_open_stake == 20.0
    assert result.max_open_bets == 2
    assert result.bankroll_end == 30.0
    assert result.max_drawdown == 5.0
    assert result.max_drawdown_fraction == pytest.approx(5.0 / 35.0)



def test_fractional_kelly_caps_each_stake_against_available_bankroll() -> None:
    result = run_backtest(
        predictions=[
            HistoricalPrediction(1, "test", "v1", prob_a=0.90, prob_b=0.10),
            HistoricalPrediction(2, "test", "v1", prob_a=0.90, prob_b=0.10),
        ],
        labels=[
            MatchLabel(1, "a", start_time=dt(18), result_available_at=dt(22)),
            MatchLabel(2, "b", start_time=dt(19), result_available_at=dt(23)),
        ],
        odds_quotes=[
            OddsQuote(1, 10, "book-a", 2.00, 2.00, dt(10), 101),
            OddsQuote(2, 10, "book-a", 2.00, 2.00, dt(11), 102),
        ],
        config=BacktestConfig(
            bankroll_start=1_000.0,
            min_ev=0.05,
            tax_rate=0.0,
            staking=StakingConfig(
                strategy="fractional_kelly",
                kelly_fraction=0.25,
                max_stake=None,
                max_bankroll_fraction=0.05,
            ),
        ),
    )

    assert [bet.stake for bet in result.bets] == pytest.approx([50.0, 47.5])
    assert all(
        bet.stake <= bet.available_bankroll_before * 0.05
        for bet in result.bets
    )
    assert result.max_open_stake == pytest.approx(97.5)
    assert result.bankroll_end == pytest.approx(1_002.5)

def test_backtest_rejects_result_recorded_before_match_start() -> None:
    result = run_backtest(
        predictions=[
            HistoricalPrediction(1, "test", "v1", prob_a=0.75, prob_b=0.25)
        ],
        labels=[
            MatchLabel(
                1,
                "a",
                start_time=dt(18),
                result_available_at=dt(17),
            )
        ],
        odds_quotes=[OddsQuote(1, 10, "book-a", 2.00, 2.00, dt(10), 101)],
        config=BacktestConfig(tax_rate=0.0, min_ev=0.05),
    )

    assert result.bets == []
    assert result.matches_temporally_ineligible == 1


def test_metrics_helpers() -> None:
    assert brier_score([1, 0], [0.75, 0.25]) == pytest.approx(0.0625)
    assert roi(12.0, 100.0) == pytest.approx(0.12)
    assert max_drawdown([100.0, 120.0, 90.0, 130.0]) == pytest.approx(30.0)
    assert roc_auc_score([0, 1], [0.25, 0.75]) == 1.0
    assert roc_auc_score([0, 1], [0.50, 0.50]) == 0.5
    assert expected_calibration_error(
        [0, 1],
        [0.25, 0.75],
        bins=2,
    ) == pytest.approx(0.25)


def test_compare_predictions_to_market_returns_probability_metrics() -> None:
    comparison = compare_predictions_to_market(
        predictions=[HistoricalPrediction(1, "test", "v1", prob_a=0.70, prob_b=0.30, predicted_at=dt(10))],
        labels=[MatchLabel(1, "a", start_time=dt(18))],
        odds_quotes=[OddsQuote(1, 10, "book-a", 2.20, 1.70, dt(12), 102)],
        config=BacktestConfig(),
    )

    assert comparison.observations == 1
    assert comparison.model_brier == pytest.approx(0.09)
    assert comparison.model_log_loss < comparison.market_log_loss


def test_historical_source_outcome_uses_series_winner_when_game_rows_are_missing() -> None:
    match = MatchForRatings(
        match_id="101",
        match_date=date(2026, 1, 1),
        team1_id="1",
        team2_id="2",
        team1_name="Alpha",
        team2_name="Beta",
        games=[
            {
                "team1_id": "1",
                "team2_id": "2",
                "team1_name": "Alpha",
                "team2_name": "Beta",
                "team1_win": 1,
                "team2_win": 0,
                "draw": 0,
            },
            {
                "team1_id": "1",
                "team2_id": "2",
                "team1_name": "Alpha",
                "team2_name": "Beta",
                "team1_win": 0,
                "team2_win": 1,
                "draw": 0,
            },
        ],
        players1=["11", "12", "13", "14", "15"],
        players2=["21", "22", "23", "24", "25"],
    )

    outcome = resolve_source_outcome(
        match,
        {
            "winner_name": "Alpha",
            "team1_score": 2,
            "team2_score": 1,
            "draw": 0,
        },
        best_of=3,
    )

    assert outcome["y_team1"] == 1
    assert outcome["source_outcome_complete"] is True
    assert outcome["observed_games"] == 2
    assert outcome["expected_games"] == 3
    assert outcome["imputed_rating_games"] == 1
    assert outcome["rating_scores"].count(1) == 2
    assert outcome["rating_scores"].count(0) == 1


def test_market_aggregation_requires_a_known_strictly_later_start() -> None:
    mapped = pd.DataFrame(
        [
            {
                "canonical_match_id": 1,
                "team_a_name": "Alpha",
                "team_b_name": "Beta",
                "start_time_normalized": "2026-01-01T18:00:00+00:00",
            },
            {
                "canonical_match_id": 2,
                "team_a_name": "Gamma",
                "team_b_name": "Delta",
                "start_time_normalized": None,
            },
        ]
    )
    odds = pd.DataFrame(
        [
            {
                "canonical_match_id": 1,
                "bookmaker_id": 10,
                "raw_team_a": "Beta",
                "raw_team_b": "Alpha",
                "odds_a": 1.5,
                "odds_b": 3.0,
                "scraped_at": "2026-01-01T17:59:00+00:00",
            },
            {
                "canonical_match_id": 1,
                "bookmaker_id": 10,
                "raw_team_a": "Beta",
                "raw_team_b": "Alpha",
                "odds_a": 1.9,
                "odds_b": 2.1,
                "scraped_at": "2026-01-01T18:00:00+00:00",
            },
            {
                "canonical_match_id": 2,
                "bookmaker_id": 10,
                "raw_team_a": "Gamma",
                "raw_team_b": "Delta",
                "odds_a": 2.0,
                "odds_b": 2.0,
                "scraped_at": "2026-01-01T17:00:00+00:00",
            },
        ]
    )

    aggregated = aggregate_market(mapped, odds)

    assert aggregated["canonical_match_id"].tolist() == [1]
    assert aggregated.loc[0, "market_close_latest_at"] == "2026-01-01T17:59:00+00:00"
    assert aggregated.loc[0, "market_close_p_a_raw"] == pytest.approx(1.0 / 3.0)


def test_mapping_audit_aligns_sides_without_using_the_result() -> None:
    predictions = pd.DataFrame(
        [
            {
                "golgg_match_id": "101",
                "date": "2026-01-01",
                "team1_id": "1",
                "team2_id": "2",
                "team1_name": "Alpha",
                "team2_name": "Beta",
                "y_team1": 0,
                "source_outcome_complete": True,
                "historical_feature_proxy_eligible": True,
                "exp039_symmetric_prob_team1": 0.70,
                "exp039_calibrated_prob_team1": 0.72,
                "exp039_parity_v2_prob_team1": 0.71,
            },
            {
                "golgg_match_id": "102",
                "date": "2026-01-01",
                "team1_id": "1",
                "team2_id": "2",
                "team1_name": "Alpha",
                "team2_name": "Beta",
                "y_team1": 1,
                "source_outcome_complete": True,
                "historical_feature_proxy_eligible": True,
                "exp039_symmetric_prob_team1": 0.60,
                "exp039_calibrated_prob_team1": 0.61,
                "exp039_parity_v2_prob_team1": 0.62,
            },
        ]
    )
    market_rows = []
    for canonical_match_id, golgg_match_id, team_a, team_b, winner_side in (
        (1, "101", "Beta", "Alpha", "team_a"),
        (2, "102", "Alpha", "Beta", "team_b"),
    ):
        row = {
            "canonical_match_id": canonical_match_id,
            "golgg_match_id": golgg_match_id,
            "result_source_match_id": golgg_match_id,
            "team_a_name": team_a,
            "team_b_name": team_b,
            "league": "Test",
            "winner_side": winner_side,
            "start_time_normalized": "2026-01-01T18:00:00+00:00",
        }
        for timing in ("open", "mid", "close"):
            row[f"market_{timing}_p_a_novig"] = 0.50
            row[f"market_{timing}_latest_at"] = "2026-01-01T17:00:00+00:00"
        market_rows.append(row)

    audit = build_mapping_audit(predictions, pd.DataFrame(market_rows))

    accepted = audit[audit["canonical_match_id"] == 1].iloc[0]
    rejected = audit[audit["canonical_match_id"] == 2].iloc[0]
    assert bool(accepted["canonical_a_is_golgg_team1"]) is False
    assert accepted["exp039_parity_v2_prob_team_a"] == pytest.approx(0.29)
    assert bool(accepted["mapping_eligible"]) is True
    assert bool(rejected["canonical_a_is_golgg_team1"]) is True
    assert bool(rejected["mapping_eligible"]) is False
    assert "canonical_outcome_conflict" in rejected["exclusion_reasons"]


def test_horizon_selection_uses_only_fresh_post_prediction_quotes() -> None:
    prediction = HistoricalPrediction(
        canonical_match_id=1,
        model_name="candidate",
        model_version="v1",
        prob_a=0.6,
        prob_b=0.4,
        data_cutoff_at=dt(1),
        predicted_at=dt(2),
    )
    label = MatchLabel(canonical_match_id=1, winner_side="a", start_time=dt(18))
    horizon = HorizonSpec("t6h", timedelta(hours=6), timedelta(hours=1))
    quotes = [
        OddsQuote(1, 1, "book-a", 2.0, 2.0, dt(11), 10),
        OddsQuote(1, 1, "book-a", 1.9, 2.1, dt(12), 11),
        OddsQuote(1, 2, "book-b", 2.0, 2.0, dt(11) + timedelta(minutes=30), 12),
        OddsQuote(1, 3, "book-c", 2.0, 2.0, dt(13), 13),
        OddsQuote(1, 4, "book-d", 2.0, 2.0, dt(2), 14),
    ]

    selected = select_horizon_quotes(prediction, label, quotes, horizon)

    assert [quote.odds_snapshot_id for quote in selected] == [11, 12]


def test_horizon_selection_rejects_predictions_after_target_horizon() -> None:
    prediction = HistoricalPrediction(
        canonical_match_id=1,
        model_name="candidate",
        model_version="v1",
        prob_a=0.6,
        prob_b=0.4,
        data_cutoff_at=dt(13),
        predicted_at=dt(13),
    )
    label = MatchLabel(canonical_match_id=1, winner_side="a", start_time=dt(18))
    horizon = HorizonSpec("t6h", timedelta(hours=6), timedelta(hours=1))

    assert select_horizon_quotes(
        prediction,
        label,
        [OddsQuote(1, 1, "book-a", 2.0, 2.0, dt(12), 10)],
        horizon,
    ) == []
