"""Unit and integration tests for Tax-Amortized Parlay Recommendations (IDEA-019)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from betting_app.api.main import app
from betting_app.api.schemas import ParlayLeg
from betting_app.models.base import Base
from betting_app.services.parlay_service import (
    calculate_parlay_metrics,
    find_parlay_recommendations,
    POLISH_TAX_RATE,
)


def test_calculate_parlay_metrics():
    """Verify exact compounding, 12% tax amortization bonus, and Kelly sizing."""
    leg1 = ParlayLeg(
        canonical_match_id=101,
        match_name="T1 vs Gen.G",
        league="LCK",
        side="a",
        team_name="T1",
        opponent_name="Gen.G",
        odds=1.70,
        model_prob=0.70,
        single_ev=0.70 * 1.70 * 0.88 - 1.0,  # +4.72%
    )
    leg2 = ParlayLeg(
        canonical_match_id=102,
        match_name="G2 vs Fnatic",
        league="LEC",
        side="a",
        team_name="G2",
        opponent_name="Fnatic",
        odds=1.80,
        model_prob=0.65,
        single_ev=0.65 * 1.80 * 0.88 - 1.0,  # +2.96%
    )

    metrics = calculate_parlay_metrics(leg1, leg2, tax_rate=0.12, bankroll=100.0)

    # Combined odds: 1.70 * 1.80 = 3.06
    assert metrics["combined_odds"] == pytest.approx(3.06, abs=1e-3)
    # Effective odds: 3.06 * 0.88 = 2.6928
    assert metrics["effective_odds"] == pytest.approx(2.693, abs=1e-2)
    # Joint prob: 0.70 * 0.65 = 0.455
    assert metrics["joint_prob"] == pytest.approx(0.455, abs=1e-4)

    # Net EV: 0.455 * 2.6928 - 1 = +22.52%
    expected_ev = 0.455 * 3.06 * 0.88 - 1.0
    assert metrics["ev"] == pytest.approx(expected_ev, abs=1e-3)
    assert metrics["ev"] > 0.20  # Over 20% net EV after tax!

    # Tax amortization gain: parlay EV vs avg single EV
    avg_single = (leg1.single_ev + leg2.single_ev) / 2.0
    expected_gain = expected_ev - avg_single
    assert metrics["tax_amortization_gain"] == pytest.approx(expected_gain, abs=1e-3)
    assert metrics["tax_amortization_gain"] > 0.15  # Massive gain over paying tax twice

    # Kelly sizing:
    assert metrics["quarter_kelly"] > 0.0
    assert 5.0 <= metrics["suggested_stake"] <= 50.0
    assert "Wysokie Bezpieczeństwo" in metrics["confidence_badge"] or "Zbalansowany Dubel" in metrics["confidence_badge"]


def test_parlay_service_with_mock_db():
    """Verify candidate filtering, same-bookmaker requirement, and team independence."""
    from betting_app.models.bookmaker import Bookmaker
    from betting_app.models.match import CanonicalMatch
    from betting_app.models.odds import OddsSnapshot
    from betting_app.models.prediction import CanonicalPrediction

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)

    with TestingSession() as session:
        # Create Bookmakers
        b1 = Bookmaker(id=1, name="superbet")
        b2 = Bookmaker(id=2, name="sts")
        session.add_all([b1, b2])

        # Create Matches
        m1 = CanonicalMatch(
            id=1, canonical_key="key_1", team_a_name="T1", team_b_name="Gen.G",
            normalized_team_a="t1", normalized_team_b="gen_g", league="LCK",
            status="upcoming", start_time_normalized="2026-09-10T10:00:00Z"
        )
        m2 = CanonicalMatch(
            id=2, canonical_key="key_2", team_a_name="G2", team_b_name="Fnatic",
            normalized_team_a="g2", normalized_team_b="fnatic", league="LEC",
            status="upcoming", start_time_normalized="2026-09-10T16:00:00Z"
        )
        m3 = CanonicalMatch(
            id=3, canonical_key="key_3", team_a_name="T1", team_b_name="Dplus",
            normalized_team_a="t1", normalized_team_b="dplus", league="LCK",
            status="upcoming", start_time_normalized="2026-09-11T10:00:00Z"
        )
        session.add_all([m1, m2, m3])

        # Create Predictions
        p1 = CanonicalPrediction(
            id=1, canonical_match_id=1, model_name="Hybrid-Thesis-Market", model_version="1.0",
            prob_a=0.75, prob_b=0.25, predicted_at="2026-09-05T12:00:00Z"
        )
        p2 = CanonicalPrediction(
            id=2, canonical_match_id=2, model_name="Hybrid-Thesis-Market", model_version="1.0",
            prob_a=0.70, prob_b=0.30, predicted_at="2026-09-05T12:00:00Z"
        )
        p3 = CanonicalPrediction(
            id=3, canonical_match_id=3, model_name="Hybrid-Thesis-Market", model_version="1.0",
            prob_a=0.80, prob_b=0.20, predicted_at="2026-09-05T12:00:00Z"
        )
        session.add_all([p1, p2, p3])

        # Create Odds on Superbet (m1 and m2)
        o1 = OddsSnapshot(
            id=1, canonical_match_id=1, bookmaker_id=1,
            odds_a=1.65, odds_b=2.20, scraped_at="2026-09-05T13:00:00Z"
        )
        o2 = OddsSnapshot(
            id=2, canonical_match_id=2, bookmaker_id=1,
            odds_a=1.75, odds_b=2.10, scraped_at="2026-09-05T13:00:00Z"
        )
        # Create Odds on STS only for m3
        o3 = OddsSnapshot(
            id=3, canonical_match_id=3, bookmaker_id=2,
            odds_a=1.50, odds_b=2.60, scraped_at="2026-09-05T13:00:00Z"
        )
        session.add_all([o1, o2, o3])
        session.commit()

        # Run recommendations
        response = find_parlay_recommendations(session, bankroll=100.0)

        assert response.count >= 1
        assert response.top_parlay is not None
        top = response.top_parlay
        assert top.bookmaker == "superbet"
        assert len(top.legs) == 2
        # Verify legs are m1 and m2
        match_ids = {leg.canonical_match_id for leg in top.legs}
        assert match_ids == {1, 2}
        assert top.combined_odds == pytest.approx(1.65 * 1.75, abs=1e-2)
        assert top.ev > 0.0


def test_api_parlays_endpoint(client: TestClient):
    """Test GET /matches/recommendations/parlays HTTP contract."""
    response = client.get("/matches/recommendations/parlays")
    assert response.status_code == 200
    data = response.json()
    assert "count" in data
    assert "parlays" in data
    assert "tax_rate" in data
    assert data["tax_rate"] == 0.12
    assert "explanation" in data
