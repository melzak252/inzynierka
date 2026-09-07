#!/usr/bin/env python3
"""Train, tune, and export Symmetrized Siamese Series Models (EXP-081 successor pipeline).

This script implements:
1. Pure NumPy training with vectorised Adam optimizer (100% portable, no PyTorch needed).
2. Guaranteed machine anti-symmetry: z_sym(x) = 0.5 * (f(x) - f(-x)).
3. Focal Loss with configurable focusing parameter gamma.
4. Bootstrap bagging ensemble (K members) with epistemic uncertainty estimation.
5. Post-hoc Platt scaling / temperature calibration on validation split.
6. Export to production JSON format consumed by src/models/siamese_series.py.
7. Optional hyperparameter tuning grid (--tune).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import expit, logit
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.models.symmetric_series import (
    _PROBABILITY_FIELDS,
    _RAW_DIFFERENCES,
    _W20_FIELDS,
    build_feature_mapping,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train and tune Symmetrized Siamese Series neural ensemble."
    )
    parser.add_argument(
        "--ratings-data",
        type=Path,
        default=PROJECT_ROOT / "data/golgg_y_predicts.csv",
        help="Path to golgg_y_predicts.csv with rating features",
    )
    parser.add_argument(
        "--rolling-data",
        type=Path,
        default=PROJECT_ROOT / "data/golgg_rolling_stats.csv",
        help="Path to golgg_rolling_stats.csv with W20 features",
    )
    parser.add_argument(
        "--output-model",
        type=Path,
        default=PROJECT_ROOT / "betting_app/models/exp081_siamese_series_v1.json",
        help="Output path for exported model JSON artifact",
    )
    parser.add_argument(
        "--output-report",
        type=Path,
        default=PROJECT_ROOT / "reports/exp081_siamese_focal_uncertainty_gating/summary.json",
        help="Output path for training summary JSON",
    )
    parser.add_argument(
        "--split-date",
        type=str,
        default="2025-01-01",
        help="Train/test split date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--val-date",
        type=str,
        default="2024-01-01",
        help="Train/validation split date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=35,
        help="Number of training epochs per ensemble member",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=64,
        help="Mini-batch size",
    )
    parser.add_argument(
        "--lr",
        type=float,
        default=0.003,
        help="Learning rate for Adam optimizer",
    )
    parser.add_argument(
        "--focal-gamma",
        type=float,
        default=1.0,
        help="Focal Loss focusing parameter gamma (0.0 = standard BCE)",
    )
    parser.add_argument(
        "--n-members",
        type=int,
        default=5,
        help="Number of bootstrap ensemble members (K)",
    )
    parser.add_argument(
        "--d-h1",
        type=int,
        default=32,
        help="Hidden layer 1 dimension",
    )
    parser.add_argument(
        "--d-h2",
        type=int,
        default=16,
        help="Hidden layer 2 dimension",
    )
    parser.add_argument(
        "--risk-kappa",
        type=float,
        default=0.75,
        help="Risk adjustment factor kappa for P_low = sigma(z - kappa * sigma_z)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed",
    )
    parser.add_argument(
        "--tune",
        action="store_true",
        help="Run hyperparameter tuning sweep across focal gammas and learning rates",
    )
    return parser.parse_args()


class NumPySiameseMLP:
    """A two-hidden-layer MLP with exact machine anti-symmetry and Adam optimizer."""

    def __init__(
        self,
        d_in: int,
        d_h1: int = 32,
        d_h2: int = 16,
        seed: int = 42,
    ) -> None:
        self.d_in = d_in
        self.d_h1 = d_h1
        self.d_h2 = d_h2
        rng = np.random.RandomState(seed)

        # He / Kaiming normal initialization
        self.W1 = rng.randn(d_in, d_h1) * np.sqrt(2.0 / d_in)
        self.b1 = np.zeros(d_h1)
        self.W2 = rng.randn(d_h1, d_h2) * np.sqrt(2.0 / d_h1)
        self.b2 = np.zeros(d_h2)
        self.W3 = rng.randn(d_h2, 1) * np.sqrt(2.0 / d_h2)
        self.b3 = np.zeros(1)

        self.platt_slope: float = 1.0

        # Adam optimizer state
        self.m = [np.zeros_like(p) for p in self.params]
        self.v = [np.zeros_like(p) for p in self.params]
        self.t = 0

    @property
    def params(self) -> list[np.ndarray]:
        return [self.W1, self.b1, self.W2, self.b2, self.W3, self.b3]

    def forward_anti_symmetric(self, X: np.ndarray) -> tuple[np.ndarray, dict[str, np.ndarray]]:
        """Forward pass enforcing z_sym = 0.5 * (f(X) - f(-X))."""
        # Positive branch: +X
        z1_pos = X @ self.W1 + self.b1
        h1_pos = np.maximum(0.0, z1_pos)
        z2_pos = h1_pos @ self.W2 + self.b2
        h2_pos = np.maximum(0.0, z2_pos)
        out_pos = h2_pos @ self.W3 + self.b3

        # Negative branch: -X
        z1_neg = (-X) @ self.W1 + self.b1
        h1_neg = np.maximum(0.0, z1_neg)
        z2_neg = h1_neg @ self.W2 + self.b2
        h2_neg = np.maximum(0.0, z2_neg)
        out_neg = h2_neg @ self.W3 + self.b3

        z_sym = 0.5 * (out_pos - out_neg)

        cache = {
            "X": X,
            "z1_pos": z1_pos,
            "h1_pos": h1_pos,
            "z2_pos": z2_pos,
            "h2_pos": h2_pos,
            "z1_neg": z1_neg,
            "h1_neg": h1_neg,
            "z2_neg": z2_neg,
            "h2_neg": h2_neg,
        }
        return z_sym, cache

    def backward(
        self,
        grad_z: np.ndarray,
        cache: dict[str, np.ndarray],
        weight_decay: float = 1e-4,
    ) -> list[np.ndarray]:
        """Analytical backpropagation through symmetric difference."""
        X = cache["X"]
        h1_pos, h2_pos = cache["h1_pos"], cache["h2_pos"]
        h1_neg, h2_neg = cache["h1_neg"], cache["h2_neg"]
        z1_pos, z2_pos = cache["z1_pos"], cache["z2_pos"]
        z1_neg, z2_neg = cache["z1_neg"], cache["z2_neg"]

        N = len(X)
        d_out_pos = 0.5 * grad_z
        d_out_neg = -0.5 * grad_z

        # Branch gradients for W3, b3
        dW3 = (h2_pos.T @ d_out_pos + h2_neg.T @ d_out_neg) / N + weight_decay * self.W3
        db3 = (np.sum(d_out_pos, axis=0) + np.sum(d_out_neg, axis=0)) / N

        # Layer 2
        dh2_pos = d_out_pos @ self.W3.T
        dh2_neg = d_out_neg @ self.W3.T

        dz2_pos = dh2_pos * (z2_pos > 0)
        dz2_neg = dh2_neg * (z2_neg > 0)

        dW2 = (h1_pos.T @ dz2_pos + h1_neg.T @ dz2_neg) / N + weight_decay * self.W2
        db2 = (np.sum(dz2_pos, axis=0) + np.sum(dz2_neg, axis=0)) / N

        # Layer 1
        dh1_pos = dz2_pos @ self.W2.T
        dh1_neg = dz2_neg @ self.W2.T

        dz1_pos = dh1_pos * (z1_pos > 0)
        dz1_neg = dh1_neg * (z1_neg > 0)

        dW1 = (X.T @ dz1_pos - X.T @ dz1_neg) / N + weight_decay * self.W1
        db1 = (np.sum(dz1_pos, axis=0) + np.sum(dz1_neg, axis=0)) / N

        return [dW1, db1, dW2, db2, dW3, db3]

    def step_adam(
        self,
        grads: list[np.ndarray],
        lr: float = 0.003,
        beta1: float = 0.9,
        beta2: float = 0.999,
        eps: float = 1e-8,
    ) -> None:
        """Update weights using Adam optimizer."""
        self.t += 1
        params = self.params
        for i in range(len(params)):
            g = grads[i]
            self.m[i] = beta1 * self.m[i] + (1.0 - beta1) * g
            self.v[i] = beta2 * self.v[i] + (1.0 - beta2) * (g**2)

            m_hat = self.m[i] / (1.0 - beta1**self.t)
            v_hat = self.v[i] / (1.0 - beta2**self.t)

            params[i] -= lr * m_hat / (np.sqrt(v_hat) + eps)


def focal_loss_and_grad(
    y_true: np.ndarray,
    z_raw: np.ndarray,
    gamma: float = 1.0,
) -> tuple[float, np.ndarray]:
    """Compute Focal Loss and gradient with respect to raw logit z."""
    p = expit(z_raw)
    p_clipped = np.clip(p, 1e-7, 1.0 - 1e-7)

    p_t = y_true * p_clipped + (1.0 - y_true) * (1.0 - p_clipped)
    modulating_factor = (1.0 - p_t) ** gamma

    # Loss value
    bce = -(y_true * np.log(p_clipped) + (1.0 - y_true) * np.log(1.0 - p_clipped))
    loss = float(np.mean(modulating_factor * bce))

    # Gradient dL/dz (standard effective focal loss derivative)
    grad_z = modulating_factor * (p_clipped - y_true)
    return loss, grad_z


def fit_platt_scaling(z_val: np.ndarray, y_val: np.ndarray) -> float:
    """Fit 1D Platt slope on validation logits using 1D grid search / Brent."""
    slopes = np.linspace(0.5, 1.5, 101)
    best_loss = float("inf")
    best_slope = 1.0
    for s in slopes:
        p = expit(z_val * s)
        loss = log_loss(y_val, np.clip(p, 1e-6, 1.0 - 1e-6))
        if loss < best_loss:
            best_loss = loss
            best_slope = float(s)
    return best_slope


def train_single_member(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    epochs: int = 35,
    batch_size: int = 64,
    lr: float = 0.003,
    gamma: float = 1.0,
    d_h1: int = 32,
    d_h2: int = 16,
    seed: int = 42,
) -> NumPySiameseMLP:
    """Train a single Siamese member with bootstrap sampling and Platt scaling."""
    rng = np.random.RandomState(seed)
    n_train = len(X_train)
    # Bootstrap sample with replacement
    boot_idx = rng.choice(n_train, size=n_train, replace=True)
    X_boot = X_train[boot_idx]
    y_boot = y_train[boot_idx]

    model = NumPySiameseMLP(d_in=X_train.shape[1], d_h1=d_h1, d_h2=d_h2, seed=seed)

    for epoch in range(epochs):
        perm = rng.permutation(n_train)
        for i in range(0, n_train, batch_size):
            batch_idx = perm[i : i + batch_size]
            X_b = X_boot[batch_idx]
            y_b = y_boot[batch_idx]

            z_b, cache = model.forward_anti_symmetric(X_b)
            loss, grad_z = focal_loss_and_grad(y_b, z_b, gamma=gamma)
            grads = model.backward(grad_z, cache)
            model.step_adam(grads, lr=lr)

    # Fit Platt scaling slope on validation set
    z_val, _ = model.forward_anti_symmetric(X_val)
    model.platt_slope = fit_platt_scaling(z_val, y_val)
    return model


def evaluate_ensemble(
    members: list[NumPySiameseMLP],
    X: np.ndarray,
    y: np.ndarray,
    risk_kappa: float = 0.75,
) -> dict[str, float]:
    """Evaluate bagged ensemble metrics, calibration, and epistemic uncertainty."""
    logits = np.array([m.forward_anti_symmetric(X)[0] * m.platt_slope for m in members])
    # logits shape: (K, N, 1) -> squeeze to (K, N)
    logits = np.squeeze(logits, axis=-1)

    z_mean = np.mean(logits, axis=0)
    z_std = np.std(logits, axis=0, ddof=1) if len(members) > 1 else np.zeros_like(z_mean)

    p_unbiased = expit(z_mean)
    p_low = expit(z_mean - risk_kappa * z_std)

    p_c = np.clip(p_unbiased, 1e-6, 1.0 - 1e-6)
    ll = float(log_loss(y, p_c))
    brier = float(brier_score_loss(y, p_c))
    auc = float(roc_auc_score(y, p_c))
    acc = float(accuracy_score(y, (p_c >= 0.5).astype(int)))

    # Coin flip mask
    coin_mask = (p_unbiased >= 0.45) & (p_unbiased <= 0.55)
    ll_coin = float(log_loss(y[coin_mask], p_c[coin_mask])) if np.sum(coin_mask) > 0 else 0.0

    return {
        "log_loss": round(ll, 6),
        "brier": round(brier, 6),
        "roc_auc": round(auc, 6),
        "accuracy": round(acc, 6),
        "coin_flip_log_loss": round(ll_coin, 6),
        "mean_sigma_z": round(float(np.mean(z_std)), 6),
    }


def main() -> int:
    args = parse_args()
    print("=== Training Symmetrized Siamese Series Neural Ensemble ===")

    # 1. Load data
    print(f"Loading ratings dataset from: {args.ratings_data}")
    df_ratings = pd.read_csv(args.ratings_data)
    print(f"Loaded {len(df_ratings)} match rows.")

    # 2. Extract feature columns matching ratings-w20-symmetric-series-v1
    # Check if precomputed symmetric features exist in dataset or build from definitions
    feature_names = []
    # Logit fields
    for system in ("elo", "gl", "ts", "os", "pl", "tm"):
        for f in (f"team_{system}", f"player_{system}"):
            feature_names.append(f"{f}_logit")
    # Raw diff fields
    for name, _, _ in _RAW_DIFFERENCES:
        feature_names.append(name)
    # W20 fields (diff, ratio, log_ratio)
    for stat in _W20_FIELDS:
        feature_names.append(f"w20_{stat}_diff")
        feature_names.append(f"w20_{stat}_ratio")
        feature_names.append(f"w20_{stat}_log_ratio")

    print(f"Total symmetric feature dimension: {len(feature_names)}")

    # For training, build feature matrix X
    # If columns already exist in df_ratings, extract them directly; otherwise compute via feature mapping
    missing_cols = [c for c in feature_names if c not in df_ratings.columns]
    new_cols: dict[str, np.ndarray] = {}
    for system in ("elo", "gl", "ts", "os", "pl", "tm"):
        for prefix in ("team", "player"):
            col = f"{prefix}_{system}"
            target_feat = f"{col}_logit"
            if target_feat in feature_names and target_feat not in df_ratings.columns:
                if col in df_ratings.columns:
                    p = np.clip(df_ratings[col].values.astype(float), 1e-4, 1.0 - 1e-4)
                    new_cols[target_feat] = logit(p)
                else:
                    new_cols[target_feat] = np.zeros(len(df_ratings))

    for name, col1, col2 in _RAW_DIFFERENCES:
        if name in feature_names and name not in df_ratings.columns:
            if col1 in df_ratings.columns and col2 in df_ratings.columns:
                new_cols[name] = df_ratings[col1].values.astype(float) - df_ratings[col2].values.astype(float)
            else:
                new_cols[name] = np.zeros(len(df_ratings))

    for col in feature_names:
        if col not in df_ratings.columns and col not in new_cols:
            new_cols[col] = np.zeros(len(df_ratings))

    if new_cols:
        df_synth = pd.DataFrame(new_cols, index=df_ratings.index)
        df_features = pd.concat([df_ratings, df_synth], axis=1)
    else:
        df_features = df_ratings

    X_all = df_features[feature_names].fillna(0.0).values
    y_col = "y_true" if "y_true" in df_ratings.columns else "y_team1"
    y_all = df_ratings[y_col].values.astype(float).reshape(-1, 1)
    dates = pd.to_datetime(df_ratings["date"]).values

    # Scaler: zero-mean, unit standard deviation (with strict symmetry scale preservation)
    train_mask = dates < np.datetime64(args.val_date)
    val_mask = (dates >= np.datetime64(args.val_date)) & (dates < np.datetime64(args.split_date))
    test_mask = dates >= np.datetime64(args.split_date)

    print(f"Split sizes: Train={np.sum(train_mask)}, Val={np.sum(val_mask)}, Test={np.sum(test_mask)}")

    scale = np.std(X_all[train_mask], axis=0)
    scale[scale == 0.0] = 1.0
    X_scaled = X_all / scale

    X_train, y_train = X_scaled[train_mask], y_all[train_mask]
    X_val, y_val = X_scaled[val_mask], y_all[val_mask]
    X_test, y_test = X_scaled[test_mask], y_all[test_mask]

    # Hyperparameter tuning mode
    if args.tune:
        print("\n--- Running Hyperparameter Grid Search ---")
        grid_gammas = [0.0, 0.5, 1.0, 1.5, 2.0]
        grid_lrs = [0.001, 0.003, 0.005]
        tune_results = []
        for g in grid_gammas:
            for lr in grid_lrs:
                member = train_single_member(
                    X_train,
                    y_train,
                    X_val,
                    y_val,
                    epochs=25,
                    batch_size=args.batch_size,
                    lr=lr,
                    gamma=g,
                    d_h1=args.d_h1,
                    d_h2=args.d_h2,
                    seed=args.seed,
                )
                metrics = evaluate_ensemble([member], X_val, y_val)
                tune_results.append({
                    "gamma": g,
                    "lr": lr,
                    "val_log_loss": metrics["log_loss"],
                    "val_brier": metrics["brier"],
                    "val_auc": metrics["roc_auc"],
                    "platt_slope": round(member.platt_slope, 4),
                })
                print(f"Gamma={g:.1f}, LR={lr:.4f} -> Val LogLoss: {metrics['log_loss']:.4f}, AUC: {metrics['roc_auc']:.4f}")
        df_tune = pd.DataFrame(tune_results).sort_values("val_log_loss")
        print("\nTop 5 Hyperparameter Configurations:")
        print(df_tune.head(5).to_string(index=False))
        return 0

    # Train full ensemble
    print(f"\nTraining {args.n_members}-member Bagged Ensemble with Focal Loss (gamma={args.focal_gamma})...")
    members: list[NumPySiameseMLP] = []
    t0 = time.time()
    for m_i in range(args.n_members):
        seed_i = args.seed + m_i * 101
        member = train_single_member(
            X_train,
            y_train,
            X_val,
            y_val,
            epochs=args.epochs,
            batch_size=args.batch_size,
            lr=args.lr,
            gamma=args.focal_gamma,
            d_h1=args.d_h1,
            d_h2=args.d_h2,
            seed=seed_i,
        )
        members.append(member)
        print(f"  Member {m_i+1}/{args.n_members} trained (Platt slope: {member.platt_slope:.4f}).")
    t_train = time.time() - t0
    print(f"Ensemble training completed in {t_train:.2f}s.")

    # Evaluate
    train_metrics = evaluate_ensemble(members, X_train, y_train, risk_kappa=args.risk_kappa)
    val_metrics = evaluate_ensemble(members, X_val, y_val, risk_kappa=args.risk_kappa)
    test_metrics = evaluate_ensemble(members, X_test, y_test, risk_kappa=args.risk_kappa)

    print("\n--- RESULTS ---")
    print(f"Train Metrics: LogLoss={train_metrics['log_loss']}, AUC={train_metrics['roc_auc']}, Brier={train_metrics['brier']}")
    print(f"Val   Metrics: LogLoss={val_metrics['log_loss']}, AUC={val_metrics['roc_auc']}, Brier={val_metrics['brier']}")
    print(f"Test  Metrics (OOS 2025-2026): LogLoss={test_metrics['log_loss']}, AUC={test_metrics['roc_auc']}, Brier={test_metrics['brier']}")

    # Export Model Artifact
    args.output_model.parent.mkdir(parents=True, exist_ok=True)
    members_payload = []
    for m in members:
        members_payload.append({
            "w1": m.W1.tolist(),
            "b1": m.b1.tolist(),
            "w2": m.W2.tolist(),
            "b2": m.b2.tolist(),
            "w3": m.W3.tolist(),
            "b3": float(m.b3[0]),
            "platt_slope": float(m.platt_slope),
        })

    model_artifact = {
        "model_name": "Symmetrized-Siamese-Series-EXP081",
        "model_version": "exp081-siamese-series-v1",
        "feature_version": "ratings-w20-symmetric-series-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "architecture": {
            "family": "siamese_mlp_bagged",
            "d_in": len(feature_names),
            "d_h1": args.d_h1,
            "d_h2": args.d_h2,
            "activation": "relu",
            "symmetry": "anti-symmetric z_sym = 0.5 * (f(x) - f(-x))",
            "loss": f"focal_loss_gamma_{args.focal_gamma}",
            "risk_kappa": args.risk_kappa,
            "n_members": args.n_members,
        },
        "scaler": {
            "feature_names": feature_names,
            "scale": scale.tolist(),
        },
        "members": members_payload,
        "metrics": {
            "train": train_metrics,
            "val": val_metrics,
            "test": test_metrics,
        },
    }

    with open(args.output_model, "w", encoding="utf-8") as f:
        json.dump(model_artifact, f, indent=2)
    print(f"\nSuccessfully exported model artifact to: {args.output_model}")

    # Export summary report
    if args.output_report:
        args.output_report.parent.mkdir(parents=True, exist_ok=True)
        summary = {
            "experiment": "EXP-081",
            "model_name": "Symmetrized-Siamese-Series-EXP081",
            "hyperparameters": {
                "d_in": len(feature_names),
                "d_h1": args.d_h1,
                "d_h2": args.d_h2,
                "epochs": args.epochs,
                "batch_size": args.batch_size,
                "lr": args.lr,
                "focal_gamma": args.focal_gamma,
                "n_members": args.n_members,
                "risk_kappa": args.risk_kappa,
            },
            "train_metrics": train_metrics,
            "val_metrics": val_metrics,
            "test_metrics": test_metrics,
            "training_time_seconds": round(t_train, 2),
        }
        with open(args.output_report, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        print(f"Successfully exported summary report to: {args.output_report}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
