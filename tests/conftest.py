"""Test fixtures: swap Postgres for in-memory SQLite and Redis for fakeredis.

This lets the full test suite run with zero external services (no Docker
needed), while exercising the real application code paths.
"""

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import cache
from app.database import Base, get_db
from app.main import app


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    cache.set_client(fakeredis.FakeRedis(decode_responses=True))

    # Note: we intentionally do NOT enter TestClient as a context manager.
    # Doing so would fire the startup event, which calls create_all against the
    # real Postgres engine. Tables are already created on the SQLite test engine
    # above, so we skip lifespan and drive the app directly.
    c = TestClient(app)
    yield c

    app.dependency_overrides.clear()
    cache.set_client(None)
