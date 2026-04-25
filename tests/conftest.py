import os
import tempfile

os.environ["RATE_LIMIT_ENABLED"] = "false"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.dependencies import get_db
from app.main import app
from app.storage import LocalStorage

# In-memory SQLite for tests
TEST_DATABASE_URL = "sqlite://"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_db():
    """Create tables before each test, drop after."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def isolated_upload_storage(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        test_storage = LocalStorage(tmpdir)
        monkeypatch.setattr("app.storage.storage", test_storage)
        monkeypatch.setattr("app.routers.papers.storage", test_storage)
        monkeypatch.setattr("app.tasks.review_tasks.storage", test_storage)
        yield


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def registered_user(client):
    """Register a user and return the user data."""
    resp = client.post("/api/auth/register", json={
        "username": "testuser",
        "password": "testpass123",
        "invite_code": "huiming",
    })
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture
def auth_headers(client, registered_user):
    """Login and return authorization headers."""
    resp = client.post("/api/auth/login", json={
        "username": "testuser",
        "password": "testpass123",
    })
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def second_user_headers(client):
    """Register a second user and return auth headers."""
    client.post("/api/auth/register", json={
        "username": "user2",
        "password": "testpass123",
        "invite_code": "huiming",
    })
    resp = client.post("/api/auth/login", json={
        "username": "user2",
        "password": "testpass123",
    })
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def sample_paper(client, auth_headers):
    """Create a sample paper and return its data."""
    resp = client.post("/api/papers", json={
        "title": "Test Paper on AI",
        "abstract": "This paper explores the impact of AI on society.",
    }, headers=auth_headers)
    assert resp.status_code == 201
    return resp.json()
