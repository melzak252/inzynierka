"""Tests for /api/matches endpoints."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlite3 import Connection

from betting_app.core.database import init_db


def _ensure_bookmaker(db: Connection) -> int:
    """Return the 'manual' bookmaker id (seeded by schema)."""
    row = db.execute("SELECT id FROM bookmakers WHERE name='manual'").fetchone()
    return int(row["id"]) if row else 1


def _seed_single_match(db: Connection) -> int:
    """Insert one canonical match + one odds_snapshot, return canonical ID."""
    bm_id = _ensure_bookmaker(db)
    db.execute(
        """
        INSERT INTO canonical_matches (id, canonical_key, team_a_name, team_b_name,
                                       normalized_team_a, normalized_team_b,
                                       start_time_normalized, league, status)
        VALUES (1, 'test-key-1', 'TeamA', 'TeamB',
                'team-a', 'team-b', '2026-12-31T12:00:00+00:00', 'TEST', 'upcoming')
        """
    )
    now = datetime.now(UTC).isoformat(timespec="seconds")
    db.execute(
        """
        INSERT INTO odds_snapshots (bookmaker_id, market_type, is_live, canonical_match_id,
                                    raw_team_a, raw_team_b, odds_a, odds_b, scraped_at, source_url)
        VALUES (?, 'match_winner', 0, 1, 'TeamA', 'TeamB', 2.0, 1.8, ?, 'https://x.pl/')
        """,
        (bm_id, now),
    )
    db.commit()
    return 1


class TestMatchList:
    def test_empty_returns_zero(self, client: TestClient):
        resp = client.get("/matches")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["matches"] == []

    def test_single_seeded(self, client: TestClient):
        from betting_app.core.database import get_db_path
        import sqlite3
        conn = sqlite3.connect(get_db_path())
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        _seed_single_match(conn)
        conn.close()

        resp = client.get("/matches?min_books=1&days_ahead=365")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        item = data["matches"][0]
        assert item["match"] == "TeamA vs TeamB"
        assert item["bookmaker_count"] == 1
        assert item["best_odds_a"] == 2.0
        assert item["best_odds_b"] == 1.8

    def test_min_books_filter(self, client: TestClient):
        from betting_app.core.database import get_db_path
        import sqlite3
        conn = sqlite3.connect(get_db_path())
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        _seed_single_match(conn)
        conn.close()

        resp = client.get("/matches?min_books=2&days_ahead=365")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0


class TestMatchDetail:
    def test_not_found(self, client: TestClient):
        resp = client.get("/matches/999")
        assert resp.status_code == 404

    def test_found(self, client: TestClient):
        from betting_app.core.database import get_db_path
        import sqlite3
        conn = sqlite3.connect(get_db_path())
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        _seed_single_match(conn)
        conn.close()

        resp = client.get("/matches/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["canonical_match_id"] == 1
        assert data["team_a_name"] == "TeamA"
        assert len(data["odds"]) == 1
        assert data["odds"][0]["bookmaker"] == "manual"


class TestOddsHistory:
    def test_history_not_found(self, client: TestClient):
        resp = client.get("/matches/999/odds-history")
        assert resp.status_code == 404

    def test_history_returns_rows(self, client: TestClient):
        from betting_app.core.database import get_db_path
        import sqlite3
        conn = sqlite3.connect(get_db_path())
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        _seed_single_match(conn)
        conn.close()

        resp = client.get("/matches/1/odds-history")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
