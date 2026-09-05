"""Unit and integration tests for Value Bet alerting service and API endpoints."""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from betting_app.models.base import Base
from betting_app.models.alerts import AlertConfig, ValueAlertLog
from betting_app.models.match import CanonicalMatch
from betting_app.models.prediction import ModelEvSignal, CanonicalPrediction
from betting_app.models.bookmaker import Bookmaker
from betting_app.services.alert_service import (
    build_discord_embed,
    build_telegram_html,
    get_or_create_alert_config,
    update_alert_config,
    is_alert_on_cooldown,
    scan_and_dispatch_ev_alerts,
    send_test_alert,
    send_discord_notification,
    send_telegram_notification,
)


@pytest.fixture
def sqlite_session():
    """Create an isolated in-memory SQLite database session for unit testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    # Seed bookmaker
    bm = Bookmaker(id=4, name="superbet", base_url="https://superbet.pl/")
    session.add(bm)
    session.commit()

    yield session
    session.close()


def test_build_discord_embed_format():
    signal = {
        "match_label": "G2 Esports vs Fnatic",
        "league": "LEC 2026",
        "team_name": "G2 Esports",
        "side": "a",
        "bookmaker_name": "Superbet",
        "odds": 1.95,
        "ev": 0.082,
        "model_prob": 0.62,
        "market_prob": 0.51,
        "suggested_stake": 3.4,
        "match_start_at": "2026-09-06 18:00 UTC",
    }
    embed = build_discord_embed(signal)

    assert "VALUE BET: G2 Esports vs Fnatic" in embed["title"]
    assert embed["color"] == 0x38BDF8  # Cyan for EV < 10%
    field_names = [f["name"] for f in embed["fields"]]
    assert "🎯 Typowana Drużyna" in field_names
    assert "💰 EV (po podatku 12%)" in field_names

    # High EV should be green
    signal_high = dict(signal, ev=0.14)
    embed_high = build_discord_embed(signal_high)
    assert embed_high["color"] == 0x10B981


def test_build_telegram_html_format():
    signal = {
        "match_label": "Gen.G vs T1",
        "league": "LCK 2026",
        "team_name": "Gen.G",
        "side": "a",
        "bookmaker_name": "STS",
        "odds": 2.10,
        "ev": 0.115,
        "model_prob": 0.58,
        "market_prob": 0.46,
        "suggested_stake": 4.5,
        "match_start_at": "2026-09-07 10:00 UTC",
    }
    html_text = build_telegram_html(signal)

    assert "<b>VALUE BET ALERT</b>" in html_text
    assert "Gen.G vs T1" in html_text
    assert "+11.5%" in html_text
    assert "<b>2.10</b>" in html_text
    assert "4.5% bankrolla" in html_text


def test_get_or_create_and_update_alert_config(sqlite_session):
    cfg = get_or_create_alert_config(sqlite_session)
    assert cfg.id == 1
    assert cfg.is_enabled is True
    assert cfg.min_ev == 0.05
    assert cfg.cooldown_hours == 6.0

    # Update configuration
    updated = update_alert_config(
        sqlite_session,
        is_enabled=False,
        min_ev=0.075,
        min_odds=1.40,
        discord_webhook_url="https://discord.com/api/webhooks/123/abc",
        telegram_chat_id="-100987654321",
    )
    assert updated.is_enabled is False
    assert updated.min_ev == 0.075
    assert updated.min_odds == 1.40
    assert updated.discord_webhook_url == "https://discord.com/api/webhooks/123/abc"
    assert updated.telegram_chat_id == "-100987654321"


def test_is_alert_on_cooldown_logic(sqlite_session):
    now_iso = datetime.now(timezone.utc).isoformat()
    log = ValueAlertLog(
        created_at=now_iso,
        canonical_match_id=101,
        match_label="T1 vs KT",
        side="a",
        team_name="T1",
        bookmaker_name="Superbet",
        odds=1.85,
        ev=0.06,
        status="sent",
    )
    sqlite_session.add(log)
    sqlite_session.commit()

    # Same match, bookmaker, side, similar odds -> should be on cooldown
    assert is_alert_on_cooldown(sqlite_session, 101, "Superbet", "a", 1.85, 0.06, 6.0) is True

    # Different bookmaker -> not on cooldown
    assert is_alert_on_cooldown(sqlite_session, 101, "STS", "a", 1.85, 0.06, 6.0) is False

    # Odds improved significantly (+0.06) -> cooldown bypass!
    assert is_alert_on_cooldown(sqlite_session, 101, "Superbet", "a", 1.91, 0.06, 6.0) is False

    # EV jumped by 3 percentage points (+0.03) -> cooldown bypass!
    assert is_alert_on_cooldown(sqlite_session, 101, "Superbet", "a", 1.85, 0.09, 6.0) is False


def test_scan_and_dispatch_ev_alerts(sqlite_session):
    # Seed upcoming match in the future
    future_time = (datetime.now(timezone.utc) + timedelta(hours=8)).isoformat()
    match = CanonicalMatch(
        id=201,
        canonical_key="lpl_2026_blg_jdg",
        team_a_name="Bilibili Gaming",
        team_b_name="JD Gaming",
        normalized_team_a="bilibili_gaming",
        normalized_team_b="jd_gaming",
        league="LPL",
        start_time_normalized=future_time,
    )
    sqlite_session.add(match)

    # Seed prediction
    pred = CanonicalPrediction(
        id=301,
        canonical_match_id=201,
        model_name="Operational-PlayerTeamRatings-W20",
        model_version="v2",
        prob_a=0.65,
        prob_b=0.35,
    )
    sqlite_session.add(pred)

    # Seed EV signal (>5% EV)
    signal = ModelEvSignal(
        id=401,
        canonical_match_id=201,
        canonical_prediction_id=301,
        bookmaker_id=4,
        side="a",
        odds=1.90,
        model_prob=0.65,
        market_prob=0.52,
        ev=0.083,  # +8.3%
        stake_suggestion=2.8,
        status="new",
    )
    sqlite_session.add(signal)
    sqlite_session.commit()

    # Run scan in simulated / dry run mode
    res = scan_and_dispatch_ev_alerts(sqlite_session, force_dry_run=True)
    assert res["dispatched"] == 1
    assert res["skipped"] == 0
    assert len(res["alerts"]) == 1
    assert res["alerts"][0]["team"] == "Bilibili Gaming"

    # Second scan should skip due to cooldown
    res2 = scan_and_dispatch_ev_alerts(sqlite_session, force_dry_run=True)
    assert res2["dispatched"] == 0
    assert res2["skipped"] == 1


def test_send_discord_notification_mock():
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 204
        ok, err = send_discord_notification("https://discord.com/api/webhooks/test", {"title": "Test"})
        assert ok is True
        assert err is None

        # Failure case
        mock_post.return_value.status_code = 400
        mock_post.return_value.text = "Bad Request"
        ok2, err2 = send_discord_notification("https://discord.com/api/webhooks/test", {"title": "Test"})
        assert ok2 is False
        assert "Discord HTTP 400" in err2


def test_send_telegram_notification_mock():
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        ok, err = send_telegram_notification("token123", "chat123", "<b>Hello</b>")
        assert ok is True
        assert err is None

        # Failure case
        mock_post.return_value.status_code = 403
        mock_post.return_value.text = "Forbidden"
        ok2, err2 = send_telegram_notification("token123", "chat123", "<b>Hello</b>")
        assert ok2 is False
        assert "Telegram HTTP 403" in err2


def test_api_alerts_endpoints(client: TestClient):
    # 1. GET /api/alerts/config
    # 1. GET /alerts/config
    resp = client.get("/alerts/config")
    assert resp.status_code == 200
    cfg = resp.json()
    assert "is_enabled" in cfg
    assert "min_ev" in cfg
    assert "cooldown_hours" in cfg

    # 2. POST /alerts/config
    update_resp = client.post(
        "/alerts/config",
        json={
            "min_ev": 0.065,
            "min_odds": 1.35,
            "cooldown_hours": 4.0,
            "discord_webhook_url": "https://discord.com/api/webhooks/mock123456",
        },
    )
    assert update_resp.status_code == 200
    updated = update_resp.json()
    assert updated["min_ev"] == 0.065
    assert updated["min_odds"] == 1.35
    assert updated["cooldown_hours"] == 4.0
    assert updated["discord_configured"] is True
    # Secret must be masked!
    assert "mock123456" not in updated["discord_webhook_url_masked"]
    assert updated["discord_webhook_url_masked"].endswith("456")

    # 3. POST /alerts/check?dry_run=true
    check_resp = client.post("/alerts/check?dry_run=true")
    assert check_resp.status_code == 200
    check_data = check_resp.json()
    assert "dispatched" in check_data
    assert "skipped" in check_data

    # 4. POST /alerts/test
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 204
        test_resp = client.post("/alerts/test?channel=discord")
        assert test_resp.status_code == 200
        assert "results" in test_resp.json()

    # 5. GET /alerts/history
    hist_resp = client.get("/alerts/history")
    assert hist_resp.status_code == 200
    hist = hist_resp.json()
    assert "total" in hist
    assert isinstance(hist["alerts"], list)
    assert hist["total"] >= 1
