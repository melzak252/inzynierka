"""Invalid tournament state is a client error, not a fabricated forecast or HTTP 500."""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from betting_app.api.routers import tournaments
from betting_app.services.tournament_service import BracketMatchNode, TournamentBracket, TournamentSimulator


@pytest.mark.parametrize("method,path", [
    ("GET", "/tournaments/invalid"),
    ("POST", "/tournaments/invalid/sync"),
    ("POST", "/tournaments/invalid/simulate"),
])
def test_invalid_bracket_returns_422_without_forecasts(monkeypatch, method, path):
    bracket = TournamentBracket(
        id="invalid", name="Invalid cycle", region="fixture", format="single_elimination",
        teams=["A", "B"],
        matches={"final": BracketMatchNode(
            id="final", name="Final", round_name="Final", bracket_section="final",
            best_of=3, team1="A", team2="B", next_match_winner_id="final",
        )},
    )
    simulator = TournamentSimulator(team_ratings={"A": 1500.0, "B": 1500.0})
    monkeypatch.setattr(tournaments, "SUPPORTED_BRACKETS", {"invalid": lambda: bracket})
    monkeypatch.setattr(tournaments, "TournamentSimulator", lambda: simulator)
    monkeypatch.setattr(tournaments, "LiquipediaBracketService", lambda: SimpleNamespace(
        sync_bracket=lambda *args, **kwargs: {"bracket": bracket, "source": "fixture"},
    ))
    app = FastAPI()
    app.include_router(tournaments.router)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.request(method, path, **({"json": {}} if method == "POST" else {}))
    assert response.status_code == 422
    assert "standings" not in response.json()


def test_unavailable_rating_source_returns_500_without_forecasts(monkeypatch):
    bracket = TournamentBracket(
        id="offline", name="Offline ratings", region="fixture", format="single_elimination",
        teams=["A", "B"],
        matches={"final": BracketMatchNode(
            id="final", name="Final", round_name="Final", bracket_section="final",
            best_of=3, team1="A", team2="B",
        )},
    )

    def unavailable_database():
        raise ConnectionError("private-database-diagnostic")

    monkeypatch.setattr(
        "betting_app.services.tournament_service.connect", unavailable_database,
    )
    monkeypatch.setattr(
        "betting_app.services.tournament_service.canonical_team_key", str.lower,
    )
    monkeypatch.setattr(tournaments, "SUPPORTED_BRACKETS", {"offline": lambda: bracket})
    monkeypatch.setattr(tournaments, "LiquipediaBracketService", lambda: SimpleNamespace(
        sync_bracket=lambda *args, **kwargs: {"bracket": bracket, "source": "fixture"},
    ))
    app = FastAPI()
    app.include_router(tournaments.router)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/tournaments/offline")
    assert response.status_code == 500
    assert "standings" not in response.text
    assert "private-database-diagnostic" not in response.text
