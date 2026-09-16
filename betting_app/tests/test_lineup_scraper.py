"""Unit tests for confirmed lineup ingestion, substitution detection, and re-inference."""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from betting_app.scrapers.lineup_scraper import (
    ConfirmedLineupScraper,
    check_confirmed_lineup,
    detect_lineup_substitution,
    is_within_lineup_window,
    normalize_player_id,
)
from betting_app.services.upcoming_inference_service import (
    build_features_for_match,
    process_confirmed_lineup_update,
)


@pytest.fixture
def sqlite_session():
    """In-memory SQLite session with team_current_roster_players schema."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(
            text("""
            CREATE TABLE team_current_roster_players (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_name VARCHAR(200) NOT NULL,
                normalized_team_name VARCHAR(200) NOT NULL,
                source_match_id VARCHAR(100),
                source_game_id VARCHAR(100),
                source_match_date VARCHAR(50),
                source VARCHAR(50) DEFAULT 'auto',
                team_id VARCHAR(100),
                player_id VARCHAR(100) NOT NULL,
                player_name VARCHAR(200) NOT NULL,
                role VARCHAR(30) NOT NULL,
                updated_at DATETIME,
                UNIQUE (normalized_team_name, role)
            )
            """)
        )
        conn.execute(
            text("""
            CREATE TABLE canonical_matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_a_name VARCHAR(200) NOT NULL,
                team_b_name VARCHAR(200) NOT NULL,
                start_time_normalized VARCHAR(50),
                status VARCHAR(50) DEFAULT 'upcoming'
            )
            """)
        )

    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


# ============================================================================
# 1. detect_lineup_substitution tests
# ============================================================================

def test_detect_lineup_substitution_no_change():
    """Test no-change scenario: identical starters in same or different order."""
    previous = ["Faker", "Zeus", "Oner", "Gumayusi", "Keria"]
    confirmed_same_order = ["Faker", "Zeus", "Oner", "Gumayusi", "Keria"]
    confirmed_diff_order = ["Keria", "Gumayusi", "Oner", "Zeus", "Faker"]

    has_sub, subs = detect_lineup_substitution(previous, confirmed_same_order)
    assert has_sub is False
    assert subs == []

    has_sub_order, subs_order = detect_lineup_substitution(previous, confirmed_diff_order)
    assert has_sub_order is False
    assert subs_order == []


def test_detect_lineup_substitution_single_sub():
    """Test substitution scenario: 1 sub -> substitution detected, returns substituted player ID."""
    previous = ["Faker", "Zeus", "Oner", "Gumayusi", "Keria"]
    confirmed = ["Faker", "Doran", "Oner", "Gumayusi", "Keria"]

    has_sub, subs = detect_lineup_substitution(previous, confirmed)
    assert has_sub is True
    assert subs == ["Doran"]


def test_detect_lineup_substitution_multiple_subs():
    """Test multiple substitutions: returns all incoming substitute player IDs."""
    previous = ["P1", "P2", "P3", "P4", "P5"]
    confirmed = ["P1", "SubMid", "P3", "P4", "SubSupport"]

    has_sub, subs = detect_lineup_substitution(previous, confirmed)
    assert has_sub is True
    assert subs == ["SubMid", "SubSupport"]


def test_detect_lineup_substitution_dict_rosters():
    """Test detect_lineup_substitution with dictionary player objects."""
    previous = [
        {"role": "TOP", "player_id": "101", "player_name": "Kiin"},
        {"role": "JUNGLE", "player_id": "102", "player_name": "Canyon"},
        {"role": "MID", "player_id": "103", "player_name": "Chovy"},
        {"role": "ADC", "player_id": "104", "player_name": "Peyz"},
        {"role": "SUPPORT", "player_id": "105", "player_name": "Lehends"},
    ]
    confirmed = [
        {"role": "TOP", "player_id": "101", "player_name": "Kiin"},
        {"role": "JUNGLE", "player_id": "102", "player_name": "Canyon"},
        {"role": "MID", "player_id": "103", "player_name": "Chovy"},
        {"role": "ADC", "player_id": "999", "player_name": "Ruler"},
        {"role": "SUPPORT", "player_id": "105", "player_name": "Lehends"},
    ]

    has_sub, subs = detect_lineup_substitution(previous, confirmed)
    assert has_sub is True
    assert subs == ["999"]


def test_detect_lineup_substitution_empty_roster():
    """Test empty roster handling."""
    has_sub, subs = detect_lineup_substitution([], [])
    assert has_sub is False
    assert subs == []


# ============================================================================
# 2. Timing window tests
# ============================================================================

def test_timing_window_valid_range():
    """Test timing window: checks valid within [start - 45m, start] window."""
    start_dt = datetime(2026, 9, 16, 18, 0, 0, tzinfo=UTC)

    # 45 minutes before start (exact boundary)
    valid_45m, reason_45m = is_within_lineup_window(start_dt, start_dt - timedelta(minutes=45))
    assert valid_45m is True
    assert reason_45m == "valid_window"

    # 30 minutes before start (typical release time)
    valid_30m, reason_30m = is_within_lineup_window(start_dt, start_dt - timedelta(minutes=30))
    assert valid_30m is True
    assert reason_30m == "valid_window"

    # 10 minutes before start
    valid_10m, reason_10m = is_within_lineup_window(start_dt, start_dt - timedelta(minutes=10))
    assert valid_10m is True
    assert reason_10m == "valid_window"

    # At match start (0 minutes)
    valid_0m, reason_0m = is_within_lineup_window(start_dt, start_dt)
    assert valid_0m is True
    assert reason_0m == "valid_window"

    # 5 minutes after start (within 15m post-start grace period)
    valid_post, reason_post = is_within_lineup_window(start_dt, start_dt + timedelta(minutes=5))
    assert valid_post is True
    assert reason_post == "valid_window"


def test_timing_window_too_early_ignored():
    """Test timing window: ignores if > 2h (or > 45m) before match."""
    start_dt = datetime(2026, 9, 16, 18, 0, 0, tzinfo=UTC)

    # 2 hours before match start (120 minutes) -> MUST be ignored / outside window
    valid_2h, reason_2h = is_within_lineup_window(start_dt, start_dt - timedelta(hours=2))
    assert valid_2h is False
    assert "outside_window_too_early" in reason_2h
    assert "120.0m" in reason_2h

    # 60 minutes before match start -> outside default 45m window
    valid_60m, reason_60m = is_within_lineup_window(start_dt, start_dt - timedelta(minutes=60))
    assert valid_60m is False
    assert "outside_window_too_early" in reason_60m

    # Check via check_confirmed_lineup 2 hours before match
    result = check_confirmed_lineup(
        match_id=1,
        match_start_at=start_dt.isoformat(),
        canonical_match={"team_a_name": "T1", "team_b_name": "Gen.G"},
        current_time=start_dt - timedelta(hours=2),
    )
    assert result["is_confirmed"] is False
    assert result["window_valid"] is False
    assert result["status"] == "outside_window"


def test_timing_window_past_match():
    """Test timing window: rejects if match started long ago (> 15m post start)."""
    start_dt = datetime(2026, 9, 16, 18, 0, 0, tzinfo=UTC)

    valid_late, reason_late = is_within_lineup_window(start_dt, start_dt + timedelta(minutes=30))
    assert valid_late is False
    assert "outside_window_past_match" in reason_late

    result = check_confirmed_lineup(
        match_id=1,
        match_start_at=start_dt.isoformat(),
        current_time=start_dt + timedelta(minutes=45),
    )
    assert result["is_confirmed"] is False
    assert result["window_valid"] is False
    assert result["status"] == "past_match"


# ============================================================================
# 3. check_confirmed_lineup & ConfirmedLineupScraper tests
# ============================================================================

def test_check_confirmed_lineup_within_window_success():
    """Test check_confirmed_lineup returns confirmed when 5-player rosters are available."""
    start_dt = datetime(2026, 9, 16, 18, 0, 0, tzinfo=UTC)
    now_dt = start_dt - timedelta(minutes=30)

    canonical_match = {
        "id": 42,
        "team_a_name": "T1",
        "team_b_name": "Gen.G",
        "start_time_normalized": start_dt.isoformat(),
        "confirmed_roster_a": ["Faker", "Zeus", "Oner", "Gumayusi", "Keria"],
        "confirmed_roster_b": ["Chovy", "Kiin", "Canyon", "Peyz", "Lehends"],
        "previous_roster_a": ["Faker", "Zeus", "Oner", "Gumayusi", "Keria"],
        "previous_roster_b": ["Chovy", "Kiin", "Canyon", "Peyz", "Lehends"],
    }

    result = check_confirmed_lineup(
        match_id=42,
        match_start_at=start_dt.isoformat(),
        canonical_match=canonical_match,
        current_time=now_dt,
    )

    assert result["is_confirmed"] is True
    assert result["window_valid"] is True
    assert result["status"] == "confirmed"
    assert result["substitutions_detected"] is False
    assert result["substituted_player_ids"] == []


def test_check_confirmed_lineup_with_substitution():
    """Test check_confirmed_lineup detects substitution within valid window."""
    start_dt = datetime(2026, 9, 16, 18, 0, 0, tzinfo=UTC)
    now_dt = start_dt - timedelta(minutes=30)

    canonical_match = {
        "id": 100,
        "team_a_name": "T1",
        "team_b_name": "Gen.G",
        "start_time_normalized": start_dt.isoformat(),
        "confirmed_roster_a": ["Faker", "Doran", "Oner", "Gumayusi", "Keria"],  # Doran in for Zeus
        "confirmed_roster_b": ["Chovy", "Kiin", "Canyon", "Peyz", "Lehends"],
        "previous_roster_a": ["Faker", "Zeus", "Oner", "Gumayusi", "Keria"],
        "previous_roster_b": ["Chovy", "Kiin", "Canyon", "Peyz", "Lehends"],
    }

    result = check_confirmed_lineup(
        match_id=100,
        canonical_match=canonical_match,
        current_time=now_dt,
    )

    assert result["is_confirmed"] is True
    assert result["window_valid"] is True
    assert result["substitutions_detected"] is True
    assert result["substituted_player_ids"] == ["Doran"]
    assert result["substitutions"]["team_a"]["substituted_players"] == ["Doran"]
    assert result["substitutions"]["team_b"]["has_sub"] is False


def test_check_confirmed_lineup_incomplete_roster():
    """Test check_confirmed_lineup fails when roster has fewer than 5 players."""
    start_dt = datetime(2026, 9, 16, 18, 0, 0, tzinfo=UTC)
    now_dt = start_dt - timedelta(minutes=25)

    canonical_match = {
        "id": 101,
        "team_a_name": "T1",
        "team_b_name": "Gen.G",
        "start_time_normalized": start_dt.isoformat(),
        "confirmed_roster_a": ["Faker", "Zeus"],  # Only 2 players
        "confirmed_roster_b": ["Chovy", "Kiin", "Canyon", "Peyz", "Lehends"],
    }

    result = check_confirmed_lineup(
        match_id=101,
        canonical_match=canonical_match,
        current_time=now_dt,
    )

    assert result["is_confirmed"] is False
    assert result["window_valid"] is True
    assert result["status"] == "incomplete_roster"


def test_confirmed_lineup_scraper_class():
    """Test ConfirmedLineupScraper wrapper class."""
    scraper = ConfirmedLineupScraper(window_minutes=45)
    start_dt = datetime(2026, 9, 16, 18, 0, 0, tzinfo=UTC)

    match = {
        "id": 55,
        "start_time_normalized": start_dt.isoformat(),
        "confirmed_roster_a": ["A", "B", "C", "D", "E"],
        "confirmed_roster_b": ["V", "W", "X", "Y", "Z"],
    }

    # Within window
    res_in = scraper.check_match(match, current_time=start_dt - timedelta(minutes=20))
    assert res_in["is_confirmed"] is True

    # 3 hours prior
    res_early = scraper.check_match(match, current_time=start_dt - timedelta(hours=3))
    assert res_early["is_confirmed"] is False
    assert res_early["status"] == "outside_window"


# ============================================================================
# 4. upcoming_inference_service integration tests
# ============================================================================

def test_build_features_for_match_is_lineup_confirmed():
    """Test build_features_for_match supports is_lineup_confirmed flag."""
    match = {
        "id": 99,
        "team_a_name": "T1",
        "team_b_name": "Gen.G",
        "start_time_normalized": "2026-09-16T18:00:00+00:00",
        "best_of": 3,
        "league": "LCK",
    }

    # Mock dependencies inside build_features_for_match to test feature preparation
    with patch("betting_app.services.upcoming_inference_service.load_team_ratings") as mock_ratings, \
         patch("betting_app.services.upcoming_inference_service.load_w20") as mock_w20, \
         patch("betting_app.services.upcoming_inference_service.load_last_roster") as mock_roster, \
         patch("betting_app.services.upcoming_inference_service.load_roster_player_ratings") as mock_player_ratings, \
         patch("betting_app.services.upcoming_inference_service.rating_probabilities") as mock_probs, \
         patch("betting_app.services.upcoming_inference_service.player_rating_probabilities") as mock_p_probs, \
         patch("betting_app.services.upcoming_inference_service._exp078_snapshot_from_features"):

        mock_ratings.return_value = {"elo": {}, "gl": {}, "ts": {}, "os": {}, "pl": {}, "tm": {}}
        mock_w20.return_value = {"win_rate": 0.6}
        mock_roster.return_value = {
            "players": [{"player_id": f"p{i}", "role": r} for i, r in enumerate(["TOP", "JUNGLE", "MID", "ADC", "SUPPORT"])]
        }
        mock_player_ratings.return_value = {"elo": {}, "gl": {}, "ts": {}, "os": {}, "pl": {}, "tm": {}}
        mock_probs.return_value = {"consensus": 0.55}
        mock_p_probs.return_value = {"consensus": 0.55}

        # 1. Without confirmed lineup
        res_unconfirmed = build_features_for_match(
            match,
            feature_version="exp078-v1",
            ratings_version="ratings-v2",
            w20_version="w20-v1",
            persist=False,
            is_lineup_confirmed=False,
        )
        assert res_unconfirmed["features"]["is_lineup_confirmed"] is False
        assert res_unconfirmed["features"]["player_ratings"]["roster_source"] == "current_team_roster"

        # 2. With confirmed lineup
        res_confirmed = build_features_for_match(
            match,
            feature_version="exp078-v1",
            ratings_version="ratings-v2",
            w20_version="w20-v1",
            persist=False,
            is_lineup_confirmed=True,
        )
        assert res_confirmed["features"]["is_lineup_confirmed"] is True
        assert res_confirmed["features"]["player_ratings"]["roster_source"] == "confirmed_lineup"


def test_process_confirmed_lineup_update_no_change():
    """Test process_confirmed_lineup_update: same starters -> no re-inference."""
    start_dt = datetime(2026, 9, 16, 18, 0, 0, tzinfo=UTC)
    now_dt = start_dt - timedelta(minutes=35)

    starters_a = ["Faker", "Zeus", "Oner", "Gumayusi", "Keria"]
    starters_b = ["Chovy", "Kiin", "Canyon", "Peyz", "Lehends"]

    match = {
        "id": 201,
        "team_a_name": "T1",
        "team_b_name": "Gen.G",
        "start_time_normalized": start_dt.isoformat(),
        "previous_roster_a": starters_a,
        "previous_roster_b": starters_b,
        "confirmed_roster_a": starters_a,  # Same starters
        "confirmed_roster_b": starters_b,  # Same starters
    }

    with patch("betting_app.services.upcoming_inference_service.build_features_for_match") as mock_build:
        mock_build.return_value = {
            "status": "ready_player",
            "features": {"is_lineup_confirmed": True, "canonical_match_id": 201},
        }

        result = process_confirmed_lineup_update(
            match,
            current_time=now_dt,
        )

        assert result["window_valid"] is True
        assert result["is_lineup_confirmed"] is True
        assert result["substitution_detected"] is False
        assert result["re_inference_triggered"] is False
        assert result["status"] == "confirmed_no_change"
        assert result["substituted_players"] == {"team_a": [], "team_b": []}


def test_process_confirmed_lineup_update_substitution_forces_reinference():
    """Test process_confirmed_lineup_update: 1 sub -> substitution detected, returns substituted player IDs & forces re-inference."""
    start_dt = datetime(2026, 9, 16, 18, 0, 0, tzinfo=UTC)
    now_dt = start_dt - timedelta(minutes=30)

    baseline_a = ["Faker", "Zeus", "Oner", "Gumayusi", "Keria"]
    confirmed_a = ["Faker", "Doran", "Oner", "Gumayusi", "Keria"]  # 1 sub (Doran for Zeus)
    starters_b = ["Chovy", "Kiin", "Canyon", "Peyz", "Lehends"]

    match = {
        "id": 202,
        "team_a_name": "T1",
        "team_b_name": "Gen.G",
        "start_time_normalized": start_dt.isoformat(),
        "previous_roster_a": baseline_a,
        "previous_roster_b": starters_b,
        "confirmed_roster_a": confirmed_a,
        "confirmed_roster_b": starters_b,
    }

    with patch("betting_app.services.upcoming_inference_service.build_features_for_match") as mock_build, \
         patch("betting_app.services.upcoming_inference_service.predict_probability_from_features") as mock_predict, \
         patch("betting_app.services.upcoming_inference_service.transaction"):

        mock_build.return_value = {
            "status": "ready_player",
            "features": {"canonical_match_id": 202, "is_lineup_confirmed": True},
            "data_cutoff_at": "2026-09-16T17:00:00Z",
        }
        mock_predict.return_value = (0.58, {"note": "re-inferred with Doran"})

        result = process_confirmed_lineup_update(
            match,
            current_time=now_dt,
        )

        assert result["window_valid"] is True
        assert result["is_lineup_confirmed"] is True
        assert result["substitution_detected"] is True
        assert result["re_inference_triggered"] is True
        assert result["status"] == "re_inferred"
        assert result["substituted_players"]["team_a"] == ["Doran"]
        assert result["substituted_player_ids"] == ["Doran"]
        assert result["prob_a"] == 0.58
        assert result["prob_b"] == pytest.approx(0.42)
        assert result["diagnostics"]["lineup_substitution_detected"] is True


def test_process_confirmed_lineup_update_too_early_ignored():
    """Test process_confirmed_lineup_update ignores match > 2h before start."""
    start_dt = datetime(2026, 9, 16, 18, 0, 0, tzinfo=UTC)
    now_dt = start_dt - timedelta(hours=2, minutes=15)  # 2h15m before match

    match = {
        "id": 203,
        "team_a_name": "T1",
        "team_b_name": "Gen.G",
        "start_time_normalized": start_dt.isoformat(),
        "confirmed_roster_a": ["Faker", "Doran", "Oner", "Gumayusi", "Keria"],
    }

    result = process_confirmed_lineup_update(
        match,
        current_time=now_dt,
    )

    assert result["window_valid"] is False
    assert result["status"] == "outside_window"
    assert result["re_inference_triggered"] is False
    assert result["substitution_detected"] is False


def test_process_confirmed_lineup_update_updates_db_roster(sqlite_session):
    """Test substitution updates team_current_roster_players starting five in database."""
    start_dt = datetime(2026, 9, 16, 18, 0, 0, tzinfo=UTC)
    now_dt = start_dt - timedelta(minutes=30)

    # Insert previous baseline roster
    old_players = [
        ("T1", "t1", "Zeus", "Zeus", "TOP"),
        ("T1", "t1", "Oner", "Oner", "JUNGLE"),
        ("T1", "t1", "Faker", "Faker", "MID"),
        ("T1", "t1", "Gumayusi", "Gumayusi", "ADC"),
        ("T1", "t1", "Keria", "Keria", "SUPPORT"),
    ]
    for team, norm, pid, pname, role in old_players:
        sqlite_session.execute(
            text("""
            INSERT INTO team_current_roster_players (team_name, normalized_team_name, player_id, player_name, role)
            VALUES (:team, :norm, :pid, :pname, :role)
            """),
            {"team": team, "norm": norm, "pid": pid, "pname": pname, "role": role},
        )
    sqlite_session.commit()

    # Confirmed lineup with Doran in TOP
    confirmed_t1 = [
        {"player_id": "Doran", "player_name": "Doran", "role": "TOP"},
        {"player_id": "Oner", "player_name": "Oner", "role": "JUNGLE"},
        {"player_id": "Faker", "player_name": "Faker", "role": "MID"},
        {"player_id": "Gumayusi", "player_name": "Gumayusi", "role": "ADC"},
        {"player_id": "Keria", "player_name": "Keria", "role": "SUPPORT"},
    ]

    match = {
        "id": 204,
        "team_a_name": "T1",
        "team_b_name": "Gen.G",
        "start_time_normalized": start_dt.isoformat(),
        "previous_roster_a": ["Zeus", "Oner", "Faker", "Gumayusi", "Keria"],
        "confirmed_roster_a": confirmed_t1,
    }

    with patch("betting_app.services.upcoming_inference_service.build_features_for_match") as mock_build, \
         patch("betting_app.services.upcoming_inference_service.predict_probability_from_features") as mock_predict, \
         patch("betting_app.services.upcoming_inference_service.transaction"):

        mock_build.return_value = {"features": {}, "data_cutoff_at": None}
        mock_predict.return_value = (0.55, {})

        result = process_confirmed_lineup_update(
            match,
            current_time=now_dt,
            session=sqlite_session,
        )

        assert result["substitution_detected"] is True
        assert result["re_inference_triggered"] is True
        assert result["substituted_player_ids"] == ["Doran"]

    # Verify that the DB was updated: TOP player for T1 is now Doran
    row = sqlite_session.execute(
        text("SELECT player_id, player_name FROM team_current_roster_players WHERE normalized_team_name = 't1' AND role = 'TOP'")
    ).fetchone()
    assert row is not None
    assert row[0] == "Doran"
    assert row[1] == "Doran"
