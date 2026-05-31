"""Tests for /api/predictions endpoint."""

from fastapi.testclient import TestClient


class TestPredictions:
    def test_empty_returns_zero(self, client: TestClient):
        resp = client.get("/predictions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["signals"] == []
