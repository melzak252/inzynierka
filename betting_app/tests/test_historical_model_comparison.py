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
        queries.append(sql)
        if params["model_version"] == "exp-039":
            return old_rows
        assert params["model_version"] == OPERATIONAL_BACKFILL_MODEL_VERSION
        return new_rows

    monkeypatch.setattr(timing, "query_df", fake_query_df)

    result = timing.historical_model_comparison(db=object())

    assert result["common_cohort"]["n_matches"] == 2
    assert result["models"][0]["temporal_eligible_matches"] == 2
    assert result["models"][1]["temporal_eligible_matches"] == 3
    assert result["common_cohort"]["operational_minus_exp039_logloss"] < 0
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
