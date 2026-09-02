"""Regression tests for the event-time financial analysis endpoint."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from betting_app.api.routers import financial
from betting_app.services.thesis_inference_service import (
    THESIS_MODEL_NAME,
    THESIS_MODEL_VERSION,
)


def _prediction(
    match_id: int,
    *,
    start: str,
    result_available_at: str,
    cutoff: str | None = "2026-01-01T10:00:00+00:00",
) -> dict[str, Any]:
    return {
        "canonical_match_id": match_id,
        "team_a_name": f"A{match_id}",
        "team_b_name": f"B{match_id}",
        "league": "Test League",
        "start_time_normalized": start,
        "result_recorded_at": result_available_at,
        "winner_side": "team_a" if match_id == 1 else "team_b",
        "prob_a": 0.70,
        "prob_b": 0.30,
        "predicted_at": "2026-01-01T11:00:00+00:00",
        "data_cutoff_at": cutoff,
        "prediction_id": match_id,
    }


def _snapshot(match_id: int, scraped_at: str) -> dict[str, Any]:
    return {
        "canonical_match_id": match_id,
        "bookmaker_id": 1,
        "bookmaker": "TestBook",
        "raw_team_a": f"A{match_id}",
        "raw_team_b": f"B{match_id}",
        "odds_a": 2.0,
        "odds_b": 2.0,
        "scraped_at": scraped_at,
    }


def _stub_query(
    predictions: list[dict[str, Any]], odds: list[dict[str, Any]]
) -> Callable[..., list[dict[str, Any]]]:
    def query(_db: object, statement: str, _params: dict[str, Any]):
        return predictions if "canonical_predictions p" in statement else odds

    return query


def test_financial_api_reserves_overlapping_stakes(monkeypatch, client: TestClient):
    predictions = [
        _prediction(1, start="2026-01-01T18:00:00+00:00", result_available_at="2026-01-01T22:00:00+00:00"),
        _prediction(2, start="2026-01-01T19:00:00+00:00", result_available_at="2026-01-01T23:00:00+00:00"),
    ]
    odds = [
        _snapshot(1, "2026-01-01T12:00:00+00:00"),
        _snapshot(2, "2026-01-01T13:00:00+00:00"),
    ]
    monkeypatch.setattr(financial, "query_df", _stub_query(predictions, odds))

    response = client.get(
        "/financial/analysis",
        params={
            "model_name": THESIS_MODEL_NAME,
            "model_version": THESIS_MODEL_VERSION,
            "staking_mode": "fixed",
            "fixed_stake": 700,
            "initial_bankroll": 1000,
            "days_back": 730,
            "min_ev": 0,
            "data_scope": "live",
        },
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert [entry["stake"] for entry in result["ledger"]] == [700, 300]
    assert result["max_open_bets"] == 2
    assert result["max_open_stake"] == 1000
    # Match two loses; no settlement before its placement may fund another 700 PLN stake.
    assert result["final_bankroll"] == 1232


def test_financial_live_scope_excludes_missing_cutoff(monkeypatch):
    predictions = [
        _prediction(
            1,
            start="2026-01-01T18:00:00+00:00",
            result_available_at="2026-01-01T22:00:00+00:00",
            cutoff=None,
        )
    ]
    monkeypatch.setattr(financial, "query_df", _stub_query(predictions, []))

    result = financial.financial_analysis(
        model_name=THESIS_MODEL_NAME,
        model_version=THESIS_MODEL_VERSION,
        data_scope="live",
        days_back=730,
        db=object(),
    )

    assert result.total_bets == 0
    assert result.temporal_exclusions["missing_data_cutoff_at"] == 1


def test_financial_api_empty_sqlite_cohort_is_valid(client: TestClient):
    response = client.get("/financial/analysis")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["data_scope"] == "historical"
    assert payload["odds_mode"] == "mid"
    assert payload["total_bets"] == 0
