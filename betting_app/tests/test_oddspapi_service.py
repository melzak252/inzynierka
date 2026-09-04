"""Unit and integration tests for OddsPapi service, budget guard, and market comparison."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from betting_app.core.db import get_session
from betting_app.models.match import CanonicalMatch
from betting_app.models.odds import OddsSnapshot
from betting_app.models.oddspapi import OddspapiFixtureMapping, OddspapiRequestLog
from betting_app.models.prediction import CanonicalPrediction
from betting_app.services.odds_service import get_or_create_bookmaker
from betting_app.services.oddspapi_service import (
    OddsPapiBudgetExhaustedError,
    OddsPapiBudgetGuard,
    OddsPapiClient,
    compare_match_market,
    extract_winner_odds,
    fetch_pinnacle_horizon_odds,
    sync_oddspapi_fixtures,
)


class MockOddsPapiClient(OddsPapiClient):
    """Mock client returning predetermined payloads without external network calls."""

    def __init__(self, responses: dict[str, Any] | None = None, budget_guard: OddsPapiBudgetGuard | None = None) -> None:
        super().__init__(api_key="test-key", budget_guard=budget_guard or OddsPapiBudgetGuard())
        self.responses = responses or {}
        self.requested_paths: list[tuple[str, dict[str, Any] | None]] = []

    def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        session: Session | None = None,
        fixture_id: str | None = None,
    ) -> Any:
        sess = session or get_session()
        allowed, reason, _ = self.budget_guard.check_budget(sess)
        if not allowed:
            raise OddsPapiBudgetExhaustedError(reason)

        self.requested_paths.append((path, params))
        self.budget_guard.record_request(sess, path, fixture_id, 200, 15)

        if path in self.responses:
            return self.responses[path]
        if fixture_id and f"fixture:{fixture_id}" in self.responses:
            return self.responses[f"fixture:{fixture_id}"]
        return self.responses.get("default", {})


def test_budget_guard_daily_and_monthly_caps(client: TestClient) -> None:
    session = get_session()
    try:
        guard = OddsPapiBudgetGuard(monthly_limit=250, daily_limit=8)

        # Initially allowed
        allowed, reason, stats = guard.check_budget(session)
        assert allowed is True
        assert stats["monthly_used"] == 0
        assert stats["daily_used"] == 0
        assert stats["daily_remaining"] == 8

        # Record 7 requests
        for i in range(7):
            guard.record_request(session, "/v4/odds", f"fix_{i}", 200, 20)

        allowed, _, stats = guard.check_budget(session)
        assert allowed is True
        assert stats["daily_used"] == 7
        assert stats["daily_remaining"] == 1

        # 8th request reaches daily cap
        guard.record_request(session, "/v4/odds", "fix_7", 200, 20)
        allowed, reason, stats = guard.check_budget(session)
        assert allowed is False
        assert "daily cap reached" in reason
        assert stats["daily_used"] == 8
        assert stats["daily_remaining"] == 0

        # Now test monthly limit
        small_monthly_guard = OddsPapiBudgetGuard(monthly_limit=10, daily_limit=50)
        # We currently have 8 requests in the DB
        allowed, _, stats = small_monthly_guard.check_budget(session)
        assert allowed is True
        assert stats["monthly_remaining"] == 2

        guard.record_request(session, "/v4/odds", "fix_8", 200, 20)
        guard.record_request(session, "/v4/odds", "fix_9", 200, 20)

        allowed, reason, stats = small_monthly_guard.check_budget(session)
        assert allowed is False
        assert "monthly quota reached" in reason
    finally:
        session.close()


def test_extract_winner_odds_live_and_historical() -> None:
    # 1. Live format (/v4/odds)
    live_payload = {
        "fixtureId": "id123",
        "bookmakerOdds": {
            "pinnacle": {
                "markets": {
                    "181": {
                        "outcomes": {
                            "181": {"players": {"0": {"price": 1.75, "active": True, "createdAt": "2026-06-01T12:00:00Z"}}},
                            "182": {"players": {"0": {"price": 2.15, "active": True, "createdAt": "2026-06-01T12:00:00Z"}}},
                        }
                    }
                }
            }
        },
    }

    res = extract_winner_odds(live_payload, "pinnacle")
    assert res is not None
    price_1, price_2, ts = res
    assert price_1 == 1.75
    assert price_2 == 2.15
    assert "2026-06-01" in ts

    # 2. Historical format (/v4/historical-odds) with line moves
    historical_payload = {
        "fixtureId": "id123",
        "bookmakers": {
            "pinnacle": {
                "markets": {
                    "181": {
                        "outcomes": {
                            "181": {
                                "players": {
                                    "0": [
                                        {"price": 1.90, "active": True, "createdAt": "2026-06-01T10:00:00Z"},
                                        {"price": 1.80, "active": True, "createdAt": "2026-06-01T11:00:00Z"},
                                        {"price": 1.70, "active": True, "createdAt": "2026-06-01T14:00:00Z"},
                                    ]
                                }
                            },
                            "182": {
                                "players": {
                                    "0": [
                                        {"price": 1.95, "active": True, "createdAt": "2026-06-01T10:00:00Z"},
                                        {"price": 2.05, "active": True, "createdAt": "2026-06-01T11:00:00Z"},
                                        {"price": 2.20, "active": True, "createdAt": "2026-06-01T14:00:00Z"},
                                    ]
                                }
                            },
                        }
                    }
                }
            }
        },
    }

    # Cutoff at 12:00 -> should pick 11:00 quotes (1.80 and 2.05)
    cutoff = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
    res_cutoff = extract_winner_odds(historical_payload, "pinnacle", cutoff_time=cutoff)
    assert res_cutoff is not None
    p1, p2, ts = res_cutoff
    assert p1 == 1.80
    assert p2 == 2.05
    assert "11:00:00" in ts

    # No cutoff -> should pick latest (1.70 and 2.20)
    res_latest = extract_winner_odds(historical_payload, "pinnacle")
    assert res_latest is not None
    assert res_latest[0] == 1.70
    assert res_latest[1] == 2.20


def test_sync_oddspapi_fixtures(client: TestClient) -> None:
    session = get_session()
    try:
        # Seed canonical match
        now = datetime.now(UTC)
        start_str = (now + timedelta(days=2)).replace(microsecond=0).isoformat()

        session.execute(
            text("""
            INSERT INTO canonical_matches (
                id, canonical_key, team_a_name, team_b_name,
                normalized_team_a, normalized_team_b, start_time_normalized,
                league, status, match_confidence
            ) VALUES (
                101, 'lck-t1-geng', 'T1', 'Gen.G',
                't1', 'geng', :start_time,
                'LCK', 'upcoming', 1.0
            )
            """),
            {"start_time": start_str},
        )
        session.commit()

        # Mock OddsPapi /fixtures response
        mock_fixtures = [
            {
                "fixtureId": "fix_t1_geng_101",
                "participant1Name": "T1 Esports",
                "participant2Name": "Gen.G Esports",
                "startTime": start_str,
                "tournamentName": "LCK Champions",
                "hasOdds": True,
            },
            {
                "fixtureId": "fix_other_match",
                "participant1Name": "Fnatic",
                "participant2Name": "G2 Esports",
                "startTime": start_str,
                "tournamentName": "LEC",
                "hasOdds": True,
            },
        ]

        mock_client = MockOddsPapiClient(responses={"/fixtures": mock_fixtures})
        result = sync_oddspapi_fixtures(session=session, client=mock_client)

        assert result["status"] == "success"
        assert result["fixtures_synced"] == 2
        assert result["mapped_to_canonical"] == 1

        # Verify mapping in DB
        mapping = session.scalar(
            text("SELECT fixture_id, canonical_match_id, provider_team_1_is_a FROM oddspapi_fixture_mappings WHERE fixture_id='fix_t1_geng_101'")
        )
        assert mapping is not None

        mapping_row = session.execute(
            text("SELECT canonical_match_id, provider_team_1_is_a FROM oddspapi_fixture_mappings WHERE fixture_id='fix_t1_geng_101'")
        ).fetchone()
        assert mapping_row[0] == 101
        assert mapping_row[1] == 1  # T1 was team A
    finally:
        session.close()


def test_fetch_pinnacle_horizon_odds(client: TestClient) -> None:
    session = get_session()
    try:
        now = datetime.now(UTC)
        # Match starts in exactly 6 hours
        match_start = now + timedelta(hours=6)
        match_start_str = match_start.replace(microsecond=0).isoformat()

        session.execute(
            text("""
            INSERT INTO canonical_matches (
                id, canonical_key, team_a_name, team_b_name,
                normalized_team_a, normalized_team_b, start_time_normalized,
                league, status, match_confidence
            ) VALUES (
                202, 'lec-fnc-g2', 'Fnatic', 'G2 Esports',
                'fnatic', 'g2 esports', :start_time,
                'LEC', 'upcoming', 1.0
            )
            """),
            {"start_time": match_start_str},
        )

        mapping = OddspapiFixtureMapping(
            fixture_id="fix_fnc_g2_202",
            canonical_match_id=202,
            sport_id=18,
            league="LEC",
            provider_team_1="G2 Esports",
            provider_team_2="Fnatic",
            provider_team_1_is_a=0,  # Team 1 is G2 (Team B)
            start_time=match_start,
            has_odds=1,
        )
        session.add(mapping)
        session.commit()

        # Odds payload from OddsPapi: outcome 181 is provider team 1 (G2), outcome 182 is provider team 2 (Fnatic)
        odds_payload = {
            "fixtureId": "fix_fnc_g2_202",
            "bookmakerOdds": {
                "pinnacle": {
                    "markets": {
                        "181": {
                            "outcomes": {
                                "181": {"players": {"0": {"price": 1.50, "active": True, "createdAt": now.isoformat()}}},
                                "182": {"players": {"0": {"price": 2.70, "active": True, "createdAt": now.isoformat()}}},
                            }
                        }
                    }
                }
            }
        }

        mock_client = MockOddsPapiClient(responses={"fixture:fix_fnc_g2_202": odds_payload})
        result = fetch_pinnacle_horizon_odds(
            session=session,
            target_horizon_hours=6.0,
            tolerance_hours=1.0,
            max_requests=2,
            client=mock_client,
        )

        assert result["status"] == "success"
        assert result["candidates"] == 1
        assert result["fetched"] == 1
        assert result["saved"] == 1

        # Verify saved snapshot in odds_snapshots
        pinnacle_id = get_or_create_bookmaker("pinnacle")
        snapshot = session.execute(
            text("""
            SELECT odds_a, odds_b, bookmaker_id FROM odds_snapshots
            WHERE canonical_match_id=202 AND bookmaker_id=:pinnacle_id
            """),
            {"pinnacle_id": pinnacle_id},
        ).fetchone()

        assert snapshot is not None
        # Since provider_team_1_is_a=0, team A (Fnatic) gets outcome 182 (2.70), team B (G2) gets outcome 181 (1.50)
        assert abs(float(snapshot[0]) - 2.70) < 1e-4
        assert abs(float(snapshot[1]) - 1.50) < 1e-4

        # Running again should skip because snapshot is already fresh
        res2 = fetch_pinnacle_horizon_odds(session=session, target_horizon_hours=6.0, client=mock_client)
        assert res2["candidates"] == 0
        assert res2["fetched"] == 0
    finally:
        session.close()


def test_compare_match_market_and_api_endpoint(client: TestClient) -> None:
    session = get_session()
    try:
        now = datetime.now(UTC)
        match_start = now + timedelta(hours=6)
        match_start_str = match_start.replace(microsecond=0).isoformat()

        session.execute(
            text("""
            INSERT INTO canonical_matches (
                id, canonical_key, team_a_name, team_b_name,
                normalized_team_a, normalized_team_b, start_time_normalized,
                league, status, match_confidence
            ) VALUES (
                303, 'lck-t1-dk', 'T1', 'Dplus KIA',
                't1', 'dplus kia', :start_time,
                'LCK', 'upcoming', 1.0
            )
            """),
            {"start_time": match_start_str},
        )

        pinnacle_id = get_or_create_bookmaker("pinnacle")
        sts_id = get_or_create_bookmaker("sts")

        quote_time = (now - timedelta(minutes=10)).replace(microsecond=0).isoformat()

        # Pinnacle: 1.80 vs 2.10
        session.execute(
            text("""
            INSERT INTO odds_snapshots (
                bookmaker_id, canonical_match_id, market_type, raw_team_a, raw_team_b,
                odds_a, odds_b, is_live, scraped_at, source_url
            ) VALUES (
                :bm_pin, 303, 'match_winner', 'T1', 'Dplus KIA',
                1.80, 2.10, 0, :scraped_at, 'oddspapi://test'
            )
            """),
            {"bm_pin": pinnacle_id, "scraped_at": quote_time},
        )

        # STS: 1.75 vs 2.15
        session.execute(
            text("""
            INSERT INTO odds_snapshots (
                bookmaker_id, canonical_match_id, market_type, raw_team_a, raw_team_b,
                odds_a, odds_b, is_live, scraped_at, source_url
            ) VALUES (
                :bm_sts, 303, 'match_winner', 'T1', 'Dplus KIA',
                1.75, 2.15, 0, :scraped_at, 'sts://test'
            )
            """),
            {"bm_sts": sts_id, "scraped_at": quote_time},
        )

        # Model prediction: prob_a = 0.58
        session.execute(
            text("""
            INSERT INTO canonical_predictions (
                id, canonical_match_id, model_name, model_version, features_version,
                prob_a, prob_b, predicted_at
            ) VALUES (
                999, 303, 'Sym-Cal LR-ElasticNet-W20-Binomial', 'exp-039', 'w20_v1',
                0.58, 0.42, :pred_at
            )
            """),
            {"pred_at": quote_time},
        )
        session.commit()

        # Test service function
        comparison = compare_match_market(canonical_match_id=303, session=session, horizon_hours=6.0)
        assert comparison is not None
        assert comparison["team_a"] == "T1"
        assert comparison["pinnacle_novig_prob_a"] is not None
        # 1/1.8 / (1/1.8 + 1/2.1) = 0.5555 / (0.5555 + 0.4761) = ~0.5385
        assert abs(comparison["pinnacle_novig_prob_a"] - 0.5385) < 0.01

        books = {b["bookmaker"]: b for b in comparison["bookmakers"]}
        assert "sts" in books
        assert "pinnacle" in books
        assert books["pinnacle"]["delta_to_pinnacle"] == 0.0
        # STS EV team A with 12% tax: 0.58 * (1.75 * 0.88) - 1.0 = 0.58 * 1.54 - 1.0 = -0.1068
        assert books["sts"]["ev_team_a_tax12"] is not None
        assert "ev_conformal_low_a" in books["sts"]
        assert "is_conformal_value_a" in books["sts"]
        assert isinstance(books["sts"]["is_conformal_value_a"], bool)
        # Test API endpoint
        response = client.get("/matches/303/market-comparison?horizon_hours=6.0")
        assert response.status_code == 200
        data = response.json()
        assert data["canonical_match_id"] == 303
        assert data["team_a"] == "T1"
        assert len(data["bookmakers"]) == 2
    finally:
        session.close()
