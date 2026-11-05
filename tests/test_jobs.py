
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
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(bind=engine)

    TestingSession = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    def override_db():
        with TestingSession() as db:
            yield db

    app.dependency_overrides[get_db] = override_db

    # Avoid triggering the application's MySQL lifespan.
    http = TestClient(app)

    try:
        yield http, TestingSession
    finally:
        http.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def create_user(session_factory, email, role):
    with session_factory() as db:
        user = User(
            full_name="Test User",
            email=email,
            password_hash=hash_password(
                "StrongPassword123!"
            ),
            role=role,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id


def login(http, email):
    response = http.post(
        "/auth/login",
        data={
            "username": email,
            "password": "StrongPassword123!",
        },
    )

    assert response.status_code == 200

    token = response.json()["access_token"]

    return {
        "Authorization": f"Bearer {token}"
    }


def sample_job():
    return {
        "title": "Python Backend Developer",
        "description": (
            "Build REST APIs using Python, "
            "FastAPI and MySQL."
        ),
        "location": "Kolkata",
        "salary_min": 600000,
        "salary_max": 900000,
    }


def test_recruiter_can_create_job(client):
    http, session = client

    create_user(
        session, "recruiter@example.com", "recruiter"
    )

    headers = login(http, "recruiter@example.com")

    response = http.post(
        "/jobs",
        json=sample_job(),
        headers=headers,
    )

    assert response.status_code == 201
    assert response.json()["title"] == "Python Backend Developer"
    assert response.json()["status"] == "open"


def test_candidate_cannot_create_job(client):
    http, session = client

    create_user(
        session, "candidate@example.com", "candidate"
    )

    headers = login(http, "candidate@example.com")

    response = http.post(
        "/jobs",
        json=sample_job(),
        headers=headers,
    )

    assert response.status_code == 403


def test_public_job_search(client):
    http, session = client

    create_user(
        session, "recruiter@example.com", "recruiter"
    )

    headers = login(http, "recruiter@example.com")

    http.post(
        "/jobs",
        json=sample_job(),
        headers=headers,
    )

    response = http.get(
        "/jobs?search=Python&location=Kolkata"
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert len(response.json()["items"]) == 1


def test_invalid_salary_range(client):
    http, session = client

    create_user(
        session, "recruiter@example.com", "recruiter"
    )

    headers = login(http, "recruiter@example.com")

    data = sample_job()
    data["salary_min"] = 1000000
    data["salary_max"] = 500000

    response = http.post(
        "/jobs",
        json=data,
        headers=headers,
    )

    assert response.status_code == 422


def test_recruiter_cannot_modify_others_job(client):
    http, session = client

    create_user(
        session, "first@example.com", "recruiter"
    )
    create_user(
        session, "second@example.com", "recruiter"
    )

    first_headers = login(http, "first@example.com")
    second_headers = login(http, "second@example.com")

    created = http.post(
        "/jobs",
        json=sample_job(),
        headers=first_headers,
    )

    job_id = created.json()["id"]

    response = http.patch(
        f"/jobs/{job_id}",
        json={"title": "Unauthorized Change"},
        headers=second_headers,
    )

    assert response.status_code == 404


def test_close_and_reopen_job(client):
    http, session = client

    create_user(
        session, "recruiter@example.com", "recruiter"
    )

    headers = login(http, "recruiter@example.com")

    created = http.post(
        "/jobs",
        json=sample_job(),
        headers=headers,
    )

    job_id = created.json()["id"]

    closed = http.patch(
        f"/jobs/{job_id}/close",
        headers=headers,
    )

    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"

    public_result = http.get(f"/jobs/{job_id}")
    assert public_result.status_code == 404

    reopened = http.patch(
        f"/jobs/{job_id}/reopen",
        headers=headers,
    )

    assert reopened.status_code == 200
    assert reopened.json()["status"] == "open"


def test_pagination(client):
    http, session = client

    create_user(
        session, "recruiter@example.com", "recruiter"
    )

    headers = login(http, "recruiter@example.com")

    for i in range(5):
        data = sample_job()
        data["title"] = f"Python Developer {i}"

        http.post(
            "/jobs",
            json=data,
            headers=headers,
        )

    response = http.get(
        "/jobs?page=2&page_size=2"
    )

    assert response.status_code == 200
    assert response.json()["total"] == 5
    assert response.json()["total_pages"] == 3
    assert len(response.json()["items"]) == 2


def test_delete_job_without_applications(client):
    http, session = client

    create_user(
        session, "recruiter@example.com", "recruiter"
    )

    headers = login(http, "recruiter@example.com")

    created = http.post(
        "/jobs",
        json=sample_job(),
        headers=headers,
    )

    job_id = created.json()["id"]

    deleted = http.delete(
        f"/jobs/{job_id}",
        headers=headers,
    )

    assert deleted.status_code == 204

    response = http.get(f"/jobs/{job_id}")
    assert response.status_code == 404
