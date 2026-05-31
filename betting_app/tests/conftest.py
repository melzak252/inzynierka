"""pytest: fresh temp SQLite DB per test. Sleep between tests to avoid locking."""

from __future__ import annotations

import gc
import os
import tempfile
import time
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from betting_app.models.base import Base
from betting_app.core.db import dispose_engine
from betting_app.api.main import app


@pytest.fixture(scope="function")
def client() -> Generator[TestClient, None, None]:
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
    tmp.close()
    path = tmp.name
    uri = f"sqlite:///{path}?timeout=5000"

    engine = create_engine(uri, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    from sqlalchemy.orm import Session
    with Session(engine) as s:
        s.execute(
            __import__("sqlalchemy").text(
                "INSERT OR IGNORE INTO bookmakers(name, base_url) VALUES "
                "('manual',NULL),('sts','https://www.sts.pl/'),('betclic','https://www.betclic.pl/'),"
                "('superbet','https://superbet.pl/'),('efortuna','https://www.efortuna.pl/'),"
                "('fortuna','https://www.efortuna.pl/'),('betfan','https://betfan.pl/'),"
                "('totalbet','https://totalbet.pl/'),('lebull','https://www.lebull.pl/')"
            )
        )
        s.commit()
    engine.dispose()
    gc.collect()
    time.sleep(0.05)

    os.environ["DATABASE_URL"] = uri
    dispose_engine()

    with TestClient(app) as c:
        yield c

    os.environ.pop("DATABASE_URL", None)
    dispose_engine()
    gc.collect()
    time.sleep(0.05)
    try:
        os.unlink(path)
    except OSError:
        pass
