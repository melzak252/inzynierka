import pytest

from betting_app.services.bet_qualification_service import is_bet_eligible


def test_insufficient_ev_rejected() -> None:
    # prob=0.50, odds=2.00, tax=0.12 -> return factor = 2.00 * 0.88 = 1.76
    # EV_net = 0.50 * 1.76 - 1.0 = -0.12 (negative EV)
    eligible, reason, diag = is_bet_eligible(prob_model=0.50, odds=2.00)
    assert not eligible
    assert reason == "insufficient_ev"
    assert diag["ev_net"] < 0.05


def test_positive_ev_eligible_standard() -> None:
    # prob=0.65, odds=2.00, tax=0.12 -> EV_net = 0.65 * 1.76 - 1.0 = +0.144 (> 0.05)
    eligible, reason, diag = is_bet_eligible(prob_model=0.65, odds=2.00)
    assert eligible
    assert reason == "eligible"
    assert diag["ev_net"] > 0.05


def test_issue_001_transition_zone_quarantine() -> None:
    # High underdog: odds 4.00 (implied ~25%), model predicts 0.40 (transition zone [0.30, 0.50))
    # EV_net = 0.40 * 4.00 * 0.88 - 1.0 = 1.408 - 1.0 = +0.408 (appears high EV, but it's a phantom trap)
    eligible, reason, diag = is_bet_eligible(
        prob_model=0.40,
        odds=4.00,
        prob_market_novig=0.25,
    )
    assert not eligible
    assert reason == "quarantine_trap_issue_001"
    assert diag["quarantine"] is True


def test_issue_001_strong_contrarian_permitted() -> None:
    # High underdog: odds 4.00, but model has high conviction (prob >= 0.50)
    eligible, reason, diag = is_bet_eligible(
        prob_model=0.55,
        odds=4.00,
        prob_market_novig=0.25,
    )
    assert eligible
    assert reason == "eligible"
    assert diag["quarantine"] is False


def test_issue_001_modest_edge_permitted() -> None:
    # Underdog: odds 3.60, model predicts 0.29 (below 0.30 transition threshold)
    # EV_net = 0.29 * 3.60 * 0.88 - 1.0 = 0.918 - 1.0 < 0 (insufficient EV)
    # But if odds=4.20, prob=0.29 -> EV = 0.29 * 4.20 * 0.88 - 1.0 = +0.0718 (> 0.05)
    eligible, reason, diag = is_bet_eligible(
        prob_model=0.29,
        odds=4.20,
        prob_market_novig=0.24,
    )
    assert eligible
    assert reason == "eligible"


def test_odds_boundaries() -> None:
    # Just below 3.50 boundary: odds 3.49 is in the golden tier (2.80-3.50), not quarantined
    # prob=0.40, odds=3.49 -> EV = 0.40 * 3.49 * 0.88 - 1.0 = +0.228
    eligible_below, reason_below, _ = is_bet_eligible(prob_model=0.40, odds=3.49)
    assert eligible_below
    assert reason_below == "eligible"

    # Exactly 3.50 boundary: quarantined if in transition zone [0.30, 0.50)
    eligible_at, reason_at, _ = is_bet_eligible(prob_model=0.40, odds=3.50)
    assert not eligible_at
    assert reason_at == "quarantine_trap_issue_001"

    # Just above 5.00 boundary: odds 5.01
    eligible_above, reason_above, _ = is_bet_eligible(prob_model=0.40, odds=5.01)
    assert eligible_above


def test_invalid_arguments() -> None:
    with pytest.raises(ValueError, match="odds must be > 1.0"):
        is_bet_eligible(prob_model=0.50, odds=0.95)

    with pytest.raises(ValueError, match="prob_model must be in"):
        is_bet_eligible(prob_model=1.20, odds=2.00)

    with pytest.raises(ValueError, match="tax_rate must be in"):
        is_bet_eligible(prob_model=0.50, odds=2.00, tax_rate=1.0)
