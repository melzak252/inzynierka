"""Tests for /api/bets and /api/wallets endpoints."""

from fastapi.testclient import TestClient
from betting_app.core.database import get_db_path
import sqlite3


def _seed_wallet() -> int:
    """Create a test wallet tied to the 'manual' bookmaker (seeded in schema). Return wallet ID."""
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # 'manual' bookmaker is seeded first → id=1
    cur = conn.execute(
        "INSERT INTO bookmaker_accounts (bookmaker_id, account_name, currency, opening_balance, current_balance) "
        "VALUES (1, 'test-wallet', 'PLN', 1000.0, 1000.0)"
    )
    conn.commit()
    wid = cur.lastrowid
    conn.close()
    return wid


class TestWallets:
    def test_list_empty(self, client: TestClient):
        resp = client.get("/wallets")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create_and_list(self, client: TestClient):
        resp = client.post(
            "/wallets",
            params={"bookmaker_id": 1, "account_name": "test", "opening_balance": 500},
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["current_balance"] == 500.0
        assert data["account_name"] == "test"

        resp = client.get("/wallets")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


class TestBets:
    def test_list_empty(self, client: TestClient):
        resp = client.get("/bets")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_place_and_settle_win(self, client: TestClient):
        wid = _seed_wallet()
        resp = client.post(
            "/bets",
            json={
                "bookmaker_account_id": wid,
                "team_a": "TeamA",
                "team_b": "TeamB",
                "side": "a",
                "stake": 100,
                "odds": 2.0,
            },
        )
        assert resp.status_code == 201, resp.text
        bet = resp.json()
        assert bet["status"] == "open"
        assert bet["stake"] == 100.0

        # Settle as won
        resp = client.post(f"/bets/{bet['id']}/settle", json={"result": "won"})
        assert resp.status_code == 200
        settled = resp.json()
        assert settled["status"] == "won"

        # profit = 100 * 2.0 * 0.88 - 100 = 76
        assert settled["profit"] == 76.0

        # Check wallet updated: 1000 - 100 + 176 = 1076
        resp = client.get("/wallets")
        wallets = resp.json()
        assert wallets[0]["current_balance"] == 1076.0

    def test_place_and_settle_loss(self, client: TestClient):
        wid = _seed_wallet()
        resp = client.post(
            "/bets",
            json={
                "bookmaker_account_id": wid,
                "side": "b",
                "stake": 50,
                "odds": 3.0,
            },
        )
        assert resp.status_code == 201, resp.text
        bet = resp.json()
        resp = client.post(f"/bets/{bet['id']}/settle", json={"result": "lost"})
        assert resp.status_code == 200
        settled = resp.json()
        assert settled["status"] == "lost"
        assert settled["profit"] == -50.0

    def test_insufficient_balance(self, client: TestClient):
        wid = _seed_wallet()
        resp = client.post(
            "/bets",
            json={
                "bookmaker_account_id": wid,
                "side": "a",
                "stake": 9999,
                "odds": 2.0,
            },
        )
        assert resp.status_code == 400

    def test_wallet_not_found(self, client: TestClient):
        resp = client.post(
            "/bets",
            json={
                "bookmaker_account_id": 999,
                "side": "a",
                "stake": 10,
                "odds": 2.0,
            },
        )
        assert resp.status_code == 404
