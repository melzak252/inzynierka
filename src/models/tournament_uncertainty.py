"""Sports-only paired-team residual-strength Laplace approximation.

Likelihood: y_ab ~ Bernoulli(sigmoid(logit(p_sports_ab) + theta_a - theta_b)).
Prior: independent theta_t ~ Normal(0, prior_sd**2). The joint inverse-Hessian
covariance retains dependence learned through opponents. This is an approximate
posterior under a static-team model, NOT arbitrary match jitter, a player model,
or a calibrated statement about roster/patch drift. Source availability must be
audited separately; chronological outcome exclusion is not PIT certification.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from numbers import Integral, Real

import numpy as np
import pandas as pd
from scipy.linalg import cho_factor, cho_solve
from scipy.optimize import minimize
from scipy.special import expit, logit


def _positive(value, name, *, zero=False):
    if (not isinstance(value, Real) or isinstance(value, (bool, np.bool_))
            or not np.isfinite(value) or (value < 0 if zero else value <= 0)):
        raise ValueError(f"{name} must be finite and {'nonnegative' if zero else 'positive'}")


def _teams(values):
    result = []
    for value in values:
        if pd.isna(value) or isinstance(value, (bool, np.bool_)):
            raise ValueError("Team identifiers must be present")
        if isinstance(value, Real) and float(value).is_integer():
            value = int(value)
        identifier = str(value)
        if not identifier.strip():
            raise ValueError("Team identifiers must be nonempty")
        result.append(identifier)
    return result


@dataclass(frozen=True)
class TeamStrengthPosterior:
    """Joint team-only Gaussian Laplace approximation, in SERIES-logit units."""

    teams: tuple[str, ...]
    mean: np.ndarray
    covariance: np.ndarray
    prior_sd: float
    provenance: dict

    def _moments(self, teams):
        names = _teams(teams)
        if len(set(names)) != len(names):
            raise ValueError("Requested teams must be unique")
        index = {team: i for i, team in enumerate(self.teams)}
        mean = np.zeros(len(names))
        covariance = np.eye(len(names)) * self.prior_sd**2
        known = [(i, index[team]) for i, team in enumerate(names) if team in index]
        if known:
            target, source = map(np.asarray, zip(*known))
            mean[target] = self.mean[source]
            covariance[np.ix_(target, target)] = self.covariance[np.ix_(source, source)]
        return names, mean, covariance

    def sample(self, teams, simulations, seed, *, uncertainty_scale=1.0):
        """Draw each team once per tournament. Scale=0 is posterior-mean-only.

        Unseen teams receive the declared prior, not fabricated learned variance.
        The caller passes returned vectors unchanged to simulate_frozen_bracket.
        """
        if (not isinstance(simulations, Integral) or isinstance(simulations, (bool, np.bool_))
                or simulations <= 0):
            raise ValueError("simulations must be a positive integer")
        if not isinstance(seed, Integral) or isinstance(seed, (bool, np.bool_)) or seed < 0:
            raise ValueError("seed must be a nonnegative integer")
        _positive(uncertainty_scale, "uncertainty_scale", zero=True)
        names, mean, covariance = self._moments(teams)
        if uncertainty_scale == 0:
            return {name: np.full(simulations, mean[i]) for i, name in enumerate(names)}
        generator = np.random.default_rng(seed)
        factor = np.linalg.cholesky(covariance)
        draws = mean + uncertainty_scale * (generator.standard_normal((simulations, len(names))) @ factor.T)
        return {name: draws[:, i] for i, name in enumerate(names)}

    def predict(self, first, second, probabilities, *, integrate=True):
        """Marginal complete-series probabilities using 32-node Gaussian quadrature."""
        first, second = _teams(first), _teams(second)
        p = np.asarray(probabilities, dtype=float)
        if (p.ndim != 1 or len(first) != len(second) or len(first) != len(p)
                or not np.isfinite(p).all() or np.any((p < 0) | (p > 1))
                or any(a == b for a, b in zip(first, second))):
            raise ValueError("Predictions require aligned distinct pairs and finite probabilities in [0, 1]")
        names = sorted(set(first) | set(second))
        _, mean, covariance = self._moments(names)
        index = {team: i for i, team in enumerate(names)}
        a = np.array([index[t] for t in first], dtype=int)
        b = np.array([index[t] for t in second], dtype=int)
        location = logit(p) + mean[a] - mean[b]
        if not integrate:
            return expit(location)
        variance = np.maximum(0, covariance[a, a] + covariance[b, b] - 2 * covariance[a, b])
        nodes, weights = np.polynomial.hermite.hermgauss(32)
        marginal = expit(location[:, None] + np.sqrt(2 * variance)[:, None] * nodes) @ (weights / np.sqrt(np.pi))
        # Quadrature weights may sum one ulp away from one; preserve certainties.
        return np.where(p == 0, 0.0, np.where(p == 1, 1.0, marginal))


def fit_team_strength_posterior(frame, probability_column, *, cutoff, prior_sd):
    """Fit only rows strictly earlier than cutoff; never tune prior_sd here.

    The probability column MUST be an externally audited sports-only OOF stream.
    Match IDs are unique; same-day/future rows are excluded before fitting. The
    optimizer uses two indexed incidence entries per match, not a dense design.
    """
    _positive(prior_sd, "prior_sd")
    required = ["golgg_match_id", "date", "team1_id", "team2_id", "y_true", probability_column]
    missing = set(required) - set(frame.columns)
    if missing:
        raise ValueError(f"Missing evidence columns: {sorted(missing)}")
    dates = pd.to_datetime(frame.date, utc=True, errors="raise")
    boundary = pd.to_datetime(cutoff, utc=True, errors="raise")
    if pd.isna(boundary) or dates.isna().any():
        raise ValueError("Evidence and cutoff dates must be present")
    evidence = frame.loc[dates < boundary, required].copy()
    if evidence.empty:
        raise ValueError("No evidence strictly earlier than cutoff")
    if evidence.golgg_match_id.isna().any() or evidence.golgg_match_id.duplicated().any():
        raise ValueError("Evidence requires unique nonmissing match IDs")
    evidence["date"] = dates.loc[evidence.index].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    evidence["team1_id"], evidence["team2_id"] = _teams(evidence.team1_id), _teams(evidence.team2_id)
    evidence = evidence.sort_values(["date", "golgg_match_id"]).reset_index(drop=True)
    p = evidence[probability_column].to_numpy(dtype=float)
    y = evidence.y_true.to_numpy(dtype=float)
    if (not np.isfinite(p).all() or np.any((p <= 0) | (p >= 1))
            or not np.isin(y, [0, 1]).all() or (evidence.team1_id == evidence.team2_id).any()):
        raise ValueError("Fit requires interior finite OOF probabilities, binary outcomes and distinct teams")
    teams = tuple(sorted(set(evidence.team1_id) | set(evidence.team2_id)))
    index = {team: i for i, team in enumerate(teams)}
    a = evidence.team1_id.map(index).to_numpy(dtype=int)
    b = evidence.team2_id.map(index).to_numpy(dtype=int)
    offset = logit(p)
    precision = 1 / prior_sd**2

    def objective(theta):
        z = offset + theta[a] - theta[b]
        residual = expit(z) - y
        loss = np.sum(np.logaddexp(0, z) - y * z) + 0.5 * precision * np.dot(theta, theta)
        gradient = (np.bincount(a, weights=residual, minlength=len(teams))
                    - np.bincount(b, weights=residual, minlength=len(teams)) + precision * theta)
        return loss, gradient

    fit = minimize(objective, np.zeros(len(teams)), method="L-BFGS-B", jac=True,
                   options={"maxiter": 1000, "ftol": 1e-12, "gtol": 1e-7})
    if not fit.success:
        raise RuntimeError(f"Residual posterior optimization failed: {fit.message}")
    fitted = expit(offset + fit.x[a] - fit.x[b])
    weights = fitted * (1 - fitted)
    hessian = np.eye(len(teams)) * precision
    np.add.at(hessian, (a, a), weights)
    np.add.at(hessian, (b, b), weights)
    np.add.at(hessian, (a, b), -weights)
    np.add.at(hessian, (b, a), -weights)
    covariance = cho_solve(cho_factor(hessian, lower=True), np.eye(len(teams)))
    covariance = (covariance + covariance.T) * 0.5
    fit.x.setflags(write=False)
    covariance.setflags(write=False)
    provenance = {
        "method": "paired-team logistic-offset Gaussian-prior joint Laplace approximation",
        "probability_unit": "series_win", "probability_column": probability_column,
        "cutoff_exclusive": boundary.isoformat(), "fit_rows": len(evidence),
        "fit_min_date": evidence.date.min(), "fit_max_date": evidence.date.max(),
        "fit_match_ids": evidence.golgg_match_id.tolist(),
        "fit_evidence_sha256": hashlib.sha256(evidence.to_csv(index=False).encode()).hexdigest(),
        "teams": list(teams), "prior_sd": float(prior_sd),
        "optimizer_iterations": int(fit.nit), "optimizer_gradient_max": float(np.max(np.abs(fit.jac))),
        "covariance": "full inverse penalized observed Hessian; opponent-induced dependence retained",
        "unknown_teams": "independent zero-mean prior; no learned evidence",
        "limitations": ["Static team identity; shared-player covariance and roster changes unmodeled",
                        "Laplace approximation, not empirically certified posterior coverage",
                        "OOF source timing audited externally; eligibility_live=0 absent source proof"],
    }
    return TeamStrengthPosterior(teams, fit.x, covariance, float(prior_sd), provenance)
