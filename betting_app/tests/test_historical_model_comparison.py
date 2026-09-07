"""Regression coverage for the temporal EXP-039/regional comparison endpoint."""

from __future__ import annotations

from betting_app.api.routers import timing
from betting_app.services.rating_contract import OPERATIONAL_BACKFILL_MODEL_VERSION


def test_historical_model_comparison_uses_only_temporally_eligible_common_cohort(
    monkeypatch,
) -> None:
    queries: list[str] = []
    old_rows = [
        {"canonical_match_id": 1, "prob_a": 0.70, "winner_side": "team_a"},
        {"canonical_match_id": 2, "prob_a": 0.40, "winner_side": "team_b"},
    ]
    new_rows = [
        {"canonical_match_id": 1, "prob_a": 0.80, "winner_side": "team_a"},
        {"canonical_match_id": 2, "prob_a": 0.30, "winner_side": "team_b"},
        {"canonical_match_id": 3, "prob_a": 0.55, "winner_side": "team_a"},
    ]

    def fake_query_df(_db, sql: str, params: dict):
        if "odds_snapshots" in sql:
            return []
        queries.append(sql)
        if params.get("model_version") == "exp-039":
            return old_rows
        if params.get("model_version") in {
            OPERATIONAL_BACKFILL_MODEL_VERSION,
            "exp081-siamese-series-v1",
            "exp081-siamese-series-v1-a0.50-t0.80",
            "a0.35-t0.80",
        }:
            return new_rows
        return []

    monkeypatch.setattr(timing, "query_df", fake_query_df)

    result = timing.historical_model_comparison(db=object(), target_model="exp081")

    assert result["target_model_key"] == "exp081"
    assert result["common_cohort"]["n_matches"] == 2
    assert result["common_cohort"]["target_model_key"] == "exp081"
    assert result["common_cohort"]["target_minus_exp039_logloss"] < 0
    assert result["common_cohort"]["operational_minus_exp039_logloss"] < 0
    assert len(result["models"]) == 5
    # exp081 is models[0]
    assert result["models"][0]["key"] == "exp081"
    assert result["models"][0]["temporal_eligible_matches"] == 3
    # exp039 is models[3]
    assert result["models"][3]["key"] == "exp039"
    assert result["models"][3]["temporal_eligible_matches"] == 2
    assert all("cp.data_cutoff_at::timestamptz" in query for query in queries)
    assert all("cm.start_time_normalized::timestamptz" in query for query in queries)
    assert "calibration_bins" in result["models"][0]
    assert "ece" in result["models"][0]
    assert "calibration_status" in result["models"][0]
    assert "segments" in result["models"][0]
    assert "formats" in result["models"][0]
    assert "naive_50_50" in result["common_cohort"]
    assert "executive_insights" in result
    assert len(result["executive_insights"]) >= 2

    result_op = timing.historical_model_comparison(db=object(), target_model="operational_regional")
    assert result_op["target_model_key"] == "operational_regional"
    assert result_op["common_cohort"]["operational_minus_exp039_logloss"] < 0


def test_model_profitability_audit_supports_exp081(monkeypatch) -> None:
    def fake_query_df(_db, sql: str, params: dict):
        if "FROM canonical_matches" in sql:
            return [
                {
                    "id": 1,
                    "team_a_name": "T1",
                    "team_b_name": "Gen.G",
                    "start_time_normalized": "2026-06-01T10:00:00+00:00",
                    "winner_side": "team_a",
                    "best_of": 3,
                    "league": "LCK",
                }
            ]
        if "FROM canonical_predictions" in sql:
            assert params.get("mver") == "exp081-siamese-series-v1"
            return [
                {
                    "canonical_match_id": 1,
                    "prob_a": 0.65,
                    "prob_b": 0.35,
                    "diagnostics_json": '{"sigma_z": 0.04}',
                }
            ]
        if "odds_snapshots" in sql:
            return [
                {
                    "canonical_match_id": 1,
                    "odds_a": 2.20,
                    "odds_b": 1.65,
                    "scraped_at": "2026-06-01T08:00:00+00:00",
                    "bookmaker": "sts",
                }
            ]
        return []
    monkeypatch.setattr(timing, "query_df", fake_query_df)
    result = timing.model_profitability_audit(model_key="exp081", db=object())
    assert result["model_key"] == "exp081"
    assert "EXP-081" in result["model_title"]
    assert result["overall"]["total_bets"] >= 0
    assert "avg_clv_pct" in result["overall"]
