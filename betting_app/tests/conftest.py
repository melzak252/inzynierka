"""pytest configuration: each test gets a fresh temp SQLite database."""

from __future__ import annotations

import os
import tempfile
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from betting_app.core.database import init_db
from betting_app.api.main import app


@pytest.fixture(scope="function")
def client() -> Generator[TestClient, None, None]:
    """Each test creates a fresh temp DB, re-inits schema, then starts TestClient."""
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
    tmp.close()
    path = tmp.name
    os.environ["BETTING_APP_DB"] = path
    init_db()  # create schema before TestClient lifespan
    with TestClient(app) as c:
        yield c
    try:
        os.unlink(path)
    except OSError:
        pass
    if "BETTING_APP_DB" in os.environ:
        del os.environ["BETTING_APP_DB"]
