"""Shared fixtures: every test gets a fresh in-memory SQLite DB."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models import Base

TOKEN = "changeme"  # default Settings token; tests send it explicitly


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # one shared in-memory DB across connections
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, expire_on_commit=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    # The app lifespan runs Alembic against the real configured (on-disk) engine,
    # which is irrelevant here: db_session already built the schema on an isolated
    # in-memory engine and get_db is overridden to use it. No-op the migration so
    # tests never touch a real database file.
    with patch("app.main.run_migrations"):
        with TestClient(app) as c:
            yield c
    app.dependency_overrides.clear()


def make_junit(cases: list[tuple[str, str]], suite: str = "unit") -> bytes:
    """Build a minimal JUnit XML report.

    `cases` is a list of (test_name, status) where status is
    passed | failed | error | skipped.
    """
    inner = ""
    for name, status in cases:
        body = ""
        if status == "failed":
            body = '<failure message="assert 1 == 2">trace</failure>'
        elif status == "error":
            body = '<error message="boom">trace</error>'
        elif status == "skipped":
            body = '<skipped message="not on windows"/>'
        inner += f'<testcase classname="tests.test_mod" name="{name}" time="0.01">{body}</testcase>'
    xml = f'<testsuites><testsuite name="{suite}" tests="{len(cases)}">{inner}</testsuite></testsuites>'
    return xml.encode()
