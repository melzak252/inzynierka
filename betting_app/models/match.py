"""Canonical match and upcoming match models."""

from __future__ import annotations

from sqlalchemy import (
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text as sa_text,
)
from sqlalchemy.orm import Mapped, mapped_column

from betting_app.models.base import Base


class CanonicalMatch(Base):
    __tablename__ = "canonical_matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    canonical_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    team_a_name: Mapped[str] = mapped_column(String(200), nullable=False)
    team_b_name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_team_a: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_team_b: Mapped[str] = mapped_column(String(200), nullable=False)
    start_time_normalized: Mapped[str | None] = mapped_column(String(50))
    league: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(50), server_default="'upcoming'")
    match_confidence: Mapped[float] = mapped_column(Integer, server_default="1")


class UpcomingMatch(Base):
    __tablename__ = "upcoming_matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bookmaker_id: Mapped[int] = mapped_column(ForeignKey("bookmakers.id"), nullable=False)
    bookmaker_match_key: Mapped[str] = mapped_column(String(200), nullable=False)
    canonical_match_id: Mapped[int | None] = mapped_column(ForeignKey("canonical_matches.id"))
    raw_team_a: Mapped[str] = mapped_column(String(200), nullable=False)
    raw_team_b: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_team_a: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_team_b: Mapped[str] = mapped_column(String(200), nullable=False)
    match_start_time: Mapped[str | None] = mapped_column(String(50))
    league: Mapped[str | None] = mapped_column(String(100))
    source_url: Mapped[str | None] = mapped_column(String(500))
    offer_url: Mapped[str | None] = mapped_column(String(500))
    is_live: Mapped[bool] = mapped_column(Integer, server_default="0")

    __table_args__ = (UniqueConstraint("bookmaker_match_key"),)
