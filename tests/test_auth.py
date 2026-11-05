
import pytest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import User
from app.security import hash_password


@pytest.fixture
def client():
    test_engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={
            "check_same_thread": False
        },
        poolclass=StaticPool,
    )

    Base.metadata.create_all(bind=test_engine)

    TestingSession = sessionmaker(
        bind=test_engine,
        expire_on_commit=False,
    )

    def override_get_db():
        with TestingSession() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db

    # Do not enter TestClient as a context manager here:
    # the current app lifespan creates tables on MySQL.
    test_client = TestClient(app)

    try:
        yield test_client, TestingSession
    finally:
        test_client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=test_engine)
        test_engine.dispose()


def test_register_candidate(client):
    http, _ = client

    response = http.post(
        "/auth/register",
        json={
            "full_name": "Test Candidate",
            "email": "test@example.com",
            "password": "StrongPassword123!"
        }
    )

    assert response.status_code == 201
    assert response.json()["role"] == "candidate"
    assert "password_hash" not in response.json()


def test_duplicate_registration(client):
    http, _ = client

    data = {
        "full_name": "Test Candidate",
        "email": "test@example.com",
        "password": "StrongPassword123!"
    }

    first = http.post("/auth/register", json=data)
    second = http.post("/auth/register", json=data)

    assert first.status_code == 201
    assert second.status_code == 409


def test_login_and_protected_route(client):
    http, _ = client

    http.post(
        "/auth/register",
        json={
            "full_name": "Test Candidate",
            "email": "test@example.com",
            "password": "StrongPassword123!"
        }
    )

    login = http.post(
        "/auth/login",
        data={
            "username": "test@example.com",
            "password": "StrongPassword123!"
        }
    )

    assert login.status_code == 200

    token = login.json()["access_token"]

    profile = http.get(
        "/users/me",
        headers={
            "Authorization": f"Bearer {token}"
        }
    )

    assert profile.status_code == 200
    assert profile.json()["email"] == "test@example.com"


def test_candidate_cannot_access_admin(client):
    http, _ = client

    http.post(
        "/auth/register",
        json={
            "full_name": "Test Candidate",
            "email": "test@example.com",
            "password": "StrongPassword123!"
        }
    )

    login = http.post(
        "/auth/login",
        data={
            "username": "test@example.com",
            "password": "StrongPassword123!"
        }
    )

    token = login.json()["access_token"]

    response = http.get(
        "/users/admin/dashboard",
        headers={
            "Authorization": f"Bearer {token}"
        }
    )

    assert response.status_code == 403


def test_admin_can_access_admin_dashboard(client):
    http, TestingSession = client

    with TestingSession() as db:
        admin = User(
            full_name="Test Admin",
            email="admin@example.com",
            password_hash=hash_password("StrongPassword123!"),
            role="admin"
        )

        db.add(admin)
        db.commit()

    login = http.post(
        "/auth/login",
        data={
            "username": "admin@example.com",
            "password": "StrongPassword123!"
        }
    )

    assert login.status_code == 200

    token = login.json()["access_token"]

    response = http.get(
        "/users/admin/dashboard",
        headers={
            "Authorization": f"Bearer {token}"
        }
    )

    assert response.status_code == 200


def test_invalid_login(client):
    http, _ = client

    response = http.post(
        "/auth/login",
        data={
            "username": "unknown@example.com",
            "password": "WrongPassword123!"
        }
    )

    assert response.status_code == 401


def test_missing_token(client):
    http, _ = client

    response = http.get("/users/me")

    assert response.status_code == 401
