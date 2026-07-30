"""
EXP-064: context-aware PlayerGameEncoder evaluation.

This is the next step after EXP-063.  EXP-063 showed that adding flat
team/champion context diffs to an EXP-039-style logistic regression is not
enough.  Here we test whether the context is more useful one layer earlier:
inside the player-game encoder.

The script trains two encoders on the same player-game rows:

* ``plain_player_encoder``: existing EXP-049-style player-game encoder.
* ``context_player_encoder``: the same architecture, but numeric inputs are
  augmented with leakage-safe champion-role, own-team, and opponent-team context
  vectors selected from walk-forward snapshots strictly before the game date.

Both encoders are then aggregated to match level using only prior games
(``player_game.date < match.date``), and evaluated with the existing chronological
OOF logistic match model.

The script is intentionally read-only with respect to production predictions and
model registry.  It writes only local/server artifacts and JSON reports.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score

from betting_app.core.db import init_db
from betting_app.ml.training.player_embedding_match_dataset import (
    PlayerEmbeddingMatchDatasetConfig,
    build_match_dataset_from_embeddings,
    encode_player_game_embeddings,
)
from betting_app.ml.training.player_game_dataset import PlayerGameDataset, PlayerGameDatasetConfig, build_player_game_dataset_from_db
from betting_app.ml.training.player_game_encoder import PlayerGameEncoderConfig, train_player_game_encoder
from betting_app.ml.training.strength_dataset import StrengthDataset, load_golgg_match_results
from betting_app.ml.training.strength_model import StrengthModelConfig, train_strength_model


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-date", default="2026-01-01")
    parser.add_argument("--max-date", default=None)
    parser.add_argument("--limit-player-rows", type=int, default=None)
    parser.add_argument("--limit-matches", type=int, default=None)
    parser.add_argument("--team-artifact-dir", default="betting_app/models/ml/team_context_embeddings/exp-057")
    parser.add_argument("--champion-artifact-dir", default="betting_app/models/ml/champion_role_embeddings/exp-056")
    parser.add_argument("--artifact-root", default="betting_app/models/ml")
    parser.add_argument("--model-version-prefix", default="exp-064")
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=2048)
    parser.add_argument("--embedding-dim", type=int, default=16)
    parser.add_argument("--hidden-dim", type=int, default=128)
    parser.add_argument("--latent-dim", type=int, default=64)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--validation-fraction", type=float, default=0.15)
    parser.add_argument("--device", default="auto", choices=("auto", "cpu", "cuda"))
    parser.add_argument("--embedding-batch-size", type=int, default=8192)
    parser.add_argument("--history-size", type=int, default=250)
    parser.add_argument("--min-prior-player-games", type=int, default=50)
    parser.add_argument("--initial-train-size", type=int, default=120)
    parser.add_argument("--test-size", type=int, default=60)
    parser.add_argument("--step-size", type=int, default=60)
    parser.add_argument("--min-fold-train-size", type=int, default=100)
    parser.add_argument("--logistic-c", type=float, default=0.05)
    parser.add_argument("--l1-ratio", type=float, default=0.50)
    parser.add_argument("--max-iter", type=int, default=1500)
    parser.add_argument("--tol", type=float, default=1e-3)
    parser.add_argument("--json-output", default=None)
    return parser.parse_args()


def _metrics(y: np.ndarray, p: np.ndarray) -> dict[str, Any]:
    y = np.asarray(y, dtype=int)
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return {
        "n": int(len(y)),
        "log_loss": float(log_loss(y, p, labels=[0, 1])) if len(y) else None,
        "brier": float(brier_score_loss(y, p)) if len(y) else None,
        "auc": float(roc_auc_score(y, p)) if len(set(y)) >= 2 else None,
        "accuracy": float(accuracy_score(y, p >= 0.5)) if len(y) else None,
    }


def _read_manifest(root: Path) -> list[str]:
    path = root / "walk_forward_manifest.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [str(item["snapshot"]) for item in payload.get("snapshots", [])]


def _snapshot_before_date(game_date: pd.Timestamp, snapshots: list[str]) -> str | None:
    """Select the latest snapshot strictly before the game date.

    Strictness matters here because player-game rows are completed-game rows.
    Using a snapshot at/after the same date could let that game leak into its own
    contextual features if the snapshot was built at end-of-day.
    """

    if pd.isna(game_date):
        return None
    cutoff = pd.Timestamp(game_date).tz_localize("UTC") if pd.Timestamp(game_date).tzinfo is None else pd.Timestamp(game_date).tz_convert("UTC")
    eligible = [s for s in snapshots if pd.Timestamp(s, tz="UTC") < cutoff.normalize()]
    return eligible[-1] if eligible else None


def _load_embedding_table(root: Path, snapshot: str, filename: str) -> pd.DataFrame:
    path = root / "snapshots" / snapshot / filename
    if not path.exists():
        path = root / filename
    return pd.read_csv(path)


def _load_team_context(root: Path, snapshots: list[str]) -> tuple[dict[tuple[str, str], np.ndarray], int, dict[str, int]]:
    lookup: dict[tuple[str, str], np.ndarray] = {}
    dim = 0
    rows_per_snapshot: dict[str, int] = {}
    for snap in snapshots:
        df = _load_embedding_table(root, snap, "team_context_embeddings.csv")
        cols = [c for c in df.columns if c.startswith("emb_")]
        dim = max(dim, len(cols))
        rows_per_snapshot[snap] = int(len(df))
        for row in df.itertuples(index=False):
            lookup[(snap, str(getattr(row, "team_id")))] = np.array([float(getattr(row, c)) for c in cols], dtype=float)
    return lookup, dim, rows_per_snapshot


def _load_champion_context(root: Path, snapshots: list[str]) -> tuple[dict[tuple[str, str, str], np.ndarray], int, dict[str, int]]:
    lookup: dict[tuple[str, str, str], np.ndarray] = {}
    dim = 0
    rows_per_snapshot: dict[str, int] = {}
    for snap in snapshots:
        df = _load_embedding_table(root, snap, "champion_role_embeddings.csv")
        cols = [c for c in df.columns if c.startswith("emb_")]
        dim = max(dim, len(cols))
        rows_per_snapshot[snap] = int(len(df))
        df["champion_id"] = df["champion_id"].astype(str)
        df["role"] = df["role"].astype(str).str.upper()
        for row in df.itertuples(index=False):
            lookup[(snap, str(getattr(row, "champion_id")), str(getattr(row, "role")).upper())] = np.array(
                [float(getattr(row, c)) for c in cols], dtype=float
            )
    return lookup, dim, rows_per_snapshot


def _add_vector_features(row: dict[str, Any], prefix: str, vector: np.ndarray | None, dim: int) -> None:
    missing = vector is None
    if vector is None:
        vector = np.full(dim, np.nan)
    for idx in range(dim):
        row[f"{prefix}_{idx:03d}"] = float(vector[idx])
    row[f"{prefix}_missing"] = float(missing)


def build_context_player_dataset(base: PlayerGameDataset, *, team_root: Path, champion_root: Path) -> PlayerGameDataset:
    team_snaps = _read_manifest(team_root)
    champ_snaps = _read_manifest(champion_root)
    snapshots = sorted(set(team_snaps) & set(champ_snaps))
    if not snapshots:
        raise RuntimeError("No common walk-forward snapshots for team/champion context artifacts")

    team_lookup, team_dim, team_rows = _load_team_context(team_root, snapshots)
    champion_lookup, champion_dim, champion_rows = _load_champion_context(champion_root, snapshots)

    rows: list[dict[str, Any]] = []
    coverage = {"snapshot": 0, "own_team": 0, "opponent_team": 0, "champion_role": 0}
    for rec in base.frame.to_dict(orient="records"):
        snap = _snapshot_before_date(pd.Timestamp(rec.get("date")), snapshots)
        if snap is None:
            continue
        out = dict(rec)
        out["context_snapshot"] = snap
        coverage["snapshot"] += 1
        own = team_lookup.get((snap, str(rec.get("team_id"))))
        opp = team_lookup.get((snap, str(rec.get("opponent_team_id"))))
        champ = champion_lookup.get((snap, str(rec.get("champion_id")), str(rec.get("role")).upper()))
        coverage["own_team"] += int(own is not None)
        coverage["opponent_team"] += int(opp is not None)
        coverage["champion_role"] += int(champ is not None)
        _add_vector_features(out, "ctx_own_team", own, team_dim)
        _add_vector_features(out, "ctx_opponent_team", opp, team_dim)
        _add_vector_features(out, "ctx_champion_role", champ, champion_dim)
        rows.append(out)

    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = frame.sort_values(["date", "game_id", "side", "role_index"]).reset_index(drop=True)
    context_features = [c for c in frame.columns if c.startswith("ctx_")]
    metadata = dict(base.metadata)
    metadata.update(
        {
            "experiment_id": "EXP-064",
            "purpose": "Player-game dataset augmented with strict pre-game champion/team/opponent context embeddings.",
            "base_rows": int(len(base.frame)),
            "rows": int(len(frame)),
            "context_feature_count": int(len(context_features)),
            "team_context_dim": int(team_dim),
            "champion_role_dim": int(champion_dim),
            "context_snapshots": snapshots,
            "coverage": {k: float(v / max(len(frame), 1)) for k, v in coverage.items()},
            "team_rows_per_snapshot": team_rows,
            "champion_rows_per_snapshot": champion_rows,
            "leakage_note": "Context snapshot is strictly before player-game date; match aggregation still uses only prior games.",
        }
    )
    if not frame.empty:
        metadata["date_min"] = frame["date"].min().isoformat() if pd.notna(frame["date"].min()) else None
        metadata["date_max"] = frame["date"].max().isoformat() if pd.notna(frame["date"].max()) else None
    return PlayerGameDataset(
        frame=frame,
        feature_names=list(base.feature_names) + context_features,
        categorical_names=base.categorical_names,
        target_names=base.target_names,
        metadata=metadata,
    )


def _train_encoder(dataset: PlayerGameDataset, *, label: str, args: argparse.Namespace) -> Any:
    return train_player_game_encoder(
        dataset,
        PlayerGameEncoderConfig(
            experiment_id="EXP-064",
            model_name="ContextAwarePlayerGameEncoder" if label == "context" else "PlayerGameEncoder",
            model_version=f"{args.model_version_prefix}-{label}",
            embedding_dim=args.embedding_dim,
            hidden_dim=args.hidden_dim,
            latent_dim=args.latent_dim,
            epochs=args.epochs,
            batch_size=args.batch_size,
            learning_rate=args.learning_rate,
            weight_decay=args.weight_decay,
            validation_fraction=args.validation_fraction,
            device=args.device,
        ),
        artifact_root=Path(args.artifact_root),
    )


def _train_match_oof(dataset: Any, *, name: str, args: argparse.Namespace) -> Any:
    ds = StrengthDataset(frame=dataset.frame, feature_names=dataset.feature_names, metadata=dataset.metadata)
    cfg = StrengthModelConfig(
        model_name=name,
        model_version="exp-064-oof",
        initial_train_size=args.initial_train_size,
        test_size=args.test_size,
        step_size=args.step_size,
        min_fold_train_size=args.min_fold_train_size,
        logistic_c=args.logistic_c,
        l1_ratio=args.l1_ratio,
        max_iter=args.max_iter,
        tol=args.tol,
        random_state=42,
        use_order_augmentation=True,
        calibrate=True,
        collect_oof=True,
    )
    return train_strength_model(ds, cfg)


def _oof_metrics(result: Any) -> dict[str, Any]:
    if result.oof_frame is None:
        return {}
    y = result.oof_frame["target"].astype(int).to_numpy()
    return {
        "raw": _metrics(y, result.oof_frame["oof_prob_raw"].to_numpy(dtype=float)),
        "calibrated": _metrics(y, result.oof_frame["oof_prob_calibrated"].to_numpy(dtype=float)),
    }


def main() -> None:
    args = parse_args()
    init_db()

    base_player = build_player_game_dataset_from_db(
        PlayerGameDatasetConfig(min_date=args.min_date, max_date=args.max_date, limit_rows=args.limit_player_rows)
    )
    context_player = build_context_player_dataset(
        base_player,
        team_root=Path(args.team_artifact_dir),
        champion_root=Path(args.champion_artifact_dir),
    )
    if context_player.frame.empty:
        raise RuntimeError("Context-aware player dataset is empty")

    # Compare on the same player rows to isolate the value of extra context.
    plain_same_frame = base_player.frame.merge(
        context_player.frame[["game_id", "player_id", "team_id", "role", "champion_id", "date"]],
        on=["game_id", "player_id", "team_id", "role", "champion_id", "date"],
        how="inner",
    )
    plain_player = PlayerGameDataset(
        frame=plain_same_frame.sort_values(["date", "game_id", "side", "role_index"]).reset_index(drop=True),
        feature_names=base_player.feature_names,
        categorical_names=base_player.categorical_names,
        target_names=base_player.target_names,
        metadata={**base_player.metadata, "experiment_id": "EXP-064", "rows": int(len(plain_same_frame)), "purpose": "Plain encoder restricted to context-covered rows."},
    )

    plain_encoder = _train_encoder(plain_player, label="plain", args=args)
    context_encoder = _train_encoder(context_player, label="context", args=args)

    matches = load_golgg_match_results(min_date=args.min_date, max_date=args.max_date, limit_rows=args.limit_matches)
    plain_embeddings = encode_player_game_embeddings(
        plain_player,
        encoder_artifact=plain_encoder.artifact_path,
        device=args.device,
        batch_size=args.embedding_batch_size,
    )
    context_embeddings = encode_player_game_embeddings(
        context_player,
        encoder_artifact=context_encoder.artifact_path,
        device=args.device,
        batch_size=args.embedding_batch_size,
    )
    match_cfg = PlayerEmbeddingMatchDatasetConfig(
        experiment_id="EXP-064",
        history_size=args.history_size,
        min_prior_player_games=args.min_prior_player_games,
    )
    plain_match = build_match_dataset_from_embeddings(matches, plain_embeddings, match_cfg)
    context_match = build_match_dataset_from_embeddings(matches, context_embeddings, match_cfg)

    plain_result = _train_match_oof(plain_match, name="EXP064-PlainPlayerEncoder-MatchLR", args=args)
    context_result = _train_match_oof(context_match, name="EXP064-ContextAwarePlayerEncoder-MatchLR", args=args)

    payload = {
        "experiment_id": "EXP-064",
        "description": "Context-aware player-game encoder vs plain player-game encoder, both aggregated leakage-safely to match level.",
        "args": vars(args),
        "plain_player_dataset_metadata": plain_player.metadata,
        "context_player_dataset_metadata": context_player.metadata,
        "plain_encoder": {"artifact_path": str(plain_encoder.artifact_path), "metadata": plain_encoder.metadata, "history_tail": plain_encoder.history[-5:]},
        "context_encoder": {"artifact_path": str(context_encoder.artifact_path), "metadata": context_encoder.metadata, "history_tail": context_encoder.history[-5:]},
        "plain_match_dataset_metadata": plain_match.metadata,
        "context_match_dataset_metadata": context_match.metadata,
        "plain_match_model": {"metrics": plain_result.metrics, "oof_metrics": _oof_metrics(plain_result), "folds": [asdict(f) for f in plain_result.folds]},
        "context_match_model": {"metrics": context_result.metrics, "oof_metrics": _oof_metrics(context_result), "folds": [asdict(f) for f in context_result.folds]},
    }
    text = json.dumps(payload, indent=2, sort_keys=True, default=str)
    if args.json_output:
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
