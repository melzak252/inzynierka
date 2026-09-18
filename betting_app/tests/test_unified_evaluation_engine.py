"""Test suite for the canonical UnifiedBettingEngine with calibrated EV."""

import math
import pytest
from src.analysis.unified_evaluation_engine import (
    CalibrationBin,
    EvaluatedBet,
    SimulationSummary,
    UnifiedBettingEngine,
    calculate_quarter_kelly_stake,
    compute_p_low,
)


def test_compute_p_low_invariants() -> None:
    """p_low must always be strictly between 0 and p, monotonically increasing."""
    p_vals = [0.10, 0.25, 0.50, 0.75, 0.90]
    for p in p_vals:
        p_low = compute_p_low(p, kappa=0.75, sigma_z=0.15)
        assert 0.0 < p_low < p
        p_low_high_sigma = compute_p_low(p, kappa=0.75, sigma_z=0.30)
        assert p_low_high_sigma < p_low


def test_quarter_kelly_stake_calculation() -> None:
    """1/4 Kelly stake must respect cap, tax, and nonnegativity."""
    bankroll = 1000.0
    stk_neg = calculate_quarter_kelly_stake(
        bankroll=bankroll, prob_for_ev=0.40, odds=2.00, tax_rate=0.12
    )
    assert stk_neg == 0.0

    stk_pos = calculate_quarter_kelly_stake(
        bankroll=bankroll, prob_for_ev=0.65, odds=2.00, tax_rate=0.12, cap_fraction=0.025
    )
    assert 0.0 < stk_pos <= 25.0


def test_calibrated_ev_invariants() -> None:
    """Calibrated EV must dampen odds multiplier variance and apply entropy haircut."""
    engine = UnifiedBettingEngine(tax_rate=0.0, min_ev_net=0.03)

    # 1. Favorite (p=0.75): low entropy H=0.811 -> minimal haircut
    _, bet_fav = engine.qualify_quote(
        match_id="m1", side="team_a", odds=1.50, prob_model=0.75, prob_conservative=0.74, won=True
    )
    # raw EV = 0.74 * 1.50 - 1 = +11.0%
    h_fav = -(0.75 * math.log2(0.75) + 0.25 * math.log2(0.25))
    expected_fav = (bet_fav.ev_net * 0.73 / 1.075) * (1.0 - 0.15 * h_fav)
    assert bet_fav.ev_calibrated == pytest.approx(expected_fav, abs=1e-3)

    # 2. Coin-flip Underdog with same raw EV (+11.0%): p_cons=0.444 on odds=2.50
    _, bet_dog = engine.qualify_quote(
        match_id="m2", side="team_a", odds=2.50, prob_model=0.50, prob_conservative=0.444, won=False
    )
    h_dog = 1.00
    expected_dog = (bet_dog.ev_net * 0.73 / (1.0 + 0.15 * 1.5)) * (1.0 - 0.15 * h_dog)
    assert bet_dog.ev_calibrated < bet_fav.ev_calibrated
    assert bet_dog.ev_calibrated == pytest.approx(expected_dog, abs=1e-3)
def test_unified_engine_simulation_calibration() -> None:
    """Simulation must compute exact Expected EV per bet vs Realized return per bet."""
    engine = UnifiedBettingEngine(tax_rate=0.12)

    bets = [
        EvaluatedBet(
            match_id="m1",
            side="team_a",
            bookmaker="STS",
            odds=2.50,
            odds_close=2.30,
            prob_model=0.52,
            prob_conservative=0.50,
            ev_net=0.10,
            ev_calibrated=0.08,
            won=True,
            stake=100.0,
            pnl=120.0,
            clv_pct=8.7,
        ),
        EvaluatedBet(
            match_id="m2",
            side="team_b",
            bookmaker="STS",
            odds=2.50,
            odds_close=2.40,
            prob_model=0.52,
            prob_conservative=0.50,
            ev_net=0.10,
            ev_calibrated=0.08,
            won=False,
            stake=100.0,
            pnl=-100.0,
            clv_pct=4.17,
        ),
    ]

    summary = engine.run_simulation(bets, strategy="flat", initial_bankroll=1000.0, flat_stake=100.0)
    assert summary.bets_count == 2
    assert summary.wins_count == 1
    assert summary.win_rate_pct == 50.0
    assert summary.total_staked == 200.0
    assert summary.total_pnl == 20.0
    assert summary.final_bankroll == 1020.0
    assert summary.roi_pct == 10.0

def test_shin_devigging_favorite_longshot_bias() -> None:
    """Shin (1992) devigging must strip favorite-longshot bias and preserve probability mass."""
    from betting_app.core.ev import fair_market_probabilities
    from src.analysis.shin_devig import shin_implied_probabilities

    # Symmetric match: 1.90 vs 1.90
    pa, pb = fair_market_probabilities(1.90, 1.90)
    assert pa == pytest.approx(0.50, abs=1e-4)
    assert pb == pytest.approx(0.50, abs=1e-4)
    assert (pa + pb) == pytest.approx(1.0, abs=1e-6)

    # Skewed match: 1.30 favorite vs 3.50 underdog (vig = 1/1.30 + 1/3.50 - 1 = 5.5%)
    pa_shin, pb_shin = fair_market_probabilities(1.30, 3.50)
    assert (pa_shin + pb_shin) == pytest.approx(1.0, abs=1e-6)

    # Naive proportional: (1/1.30) / (1/1.30 + 1/3.50) = 72.9%
    # Shin strips the bookmaker's heavy underdog margin: favorite prob is significantly higher!
    naive_pa = (1.0 / 1.30) / (1.0 / 1.30 + 1.0 / 3.50)
    assert pa_shin > naive_pa
    assert pa_shin > 0.80
    assert pb_shin < 0.20

    # Invalid odds must raise ValueError
    with pytest.raises(ValueError):
        fair_market_probabilities(0.95, 2.10)


def test_adaptive_alpha_horizon() -> None:
    """Adaptive alpha must assign higher sports model weight early (>24h) and higher market weight late (<2h)."""
    from datetime import UTC, datetime, timedelta
    from betting_app.core.models.registry import get_active_model
    from betting_app.services.upcoming_inference_service import evaluate_bayesian_market_hybrid

    model_spec = get_active_model()
    now = datetime.now(UTC)

    # Early line: 48 hours before match -> alpha ~ 0.40 (sports model weight ~ 0.60)
    early_start = (now + timedelta(hours=48)).isoformat()
    features_early = {
        "canonical": {"id": 1, "best_of": 1, "start_time": early_start, "team_a_name": "T1", "team_b_name": "GEN"},
        "market_novig_prob_a": 0.50,
        "ratings": {"probabilities": {"consensus": 0.80}},
        "player_ratings": {"probabilities": {"consensus": 0.80}},
    }
    res_early = evaluate_bayesian_market_hybrid(features_early, model_spec)
    alpha_early = res_early.diagnostics["alpha"]
    assert alpha_early < 0.45, f"Expected early alpha < 0.45, got {alpha_early}"

    # Late line: 1 hour before match -> alpha ~ 0.53 (higher market weight)
    late_start = (now + timedelta(hours=1)).isoformat()
    features_late = {
        "canonical": {"id": 2, "best_of": 1, "start_time": late_start, "team_a_name": "T1", "team_b_name": "GEN"},
        "market_novig_prob_a": 0.50,
        "ratings": {"probabilities": {"consensus": 0.80}},
        "player_ratings": {"probabilities": {"consensus": 0.80}},
    }
    res_late = evaluate_bayesian_market_hybrid(features_late, model_spec)
    alpha_late = res_late.diagnostics["alpha"]
    assert alpha_late > 0.50, f"Expected late alpha > 0.50, got {alpha_late}"
    assert alpha_late > alpha_early
