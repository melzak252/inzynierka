"""Unit tests for the betting recommendation engine."""

from betting_app.api.routers.matches import _build_match_recommendation
from betting_app.api.schemas import BookmakerOddsRow


def test_recommendation_unmapped_teams():
    rec = _build_match_recommendation(
        team_a_name="Gen.G",
        team_b_name="Hanwha Life",
        has_unmapped_teams=True,
        odds_rows=[],
        hybrid_prob_a=0.55,
        hybrid_prob_b=0.45,
        pure_prob_a=0.55,
        pure_prob_b=0.45,
    )
    assert not rec.has_value
    assert rec.verdict == "unmapped"
    assert "mapowanie" in rec.verdict_label.lower()
    assert len(rec.reasons) > 0


def test_recommendation_no_odds():
    rec = _build_match_recommendation(
        team_a_name="Gen.G",
        team_b_name="Hanwha Life",
        has_unmapped_teams=False,
        odds_rows=[],
        hybrid_prob_a=0.55,
        hybrid_prob_b=0.45,
        pure_prob_a=0.55,
        pure_prob_b=0.45,
    )
    assert not rec.has_value
    assert rec.verdict == "no_odds"
    assert "brak" in rec.verdict_label.lower()


def test_recommendation_value_bet_detected():
    # Hanwha Life @ 2.40 with hybrid prob 0.487 -> EV after 12% tax: 0.487 * (2.40 * 0.88) - 1 = +2.85%
    odds_rows = [
        BookmakerOddsRow(
            bookmaker="betclic",
            canonical_odds_a=1.58,
            canonical_odds_b=2.15,
        ),
        BookmakerOddsRow(
            bookmaker="sts",
            canonical_odds_a=1.53,
            canonical_odds_b=2.40,
            offer_url="https://sts.pl/match/123",
        ),
    ]
    rec = _build_match_recommendation(
        team_a_name="Gen.G",
        team_b_name="Hanwha Life",
        has_unmapped_teams=False,
        odds_rows=odds_rows,
        hybrid_prob_a=0.513,
        hybrid_prob_b=0.487,
        pure_prob_a=0.435,
        pure_prob_b=0.565,
    )
    assert rec.has_value
    assert rec.verdict == "value_bet"
    assert rec.side == "b"
    assert rec.recommended_team == "Hanwha Life"
    assert rec.bookmaker == "sts"
    assert rec.best_odds == 2.40
    assert rec.offer_url == "https://sts.pl/match/123"
    assert rec.ev is not None and rec.ev > 0.02
    assert rec.min_odds_required is not None
    assert rec.min_odds_required < 2.40  # 1 / (0.487 * 0.88) = 2.33
    assert rec.quarter_kelly is not None and rec.quarter_kelly > 0
    assert len(rec.reasons) >= 3
    assert any("2.40" in r for r in rec.reasons)
    assert any("STS" in r.upper() for r in rec.reasons)


def test_recommendation_no_bet_when_no_ev():
    # Both sides have odds below break-even with 12% tax
    odds_rows = [
        BookmakerOddsRow(
            bookmaker="sts",
            canonical_odds_a=1.60,
            canonical_odds_b=2.00,
        ),
    ]
    rec = _build_match_recommendation(
        team_a_name="Team A",
        team_b_name="Team B",
        has_unmapped_teams=False,
        odds_rows=odds_rows,
        hybrid_prob_a=0.50,
        hybrid_prob_b=0.50,
        pure_prob_a=0.50,
        pure_prob_b=0.50,
    )
    assert not rec.has_value
    assert rec.verdict == "no_bet"
    assert "No Bet" in rec.verdict_label
    assert len(rec.reasons) >= 2
    assert rec.threshold_info is not None
