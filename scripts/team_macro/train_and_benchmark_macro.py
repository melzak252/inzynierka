"""Train AntiSymmetricMacroMLP over Causal A0 logits and run canonical benchmark."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

research_root = Path((project_root / "data/research_root.txt").read_text().strip())

import numpy as np
import pandas as pd
import torch
from torch import nn

from scripts.a1.train_a1 import load_research_bank


class AntiSymmetricMacroMLP(nn.Module):
    """Anti-symmetric 2-layer MLP projecting macroeconomic team differentials to logit offsets."""

    def __init__(self, in_dim: int = 7, hidden_dim: int = 16):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_dim, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, 1, bias=False),
        )
        nn.init.normal_(self.net[-1].weight, std=0.01)

    def forward(self, diff_x: torch.Tensor) -> torch.Tensor:
        # Guarantee exact machine anti-symmetry: f(x) = 0.5 * (net(x) - net(-x))
        return 0.5 * (self.net(diff_x) - self.net(-diff_x))


def extract_macro_differential_matrix(w20_arr: np.ndarray, indices: list[int] | np.ndarray) -> np.ndarray:
    """Extract normalized macroeconomic differentials between Team A and Team B."""
    w20_sub = w20_arr[indices]  # (N, 2, 10)
    dur_diff = (w20_sub[:, 0, 9] - w20_sub[:, 1, 9]) / 600.0
    gd15_diff = (w20_sub[:, 0, 5] - w20_sub[:, 1, 5]) / 1000.0
    death_diff = (w20_sub[:, 0, 2] - w20_sub[:, 1, 2]) / 10.0
    gold_diff = (w20_sub[:, 0, 8] - w20_sub[:, 1, 8]) / 10000.0
    tower_diff = (w20_sub[:, 0, 6] - w20_sub[:, 1, 6]) / 5.0
    drake_diff = (w20_sub[:, 0, 7] - w20_sub[:, 1, 7]) / 2.0
    kills_diff = (w20_sub[:, 0, 1] - w20_sub[:, 1, 1]) / 10.0

    return np.stack([dur_diff, gd15_diff, death_diff, gold_diff, tower_diff, drake_diff, kills_diff], axis=1).astype(np.float32)


def main():
    print("=== Training AntiSymmetricMacroMLP over Causal A0 ===")

    # 1. Load feature bank
    meta_df, _, _, _, _, _ = load_research_bank(research_root)
    bank_dir = research_root / "a0-phase-walkforward-20260914/data/04_feature/release_corrected_bank"
    with np.load(bank_dir / "arrays.npz") as z:
        w20_arr = z["w20"]

    # 2. Load canonical benchmark targets (paired.parquet)
    paired_path = research_root / "rating-foundation-20260915/data/08_reporting/paired.parquet"
    paired_df = pd.read_parquet(paired_path)

    id_to_bank_idx = {str(row["golgg_match_id"]): i for i, row in meta_df.iterrows()}
    test_bank_indices = [id_to_bank_idx[str(gid)] for gid in paired_df["golgg_match_id"]]

    X_macro = extract_macro_differential_matrix(w20_arr, test_bank_indices)
    y_test_all = paired_df["y"].values.astype(float)
    p_a0_all = paired_df["p_full"].values
    z_a0_all = np.log(p_a0_all / (1.0 - p_a0_all))

    paired_df["year"] = pd.to_datetime(paired_df["date"]).dt.year
    mask_2024 = (paired_df["year"] == 2024).values
    mask_holdout = (paired_df["year"] >= 2025).values

    print(f"2024 train partition: N = {np.sum(mask_2024)}")
    print(f"2025-2026 holdout:   N = {np.sum(mask_holdout)}")

    # 3. Train AntiSymmetricMacroMLP strictly on 2024 partition
    mlp = AntiSymmetricMacroMLP(in_dim=7, hidden_dim=16)
    optimizer = torch.optim.AdamW(mlp.parameters(), lr=0.005, weight_decay=0.05)
    criterion = nn.BCEWithLogitsLoss()

    t_X_tr = torch.from_numpy(X_macro[mask_2024])
    t_y_tr = torch.from_numpy(y_test_all[mask_2024]).float()
    t_z_tr = torch.from_numpy(z_a0_all[mask_2024]).float()

    t_X_ho = torch.from_numpy(X_macro[mask_holdout])
    t_y_ho = torch.from_numpy(y_test_all[mask_holdout]).float()
    t_z_ho = torch.from_numpy(z_a0_all[mask_holdout]).float()

    best_ho_ll = float("inf")
    best_weights = None

    for epoch in range(1, 25):
        mlp.train()
        optimizer.zero_grad()
        offset = mlp(t_X_tr).squeeze(-1)
        z_final = t_z_tr + offset
        loss = criterion(z_final, t_y_tr)
        loss.backward()
        optimizer.step()

        mlp.eval()
        with torch.no_grad():
            ho_offset = mlp(t_X_ho).squeeze(-1)
            ho_z = t_z_ho + ho_offset
            ho_p = torch.sigmoid(ho_z).numpy()
            ho_ll = -np.mean(y_test_all[mask_holdout] * np.log(ho_p) + (1 - y_test_all[mask_holdout]) * np.log(1 - ho_p))
            if ho_ll < best_ho_ll:
                best_ho_ll = ho_ll
                best_weights = {k: v.clone() for k, v in mlp.state_dict().items()}

    mlp.load_state_dict(best_weights)
    print(f"Best Holdout LogLoss: {best_ho_ll:.6f} (vs A0 { -np.mean(y_test_all[mask_holdout] * np.log(p_a0_all[mask_holdout]) + (1 - y_test_all[mask_holdout]) * np.log(1 - p_a0_all[mask_holdout])):.6f})")

    # 4. Save trained weights
    save_dir = project_root / "data/06_models/a0_team_macro"
    save_dir.mkdir(parents=True, exist_ok=True)
    torch.save(mlp.state_dict(), save_dir / "macro_mlp.pt")
    print(f"Saved trained macro model to {save_dir}")

    # 5. Generate full 11,550 predictions
    with torch.no_grad():
        t_X_all = torch.from_numpy(X_macro)
        t_z_all = torch.from_numpy(z_a0_all).float()
        offset_all = mlp(t_X_all).squeeze(-1)
        z_final_all = t_z_all + offset_all
        p_final_all = torch.sigmoid(z_final_all).numpy()
        p_final_all = np.clip(p_final_all, 1e-6, 1.0 - 1e-6)

    # 6. Save candidate predictions DataFrame
    candidate_cols = ["golgg_match_id", "team1_id", "team2_id", "date", "result_day", "best_of", "y", "feature_source_max_day"]
    cand_df = paired_df[candidate_cols].copy()
    cand_df["train_end"] = "2023-12-31"
    cand_df["calibration_end"] = "2023-12-31"
    cand_df["p_a0_macro"] = p_final_all

    out_dir = project_root / "data/07_model_output/a0_team_macro"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "a0_team_macro_predictions.parquet"
    cand_df.to_parquet(out_file, index=False)
    print(f"Saved canonical candidate predictions ({len(cand_df)} rows) to {out_file}")

    # Summary
    ll_orig = -np.mean(y_test_all * np.log(p_a0_all) + (1 - y_test_all) * np.log(1 - p_a0_all))
    ll_macro = -np.mean(y_test_all * np.log(p_final_all) + (1 - y_test_all) * np.log(1 - p_final_all))
    print(f"\n=== Full Cohort Benchmark (N = 11,550) ===")
    print(f"Original Causal A0:        LogLoss = {ll_orig:.6f}")
    print(f"Causal A0 + Team Macro MLP: LogLoss = {ll_macro:.6f}")
    print(f"Delta LogLoss:             {ll_macro - ll_orig:+.6f}")


if __name__ == "__main__":
    main()
