"""Bookmaker, wallet and bet models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from betting_app.models.base import Base


class Bookmaker(Base):
    __tablename__ = "bookmakers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(default=True)


class BookmakerAccount(Base):
    __tablename__ = "bookmaker_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bookmaker_id: Mapped[int] = mapped_column(ForeignKey("bookmakers.id"), nullable=False)
    account_name: Mapped[str] = mapped_column(String(100), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="PLN")
    opening_balance: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    current_balance: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("bookmaker_id", "account_name"),)


class Bet(Base):
    __tablename__ = "bets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_id: Mapped[int | None] = mapped_column(Integer)
    model_ev_signal_id: Mapped[int | None] = mapped_column(Integer)
    bookmaker_account_id: Mapped[int | None] = mapped_column(ForeignKey("bookmaker_accounts.id"))
    canonical_match_id: Mapped[int | None] = mapped_column(ForeignKey("canonical_matches.id"))
    placed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    bookmaker_id: Mapped[int | None] = mapped_column(Integer)
    side: Mapped[str] = mapped_column(String(1), CheckConstraint("side IN ('a','b')"))
    stake: Mapped[float] = mapped_column(Numeric(12, 2))
    taken_odds: Mapped[float] = mapped_column(Numeric(8, 4))
    status: Mapped[str] = mapped_column(String(20), default="open")
    result: Mapped[str | None] = mapped_column(String(20))
    profit: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime)
    team_a: Mapped[str | None] = mapped_column(String(200))
    team_b: Mapped[str | None] = mapped_column(String(200))
    league: Mapped[str | None] = mapped_column(String(100))
    match_start_time: Mapped[datetime | None] = mapped_column(DateTime)
    model_prob: Mapped[float | None] = mapped_column(Numeric(6, 4))
    ev: Mapped[float | None] = mapped_column(Numeric(10, 4))
    tax_rate: Mapped[float] = mapped_column(Numeric(4, 2), default=0.12)
    note: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(50), default="manual")


class WalletTransaction(Base):
    __tablename__ = "bookmaker_wallet_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bookmaker_account_id: Mapped[int] = mapped_column(ForeignKey("bookmaker_accounts.id"))
    bet_id: Mapped[int | None] = mapped_column(ForeignKey("bets.id"))
    transaction_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    transaction_type: Mapped[str] = mapped_column(String(50))
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    balance_after: Mapped[float] = mapped_column(Numeric(12, 2))
    note: Mapped[str | None] = mapped_column(Text)
