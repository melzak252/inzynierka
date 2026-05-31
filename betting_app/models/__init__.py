"""SQLAlchemy ORM models for the betting database."""

from betting_app.models.base import Base, get_sync_session, get_async_session, is_timescale, is_sqlite

from betting_app.models.bookmaker import Bookmaker, BookmakerAccount, Bet, WalletTransaction
from betting_app.models.golgg import GolggTeam, GolggMatch, GolggGame, GolggGamePlayer, TeamAlias
from betting_app.models.match import CanonicalMatch, UpcomingMatch
from betting_app.models.odds import (
    OddsSnapshot,
    ScrapeRun,
    BookmakerEvent,
    BookmakerMarket,
    OddsOutcomeSnapshot,
)
from betting_app.models.prediction import (
    ModelArtifact,
    RatingRun,
    EntityRating,
    TeamRollingFeature,
    UpcomingMatchFeature,
    CanonicalPrediction,
    ModelEvSignal,
)
from betting_app.models.automation import AutomationRun, AutomationCommand

__all__ = [
    "Base",
    "get_sync_session",
    "get_async_session",
    "is_timescale",
    "is_sqlite",
    "Bookmaker",
    "BookmakerAccount",
    "Bet",
    "WalletTransaction",
    "GolggTeam",
    "GolggMatch",
    "GolggGame",
    "GolggGamePlayer",
    "TeamAlias",
    "CanonicalMatch",
    "UpcomingMatch",
    "OddsSnapshot",
    "ScrapeRun",
    "BookmakerEvent",
    "BookmakerMarket",
    "OddsOutcomeSnapshot",
    "ModelArtifact",
    "RatingRun",
    "EntityRating",
    "TeamRollingFeature",
    "UpcomingMatchFeature",
    "CanonicalPrediction",
    "ModelEvSignal",
    "AutomationRun",
    "AutomationCommand",
]
