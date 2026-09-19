import pytest

from betting_app.services.bet_qualification_service import (
    DEFAULT_BASE_MIN_EV,
    DEFAULT_HURDLE_ODDS_CUTOFF,
    DEFAULT_HURDLE_PENALTY_SCALE,
    DEFAULT_LONGSHOT_ODDS_THRESHOLD,
    DEFAULT_MAX_BO1_MARKET_GAP,
    DEFAULT_MAX_EV_LONGSHOT,
    DEFAULT_MAX_NEGATIVE_CLV_DRIFT,
    dynamic_min_ev_hurdle,
    is_bet_eligible,
)


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


def test_high_underdog_positive_ev_eligible() -> None:
    # High underdog: odds 4.00, model predicts 0.40 (e.g. risk-gated P_low from Siamese MLP)
    # EV_net = 0.40 * 4.00 * 0.88 - 1.0 = 1.408 - 1.0 = +0.408 (mathematical EV >= +5%)
    # When max_ev_longshot is disabled (None), high underdog EV qualifies
    eligible, reason, diag = is_bet_eligible(
        prob_model=0.40,
        odds=4.00,
        prob_market_novig=0.25,
        max_ev_longshot=None,
    )
    assert eligible
    assert reason == "eligible"
    assert diag["quarantine"] is False
def test_issue_001_strong_contrarian_permitted() -> None:
    # High underdog: odds 4.00, but model has high conviction (prob >= 0.50)
    # EV_net = 0.55 * 4.00 * 0.88 - 1.0 = 0.936 > 0.25 cap; with max_ev_longshot=None it qualifies
    eligible, reason, diag = is_bet_eligible(
        prob_model=0.55,
        odds=4.00,
        prob_market_novig=0.25,
        max_ev_longshot=None,
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


def test_odds_boundaries_consistent_ev() -> None:
    # Across odds 3.49, 3.50, and 5.01: eligibility is strictly driven by net EV
    # prob=0.40, odds=3.49 -> EV = 0.40 * 3.49 * 0.88 - 1.0 = +0.228 (> 0.05, < 0.25)
    eligible_below, reason_below, _ = is_bet_eligible(prob_model=0.40, odds=3.49)
    assert eligible_below
    assert reason_below == "eligible"

    # At 3.50: EV = 0.40 * 3.50 * 0.88 - 1.0 = +0.232 (> 0.05, < 0.25) -> eligible
    eligible_at, reason_at, _ = is_bet_eligible(prob_model=0.40, odds=3.50)
    assert eligible_at
    assert reason_at == "eligible"

    # Above 5.00: odds 5.01, EV = 0.40 * 5.01 * 0.88 - 1 = +0.7635 > 0.25
    # With max_ev_longshot=None, net EV cleanly qualifies
    eligible_above, reason_above, _ = is_bet_eligible(prob_model=0.40, odds=5.01, max_ev_longshot=None)
    assert eligible_above
    assert reason_above == "eligible"
def test_invalid_arguments() -> None:
    with pytest.raises(ValueError, match="odds must be > 1.0"):
        is_bet_eligible(prob_model=0.50, odds=0.95)

    with pytest.raises(ValueError, match="prob_model must be in"):
        is_bet_eligible(prob_model=1.20, odds=2.00)

    with pytest.raises(ValueError, match="tax_rate must be in"):
        is_bet_eligible(prob_model=0.50, odds=2.00, tax_rate=1.0)


def test_dynamic_min_ev_hurdle_calculation() -> None:
    # At or above cutoff (2.20), hurdle equals base_min_ev (0.05)
    assert dynamic_min_ev_hurdle(2.20) == pytest.approx(0.05)
    assert dynamic_min_ev_hurdle(3.50) == pytest.approx(0.05)
    assert dynamic_min_ev_hurdle(5.00) == pytest.approx(0.05)

    # At 1.10: penalty is (1.10 / 2.20) * 0.08 = 0.5 * 0.08 = 0.04 -> hurdle = 0.09
    assert dynamic_min_ev_hurdle(1.10) == pytest.approx(0.09)

    # At 1.65: penalty is (0.55 / 2.20) * 0.08 = 0.25 * 0.08 = 0.02 -> hurdle = 0.07
    assert dynamic_min_ev_hurdle(1.65) == pytest.approx(0.07)

    # Custom parameters
    assert dynamic_min_ev_hurdle(1.50, base_min_ev=0.03, odds_cutoff=2.00, penalty_scale=0.10) == pytest.approx(
        0.03 + (0.50 / 2.00) * 0.10
    )


def test_issue_002_winners_curse_marginal_coinflip_rejected() -> None:
    # Coin-flip / tight match: odds=1.80, tax=0.12 -> return factor = 1.80 * 0.88 = 1.584
    # Model predicts 0.670 -> EV_net = 0.670 * 1.584 - 1.0 = +0.06128 (+6.13%)
    # Under flat EV >= 0.05, this marginal coin-flip would qualify.
    # Under dynamic hurdle: cutoff=2.20, penalty=(0.40 / 2.20) * 0.08 = 0.01455 -> effective hurdle = +6.45%
    # Since 6.13% < 6.45%, it must be rejected!
    eligible_dyn, reason_dyn, diag_dyn = is_bet_eligible(prob_model=0.67, odds=1.80, dynamic_hurdle=True)
    assert not eligible_dyn
    assert reason_dyn == "insufficient_ev"
    assert diag_dyn["ev_net"] == pytest.approx(0.0613, abs=1e-4)
    assert diag_dyn["effective_min_ev"] > diag_dyn["ev_net"]
    assert diag_dyn["dynamic_hurdle"] is True

    # When dynamic_hurdle is explicitly disabled, it qualifies under flat EV
    eligible_flat, reason_flat, diag_flat = is_bet_eligible(prob_model=0.67, odds=1.80, dynamic_hurdle=False)
    assert eligible_flat
    assert reason_flat == "eligible"
    assert diag_flat["effective_min_ev"] == 0.05


def test_issue_002_strong_favorite_still_qualifies() -> None:
    # If model has genuine massive edge on favorite: odds=1.60, tax=0.12 -> return factor = 1.408
    # Model predicts 0.80 -> EV_net = 0.80 * 1.408 - 1.0 = +0.1264 (+12.64%)
    # Hurdle at 1.60: 0.05 + (0.60 / 2.20) * 0.08 = 0.0718 (+7.18%)
    # Net EV of +12.64% cleanly exceeds the +7.18% hurdle!
    eligible, reason, diag = is_bet_eligible(prob_model=0.80, odds=1.60)
    assert eligible
    assert reason == "eligible"
    assert diag["ev_net"] > diag["effective_min_ev"]


def test_diagnostics_contain_market_gap() -> None:
    eligible, reason, diag = is_bet_eligible(
        prob_model=0.60,
        odds=2.50,
        prob_market_novig=0.42,
    )
    assert eligible
    assert diag["market_gap"] == pytest.approx(0.18)


def test_issue_003_severe_rating_disagreement_quarantined() -> None:
    # Strong favorite that passes EV check (e.g. odds=1.70, prob=0.75 -> EV=+12.2%)
    # Case 1: Severe disagreement (e.g. 0.22 > 0.15 cutoff) must be quarantined
    eligible, reason, diag = is_bet_eligible(
        prob_model=0.75,
        odds=1.70,
        rating_disagreement=0.22,
    )
    assert not eligible
    assert reason == "severe_rating_disagreement"
    assert diag["quarantine"] is True
    assert diag["quarantine_reason"] == "severe_rating_disagreement"
    assert diag["rating_disagreement"] == 0.22

    # Case 2: Moderate disagreement (0.10 <= 0.15) qualifies cleanly
    eligible_ok, reason_ok, diag_ok = is_bet_eligible(
        prob_model=0.75,
        odds=1.70,
        rating_disagreement=0.10,
    )
    assert eligible_ok
    assert reason_ok == "eligible"
    assert diag_ok["quarantine"] is False

    # Case 3: Underdog (odds=3.00 > 2.20 hurdle cutoff) with disagreement is not blocked
    # because underdogs do not suffer from the favorite/coin-flip overconfidence trap
    eligible_dog, reason_dog, diag_dog = is_bet_eligible(
        prob_model=0.45,
        odds=3.00,
        rating_disagreement=0.25,
    )
    assert eligible_dog
    assert reason_dog == "eligible"
    assert diag_dog["quarantine"] is False


def test_issue_003_tier1_market_divergence_quarantined() -> None:
    # Case 1: Tier-1 Domestic with sharp divergence (model=0.70, market=0.58 -> gap=0.12 > 0.08)
    eligible_t1, reason_t1, diag_t1 = is_bet_eligible(
        prob_model=0.70,
        odds=1.90,
        prob_market_novig=0.58,
        competition_tier="Tier-1 Domestic",
    )
    assert not eligible_t1
    assert reason_t1 == "tier1_sharp_market_divergence"
    assert diag_t1["quarantine"] is True
    assert diag_t1["quarantine_reason"] == "tier1_sharp_market_divergence"

    # Case 2: Tier-1 Domestic with acceptable divergence (model=0.65, market=0.60 -> gap=0.05 <= 0.08)
    eligible_t1_ok, reason_t1_ok, diag_t1_ok = is_bet_eligible(
        prob_model=0.65,
        odds=1.90,
        prob_market_novig=0.60,
        competition_tier="Tier-1 Domestic",
    )
    assert eligible_t1_ok
    assert reason_t1_ok == "eligible"
    assert diag_t1_ok["quarantine"] is False

    # Case 3: Tier-2 ERL with large divergence (model=0.70, market=0.55 -> gap=0.15)
    # Must remain eligible because ERL markets have high bookmaker inefficiency exploited by the model
    eligible_erl, reason_erl, diag_erl = is_bet_eligible(
        prob_model=0.70,
        odds=1.90,
        prob_market_novig=0.55,
        competition_tier="Tier-2 ERL",
    )
    assert eligible_erl
    assert reason_erl == "eligible"
    assert diag_erl["quarantine"] is False

def test_coinflip_market_divergence_trap_quarantined() -> None:
    """Odds in [1.80, 2.50] with divergence >= 0.08 must be quarantined when enabled."""
    # Case 1: Coin-flip line (odds=2.10) with sharp model divergence (|0.60 - 0.48| = 0.12 >= 0.08)
    eligible, reason, diag = is_bet_eligible(
        prob_model=0.60,
        odds=2.10,
        prob_market_novig=0.48,
        max_coinflip_market_gap=0.08,
        tax_rate=0.0,
        min_ev_net=0.03,
    )
    assert not eligible
    assert reason == "coinflip_market_divergence_trap"
    assert diag["quarantine"] is True
    assert diag["quarantine_reason"] == "coinflip_market_divergence_trap"

    # Case 2: Coin-flip line with small acceptable divergence (|0.52 - 0.48| = 0.04 < 0.08)
    eligible_ok, reason_ok, diag_ok = is_bet_eligible(
        prob_model=0.52,
        odds=2.10,
        prob_market_novig=0.48,
        max_coinflip_market_gap=0.08,
        tax_rate=0.0,
        min_ev_net=0.03,
    )
    assert eligible_ok
    assert reason_ok == "eligible"
    assert diag_ok["quarantine"] is False

    # Case 3: Outside coin-flip band (odds=1.60 favorite), divergence allowed
    eligible_fav, reason_fav, diag_fav = is_bet_eligible(
        prob_model=0.75,
        odds=1.60,
        prob_market_novig=0.64,
        max_coinflip_market_gap=0.08,
        tax_rate=0.0,
        min_ev_net=0.03,
    )
    assert eligible_fav
    assert reason_fav == "eligible"

def test_conservative_ev_does_not_hide_mean_market_divergence() -> None:
    eligible, reason, diag = is_bet_eligible(
        prob_model=0.80,
        prob_conservative=0.65,
        uncertainty_required=True,
        odds=2.10,
        prob_market_novig=0.60,
        competition_tier="Tier-1 Domestic",
    )
    assert not eligible
    assert reason == "tier1_sharp_market_divergence"
    assert diag["ev_net"] == pytest.approx(0.2012)
    assert diag["market_gap"] == pytest.approx(0.20)


def test_uncertainty_can_only_remove_qualification() -> None:
    outcomes = [
        is_bet_eligible(
            prob_model=0.65, odds=2.10, prob_conservative=bound,
            uncertainty_required=True,
        )[0]
        for bound in (0.65, 0.60, 0.50, 0.0)
    ]
    assert outcomes == [True, True, False, False]


@pytest.mark.parametrize("bound", [None, float("nan"), float("inf"), -0.1, 0.9, "bad"])
def test_required_uncertainty_fails_closed(bound) -> None:
    eligible, _, _ = is_bet_eligible(
        prob_model=0.7, odds=2.0, prob_conservative=bound,
        uncertainty_required=True,
    )
    assert not eligible


@pytest.mark.parametrize(
    "parameter",
    ["odds", "tax_rate", "min_ev_net", "hurdle_odds_cutoff",
     "hurdle_penalty_scale", "rating_disagreement",
     "max_rating_disagreement", "max_tier1_market_gap", "max_ev_net",
     "max_ev_longshot", "longshot_odds_threshold", "max_bo1_market_gap",
     "max_negative_clv_drift"],
)
@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_qualification_inputs_rejected(parameter, invalid) -> None:
    arguments = {"prob_model": 0.7, "odds": 2.0, parameter: invalid}
    with pytest.raises(ValueError):
        is_bet_eligible(**arguments)

def test_extreme_ev_quarantine() -> None:
    # Normal bet with EV = 0.65 * (2.0 * 0.88) - 1 = +14.4% passes max_ev_net=0.25
    eligible, reason, diag = is_bet_eligible(prob_model=0.65, odds=2.0, max_ev_net=0.25)
    assert eligible
    assert reason == "eligible"
    assert diag["quarantine"] is False

    # Extreme bet with EV = 0.85 * (2.0 * 0.88) - 1 = +49.6% > 25% is quarantined
    eligible_ext, reason_ext, diag_ext = is_bet_eligible(prob_model=0.85, odds=2.0, max_ev_net=0.25)
    assert not eligible_ext
    assert reason_ext == "extreme_ev_overconfidence"
    assert diag_ext["quarantine"] is True
    assert diag_ext["quarantine_reason"] == "extreme_ev_overconfidence"

    # If max_ev_net is None, extreme EV is not blocked
    eligible_none, reason_none, _ = is_bet_eligible(prob_model=0.85, odds=2.0, max_ev_net=None)
    assert eligible_none
    assert reason_none == "eligible"


def test_rule_a_ev_ceiling_on_longshots() -> None:
    # Underdog: odds=4.00 (> threshold 3.00), prob=0.40 -> EV = 0.40 * (4.00 * 0.88) - 1.0 = +40.8%
    # default max_ev_longshot is 0.25 (25%). EV (+40.8%) > 25% -> quarantined
    eligible, reason, diag = is_bet_eligible(
        prob_model=0.40,
        odds=4.00,
        prob_market_novig=0.25,
    )
    assert not eligible
    assert reason == "extreme_ev_longshot_cap"
    assert diag["quarantine"] is True
    assert diag["quarantine_reason"] == "extreme_ev_longshot_cap"
    assert diag["max_ev_longshot"] == DEFAULT_MAX_EV_LONGSHOT
    assert diag["longshot_odds_threshold"] == DEFAULT_LONGSHOT_ODDS_THRESHOLD

    # Modest edge on underdog: odds=3.50 (> 3.00), prob=0.35 -> return factor = 3.50 * 0.88 = 3.08
    # EV = 0.35 * 3.08 - 1.0 = +0.078 (7.8% <= 25%) -> eligible!
    eligible_modest, reason_modest, diag_modest = is_bet_eligible(
        prob_model=0.35,
        odds=3.50,
        prob_market_novig=0.28,
    )
    assert eligible_modest
    assert reason_modest == "eligible"
    assert diag_modest["quarantine"] is False

    # Non-longshot favorite: odds=2.50 (<= 3.00), prob=0.60 -> EV = 0.60 * 2.20 - 1.0 = +0.32 (> 25%)
    # Rule A does NOT trigger because odds <= longshot_odds_threshold
    eligible_fav, reason_fav, diag_fav = is_bet_eligible(
        prob_model=0.60,
        odds=2.50,
    )
    assert eligible_fav
    assert reason_fav == "eligible"
    assert diag_fav["quarantine"] is False

    # Disabled max_ev_longshot (None): EV > 25% is permitted
    eligible_none, reason_none, diag_none = is_bet_eligible(
        prob_model=0.40,
        odds=4.00,
        max_ev_longshot=None,
    )
    assert eligible_none
    assert reason_none == "eligible"
    assert diag_none["quarantine"] is False


def test_rule_b_bo1_discrepancy_quarantine() -> None:
    # In Bo1: prob_model=0.65, market=0.50 -> abs gap = 0.15 >= default max_bo1_market_gap (0.12)
    # Return factor at odds 2.00 = 1.76; EV = 0.65 * 1.76 - 1.0 = +14.4% (healthy EV)
    eligible_bo1, reason_bo1, diag_bo1 = is_bet_eligible(
        prob_model=0.65,
        odds=2.00,
        prob_market_novig=0.50,
        best_of=1,
    )
    assert not eligible_bo1
    assert reason_bo1 == "bo1_extreme_market_divergence"
    assert diag_bo1["quarantine"] is True
    assert diag_bo1["quarantine_reason"] == "bo1_extreme_market_divergence"
    assert diag_bo1["best_of"] == 1
    assert diag_bo1["max_bo1_market_gap"] == DEFAULT_MAX_BO1_MARKET_GAP

    # In Bo1: market gap within limit (model=0.58, market=0.50 -> gap = 0.08 < 0.12)
    # EV at odds 2.00: 0.58 * 1.76 - 1.0 = +0.0208 (< 0.05 min EV).
    # Let's use odds=2.10: return factor = 2.10 * 0.88 = 1.848.
    # Dynamic hurdle cutoff=2.20, penalty = (0.10/2.20)*0.08 = 0.0036 -> hurdle = ~0.0536
    # prob=0.60, market=0.50 -> gap 0.10 < 0.12. EV = 0.60 * 1.848 - 1.0 = +0.1088 (> 0.0536)
    eligible_bo1_ok, reason_bo1_ok, diag_bo1_ok = is_bet_eligible(
        prob_model=0.60,
        odds=2.10,
        prob_market_novig=0.50,
        best_of=1,
    )
    assert eligible_bo1_ok
    assert reason_bo1_ok == "eligible"
    assert diag_bo1_ok["quarantine"] is False

    # In Bo3 or Bo5 (best_of != 1), Rule B does NOT trigger even with gap >= 0.12
    eligible_bo3, reason_bo3, diag_bo3 = is_bet_eligible(
        prob_model=0.65,
        odds=2.00,
        prob_market_novig=0.50,
        best_of=3,
    )
    assert eligible_bo3
    assert reason_bo3 == "eligible"
    assert diag_bo3["quarantine"] is False

    # When best_of=None, Rule B does NOT trigger
    eligible_none, reason_none, diag_none = is_bet_eligible(
        prob_model=0.65,
        odds=2.00,
        prob_market_novig=0.50,
        best_of=None,
    )
    assert eligible_none
    assert reason_none == "eligible"


def test_rule_c_negative_clv_drift_quarantine() -> None:
    # prob_market_novig = 0.55 (open), prob_market_close_novig = 0.52 (close)
    # clv_drift = 0.52 - 0.55 = -0.03 <= default max_negative_clv_drift (-0.015) -> quarantined
    # EV at odds 2.00, prob_model=0.65: +14.4%
    eligible_drift, reason_drift, diag_drift = is_bet_eligible(
        prob_model=0.65,
        odds=2.00,
        prob_market_novig=0.55,
        prob_market_close_novig=0.52,
    )
    assert not eligible_drift
    assert reason_drift == "negative_market_drift_clv"
    assert diag_drift["quarantine"] is True
    assert diag_drift["quarantine_reason"] == "negative_market_drift_clv"
    assert diag_drift["clv_drift"] == pytest.approx(-0.03)
    assert diag_drift["max_negative_clv_drift"] == DEFAULT_MAX_NEGATIVE_CLV_DRIFT

    # Acceptable drift: open=0.55, close=0.545 -> drift = -0.005 > -0.015 -> eligible
    eligible_ok, reason_ok, diag_ok = is_bet_eligible(
        prob_model=0.65,
        odds=2.00,
        prob_market_novig=0.55,
        prob_market_close_novig=0.545,
    )
    assert eligible_ok
    assert reason_ok == "eligible"
    assert diag_ok["quarantine"] is False
    assert diag_ok["clv_drift"] == pytest.approx(-0.005)

    # Positive drift (market moved in favor of the side): open=0.55, close=0.58 -> drift = +0.03 > -0.015 -> eligible
    eligible_pos, reason_pos, diag_pos = is_bet_eligible(
        prob_model=0.65,
        odds=2.00,
        prob_market_novig=0.55,
        prob_market_close_novig=0.58,
    )
    assert eligible_pos
    assert reason_pos == "eligible"
    assert diag_pos["quarantine"] is False
    assert diag_pos["clv_drift"] == pytest.approx(0.03)


def test_new_parameter_validations() -> None:
    # Invalid best_of values (must be positive integer, not bool, not <= 0)
    with pytest.raises(ValueError, match="best_of must be a positive integer"):
        is_bet_eligible(prob_model=0.60, odds=2.00, best_of=0)
    with pytest.raises(ValueError, match="best_of must be a positive integer"):
        is_bet_eligible(prob_model=0.60, odds=2.00, best_of=-1)
    with pytest.raises(ValueError, match="best_of must be a positive integer"):
        is_bet_eligible(prob_model=0.60, odds=2.00, best_of=True)  # bool issubclass of int

    # Invalid prob_market_close_novig (must be in (0, 1))
    with pytest.raises(ValueError, match="prob_market_close_novig must be in"):
        is_bet_eligible(prob_model=0.60, odds=2.00, prob_market_close_novig=0.0)
    with pytest.raises(ValueError, match="prob_market_close_novig must be in"):
        is_bet_eligible(prob_model=0.60, odds=2.00, prob_market_close_novig=1.0)

    # Invalid longshot_odds_threshold (must be > 1.0 and finite)
    with pytest.raises(ValueError, match="longshot_odds_threshold must be finite and > 1.0"):
        is_bet_eligible(prob_model=0.60, odds=2.00, longshot_odds_threshold=1.0)
    with pytest.raises(ValueError, match="longshot_odds_threshold must be finite and > 1.0"):
        is_bet_eligible(prob_model=0.60, odds=2.00, longshot_odds_threshold=0.8)

    # Negative non-negative thresholds
    with pytest.raises(ValueError, match="max_ev_longshot must be finite and nonnegative"):
        is_bet_eligible(prob_model=0.60, odds=2.00, max_ev_longshot=-0.1)
    with pytest.raises(ValueError, match="max_bo1_market_gap must be finite and nonnegative"):
        is_bet_eligible(prob_model=0.60, odds=2.00, max_bo1_market_gap=-0.05)
