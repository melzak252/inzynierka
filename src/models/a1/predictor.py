"""A1 Predictor: inference adapter and calibrated mixture ensemble."""

from __future__ import annotations

from pathlib import Path
import json
import torch
import numpy as np

from src.models.a1.architecture import A1Model, A1Config


class A1Predictor:
    """Inference predictor for the trained A1 neural model."""

    def __init__(self, model: A1Model, calibration_params: dict | None = None):
        self.model = model
        self.model.eval()
        self.calibration_params = calibration_params or {"platt_a": 1.0, "platt_b": 0.0}

    @torch.no_grad()
    def predict_batch(
        self,
        context: np.ndarray,
        player_ratings: np.ndarray,
        player_history: np.ndarray,
        player_mask: np.ndarray,
        player_champions: np.ndarray,
        meta_champions: np.ndarray,
        best_of: np.ndarray,
    ) -> np.ndarray:
        """Predict win probabilities for a batch of matches."""
        ctx_t = torch.as_tensor(context, dtype=torch.float32)
        pr_t = torch.as_tensor(player_ratings, dtype=torch.float32)
        ph_t = torch.as_tensor(player_history, dtype=torch.float32)
        pm_t = torch.as_tensor(player_mask, dtype=torch.uint8)
        pc_t = torch.as_tensor(player_champions, dtype=torch.long)
        mc_t = torch.as_tensor(meta_champions, dtype=torch.float32)
        bo_t = torch.as_tensor(best_of, dtype=torch.long)

        raw_probs = self.model(
            context=ctx_t,
            player_ratings=pr_t,
            player_history=ph_t,
            player_mask=pm_t,
            player_champions=pc_t,
            meta_champions=mc_t,
            best_of=bo_t,
        ).cpu().numpy()

        # Apply calibration if parameters exist
        a = self.calibration_params.get("platt_a", 1.0)
        b = self.calibration_params.get("platt_b", 0.0)
        if a != 1.0 or b != 0.0:
            logit_raw = np.log(np.clip(raw_probs, 1e-6, 1.0 - 1e-6) / np.clip(1.0 - raw_probs, 1e-6, 1.0 - 1e-6))
            logit_cal = a * logit_raw + b
            cal_probs = 1.0 / (1.0 + np.exp(-logit_cal))
            return np.clip(cal_probs, 1e-6, 1.0 - 1e-6)

        return np.clip(raw_probs, 1e-6, 1.0 - 1e-6)
