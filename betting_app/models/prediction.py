"""Prediction / rating / feature models."""

from __future__ import annotations

from sqlalchemy import (
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from betting_app.models.base import Base


class ModelArtifact(Base):
    __tablename__ = "model_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    artifact_path: Mapped[str | None] = mapped_column(String(500))
    feature_schema_json: Mapped[str | None] = mapped_column(Text)
    model_params_json: Mapped[str | None] = mapped_column(Text)
    training_cutoff_at: Mapped[str | None] = mapped_column(String(50))
    metrics_json: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="registered")

    __table_args__ = (UniqueConstraint("model_name", "model_version"),)


class RatingRun(Base):
    __tablename__ = "rating_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ratings_version: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    source: Mapped[str | None] = mapped_column(String(100))
    data_cutoff_at: Mapped[str | None] = mapped_column(String(50))
    started_at: Mapped[str | None] = mapped_column(String(50))
    finished_at: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(50), default="running")
    systems_json: Mapped[str | None] = mapped_column(Text)
    matches_processed: Mapped[int] = mapped_column(Integer, default=0)
    games_processed: Mapped[int] = mapped_column(Integer, default=0)
    players_processed: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)


class EntityRating(Base):
    __tablename__ = "entity_ratings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rating_run_id: Mapped[int | None] = mapped_column(ForeignKey("rating_runs.id"))
    ratings_version: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    snapshot_at: Mapped[str | None] = mapped_column(String(50))
    entity_type: Mapped[str] = mapped_column(String(20), index=True)
    entity_name: Mapped[str] = mapped_column(String(200))
    normalized_entity_name: Mapped[str] = mapped_column(String(200), index=True)
    team_name: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[str | None] = mapped_column(String(20))
    rating_system: Mapped[str] = mapped_column(String(20), index=True)
    rating_value: Mapped[float | None] = mapped_column(Integer)
    rd: Mapped[float | None] = mapped_column(Integer)
    sigma: Mapped[float | None] = mapped_column(Integer)
    games_played: Mapped[int] = mapped_column(Integer, default=0)
    last_match_at: Mapped[str | None] = mapped_column(String(50))
    state_json: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (UniqueConstraint("ratings_version", "entity_type", "normalized_entity_name", "rating_system"),)


class TeamRollingFeature(Base):
    __tablename__ = "team_rolling_features"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    feature_version: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    team_name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_team_name: Mapped[str] = mapped_column(String(200), nullable=False)
    window_size: Mapped[int] = mapped_column(Integer, default=20)
    data_cutoff_at: Mapped[str | None] = mapped_column(String(50))
    matches_count: Mapped[int] = mapped_column(Integer, default=0)
    games_count: Mapped[int] = mapped_column(Integer, default=0)
    win_rate: Mapped[float | None] = mapped_column(Integer)
    avg_kills: Mapped[float | None] = mapped_column(Integer)
    avg_deaths: Mapped[float | None] = mapped_column(Integer)
    avg_gd15: Mapped[float | None] = mapped_column(Integer)
    avg_dpm: Mapped[float | None] = mapped_column(Integer)
    avg_vspm: Mapped[float | None] = mapped_column(Integer)
    avg_gold: Mapped[float | None] = mapped_column(Integer)
    avg_towers: Mapped[float | None] = mapped_column(Integer)
    avg_dragons: Mapped[float | None] = mapped_column(Integer)
    avg_nashors: Mapped[float | None] = mapped_column(Integer)
    avg_game_duration: Mapped[float | None] = mapped_column(Integer)
    features_json: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (UniqueConstraint("feature_version", "normalized_team_name", "window_size"),)


class UpcomingMatchFeature(Base):
    __tablename__ = "upcoming_match_features"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    canonical_match_id: Mapped[int] = mapped_column(ForeignKey("canonical_matches.id"), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(100), nullable=False)
    ratings_version: Mapped[str] = mapped_column(String(100), nullable=False)
    data_cutoff_at: Mapped[str | None] = mapped_column(String(50))
    team_a_golgg_name: Mapped[str | None] = mapped_column(String(200))
    team_b_golgg_name: Mapped[str | None] = mapped_column(String(200))
    feature_status: Mapped[str] = mapped_column(String(50), default="pending")
    missing_reason: Mapped[str | None] = mapped_column(Text)
    features_json: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (UniqueConstraint("canonical_match_id", "feature_version", "ratings_version"),)


class CanonicalPrediction(Base):
    __tablename__ = "canonical_predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    canonical_match_id: Mapped[int] = mapped_column(ForeignKey("canonical_matches.id"), nullable=False, index=True)
    model_artifact_id: Mapped[int | None] = mapped_column(ForeignKey("model_artifacts.id"))
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    predicted_at: Mapped[str | None] = mapped_column(String(50))
    prob_a: Mapped[float | None] = mapped_column(Integer)
    prob_b: Mapped[float | None] = mapped_column(Integer)
    features_version: Mapped[str | None] = mapped_column(String(100))
    ratings_version: Mapped[str | None] = mapped_column(String(100))
    data_cutoff_at: Mapped[str | None] = mapped_column(String(50))
    prediction_status: Mapped[str] = mapped_column(String(50), default="active")
    diagnostics_json: Mapped[str | None] = mapped_column(Text)


class ModelEvSignal(Base):
    __tablename__ = "model_ev_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    canonical_match_id: Mapped[int] = mapped_column(ForeignKey("canonical_matches.id"), nullable=False, index=True)
    canonical_prediction_id: Mapped[int | None] = mapped_column(ForeignKey("canonical_predictions.id"))
    odds_snapshot_id: Mapped[int | None] = mapped_column(Integer)
    bookmaker_id: Mapped[int] = mapped_column(ForeignKey("bookmakers.id"), nullable=False)
    side: Mapped[str] = mapped_column(String(5), nullable=False)
    odds: Mapped[float | None] = mapped_column(Integer)
    model_prob: Mapped[float | None] = mapped_column(Integer)
    market_prob: Mapped[float | None] = mapped_column(Integer)
    ev: Mapped[float | None] = mapped_column(Integer)
    tax_rate: Mapped[float] = mapped_column(Integer, default=0.12)
    stake_suggestion: Mapped[float | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(50), default="new")
