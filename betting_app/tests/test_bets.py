"""Tests for /api/bets and /api/wallets endpoints."""

from fastapi.testclient import TestClient
from sqlalchemy import text

from betting_app.core.db import get_session


def _seed_wallet(balance: float = 1000.0) -> int:
    """Create a test wallet, return its ID."""
    session = get_session()
    wid = session.execute(
        text("""
        INSERT INTO bookmaker_accounts (bookmaker_id, account_name, currency, opening_balance, current_balance, is_active, created_at, updated_at)
        VALUES (1, 'test-wallet', 'PLN', :bal, :bal, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        RETURNING id
        """),
        {"bal": balance},
    ).scalar_one()
    session.commit()
    session.close()
    return int(wid)


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
        assert data["id"] > 0

        resp = client.get("/wallets")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_create_wallet_negative_opening_balance(self, client: TestClient):
        resp = client.post(
            "/wallets",
            params={"bookmaker_id": 1, "account_name": "neg", "opening_balance": -50},
        )
        assert resp.status_code == 400

    def test_wallet_non_negative_balance_constraint(self, client: TestClient):
        from sqlalchemy.exc import IntegrityError
        session = get_session()
        try:
            import pytest
            with pytest.raises(IntegrityError):
                session.execute(
                    text("""
                    INSERT INTO bookmaker_accounts (bookmaker_id, account_name, currency, opening_balance, current_balance, is_active, created_at, updated_at)
                    VALUES (1, 'bad-wallet', 'PLN', -10.0, -10.0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """)
                )
                session.commit()
        finally:
            session.rollback()
            session.close()

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

        resp = client.post(f"/bets/{bet['id']}/settle", json={"result": "won"})
        assert resp.status_code == 200
        settled = resp.json()
        assert settled["status"] == "won"
        assert settled["profit"] == 76.0

        resp = client.get("/wallets")
        wallets = resp.json()
        assert wallets[0]["current_balance"] == 1076.0

    def test_settlement_is_idempotent(self, client: TestClient):
        wid = _seed_wallet()
        placed = client.post(
            "/bets",
            json={
                "bookmaker_account_id": wid,
                "side": "a",
                "stake": 100,
                "odds": 2.0,
            },
        ).json()
        assert client.post(
            f"/bets/{placed['id']}/settle",
            json={"result": "won"},
        ).status_code == 200
        assert client.post(
            f"/bets/{placed['id']}/settle",
            json={"result": "won"},
        ).status_code == 400
        assert client.get("/wallets").json()[0]["current_balance"] == 1076.0
        session = get_session()
        try:
            assert session.execute(
                text(
                    "SELECT COUNT(*) FROM bookmaker_wallet_transactions "
                    "WHERE bet_id = :bet_id"
                ),
                {"bet_id": placed["id"]},
            ).scalar_one() == 2
        finally:
            session.close()

    def test_place_and_settle_loss(self, client: TestClient):
        wid = _seed_wallet()
        resp = client.post(
            "/bets",
            json={"bookmaker_account_id": wid, "side": "b", "stake": 50, "odds": 3.0},
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
            json={"bookmaker_account_id": wid, "side": "a", "stake": 9999, "odds": 2.0},
        )
        assert resp.status_code == 400
        session = get_session()
        try:
            assert session.execute(text("SELECT COUNT(*) FROM bets")).scalar_one() == 0
            assert session.execute(
                text("SELECT COUNT(*) FROM bookmaker_wallet_transactions")
            ).scalar_one() == 0
            assert session.execute(
                text("SELECT current_balance FROM bookmaker_accounts WHERE id = :id"),
                {"id": wid},
            ).scalar_one() == 1000.0
        finally:
            session.close()

    def test_wallet_not_found(self, client: TestClient):
        resp = client.post(
            "/bets",
            json={"bookmaker_account_id": 999, "side": "a", "stake": 10, "odds": 2.0},
        )
        assert resp.status_code == 404

    def test_settle_loss_is_idempotent(self, client: TestClient):
        wid = _seed_wallet()
        resp = client.post(
            "/bets",
            json={"bookmaker_account_id": wid, "side": "b", "stake": 50, "odds": 3.0},
        )
        assert resp.status_code == 201
        bet = resp.json()
        # First settle as lost
        resp1 = client.post(f"/bets/{bet['id']}/settle", json={"result": "lost"})
        assert resp1.status_code == 200
        assert resp1.json()["status"] == "lost"
        assert resp1.json()["profit"] == -50.0

        # Second settle must fail
        resp2 = client.post(f"/bets/{bet['id']}/settle", json={"result": "lost"})
        assert resp2.status_code == 400
        assert "already settled" in resp2.json()["detail"].lower()

        # Third settle as won must also fail
        resp3 = client.post(f"/bets/{bet['id']}/settle", json={"result": "won"})
        assert resp3.status_code == 400

        # Balance remains deducted only once
        wallets = client.get("/wallets").json()
        assert wallets[0]["current_balance"] == 950.0

    def test_settle_void_refunds_stake(self, client: TestClient):
        wid = _seed_wallet()
        resp = client.post(
            "/bets",
            json={"bookmaker_account_id": wid, "side": "a", "stake": 150, "odds": 2.5},
        )
        assert resp.status_code == 201
        bet = resp.json()
        assert client.get("/wallets").json()[0]["current_balance"] == 850.0

        # Settle void
        resp_void = client.post(f"/bets/{bet['id']}/settle", json={"result": "void"})
        assert resp_void.status_code == 200
        settled = resp_void.json()
        assert settled["status"] == "void"
        assert settled["profit"] == 0.0

        # Wallet must be refunded
        assert client.get("/wallets").json()[0]["current_balance"] == 1000.0

        # Idempotency check: settling again must be rejected
        assert client.post(f"/bets/{bet['id']}/settle", json={"result": "void"}).status_code == 400
        assert client.get("/wallets").json()[0]["current_balance"] == 1000.0

    def test_atomicity_on_bet_placement_error(self, client: TestClient):
        wid = _seed_wallet()
        # Invalid side ('c' not allowed by schema)
        resp = client.post(
            "/bets",
            json={"bookmaker_account_id": wid, "side": "invalid", "stake": 100, "odds": 2.0},
        )
        assert resp.status_code == 422
        # Verify wallet balance unchanged, no bet, no transaction
        assert client.get("/wallets").json()[0]["current_balance"] == 1000.0
        session = get_session()
        try:
            assert session.execute(text("SELECT COUNT(*) FROM bets")).scalar_one() == 0
            assert session.execute(
                text("SELECT COUNT(*) FROM bookmaker_wallet_transactions")
            ).scalar_one() == 0
        finally:
            session.close()

    def test_cannot_overdraw_wallet(self, client: TestClient):
        wid = _seed_wallet(balance=100.0)
        # Place bet 1: 60 PLN -> balance becomes 40 PLN
        resp1 = client.post(
            "/bets",
            json={"bookmaker_account_id": wid, "side": "a", "stake": 60, "odds": 2.0},
        )
        assert resp1.status_code == 201
        assert client.get("/wallets").json()[0]["current_balance"] == 40.0

        # Place bet 2: 60 PLN -> insufficient balance (needs 60, only 40 left)
        resp2 = client.post(
            "/bets",
            json={"bookmaker_account_id": wid, "side": "b", "stake": 60, "odds": 2.0},
        )
        assert resp2.status_code == 400
        # Verify wallet remains at 40 PLN, only 1 bet placed
        assert client.get("/wallets").json()[0]["current_balance"] == 40.0
        session = get_session()
        try:
            assert session.execute(text("SELECT COUNT(*) FROM bets")).scalar_one() == 1
            assert session.execute(
                text("SELECT COUNT(*) FROM bookmaker_wallet_transactions")
            ).scalar_one() == 1
        finally:
            session.close()

    def test_settle_nonexistent_bet(self, client: TestClient):
        resp = client.post("/bets/99999/settle", json={"result": "won"})
        assert resp.status_code == 404
