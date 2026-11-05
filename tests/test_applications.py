
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

    # Do not execute the production MySQL lifespan.
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
            "Develop REST APIs using Python, "
            "FastAPI, SQLAlchemy and MySQL."
        ),
        "location": "Kolkata",
        "salary_min": 600000,
        "salary_max": 900000,
    }


@pytest.fixture
def setup_accounts(client):
    http, session = client

    create_user(
        session,
        "candidate@example.com",
        "candidate",
    )

    create_user(
        session,
        "recruiter@example.com",
        "recruiter",
    )

    candidate_headers = login(
        http, "candidate@example.com"
    )

    recruiter_headers = login(
        http, "recruiter@example.com"
    )

    job_response = http.post(
        "/jobs",
        json=sample_job(),
        headers=recruiter_headers,
    )

    assert job_response.status_code == 201

    return {
        "http": http,
        "session": session,
        "candidate": candidate_headers,
        "recruiter": recruiter_headers,
        "job_id": job_response.json()["id"],
    }


def submit_application(data):
    response = data["http"].post(
        "/applications",
        json={"job_id": data["job_id"]},
        headers=data["candidate"],
    )

    return response


def test_candidate_can_apply(setup_accounts):
    data = setup_accounts

    response = submit_application(data)

    assert response.status_code == 201
    assert response.json()["status"] == "applied"
    assert response.json()["job_id"] == data["job_id"]


def test_duplicate_application_rejected(setup_accounts):
    data = setup_accounts

    first = submit_application(data)
    second = submit_application(data)

    assert first.status_code == 201
    assert second.status_code == 409


def test_candidate_can_track_application(setup_accounts):
    data = setup_accounts

    submit_application(data)

    response = data["http"].get(
        "/applications/me",
        headers=data["candidate"],
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["status"] == "applied"


def test_recruiter_can_view_applicants(setup_accounts):
    data = setup_accounts

    submit_application(data)

    response = data["http"].get(
        f"/applications/job/{data['job_id']}",
        headers=data["recruiter"],
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1


def test_recruiter_can_shortlist(setup_accounts):
    data = setup_accounts

    application = submit_application(data)
    application_id = application.json()["id"]

    response = data["http"].patch(
        f"/applications/{application_id}/shortlist",
        headers=data["recruiter"],
    )

    assert response.status_code == 200
    assert response.json()["status"] == "shortlisted"


def test_recruiter_can_reject(setup_accounts):
    data = setup_accounts

    application = submit_application(data)
    application_id = application.json()["id"]

    response = data["http"].patch(
        f"/applications/{application_id}/reject",
        headers=data["recruiter"],
    )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"


def test_candidate_can_withdraw(setup_accounts):
    data = setup_accounts

    application = submit_application(data)
    application_id = application.json()["id"]

    response = data["http"].patch(
        f"/applications/{application_id}/withdraw",
        headers=data["candidate"],
    )

    assert response.status_code == 200
    assert response.json()["status"] == "withdrawn"


def test_cannot_shortlist_rejected_application(setup_accounts):
    data = setup_accounts

    application = submit_application(data)
    application_id = application.json()["id"]

    rejected = data["http"].patch(
        f"/applications/{application_id}/reject",
        headers=data["recruiter"],
    )

    assert rejected.status_code == 200

    response = data["http"].patch(
        f"/applications/{application_id}/shortlist",
        headers=data["recruiter"],
    )

    assert response.status_code == 409


def test_candidate_cannot_shortlist(setup_accounts):
    data = setup_accounts

    application = submit_application(data)
    application_id = application.json()["id"]

    response = data["http"].patch(
        f"/applications/{application_id}/shortlist",
        headers=data["candidate"],
    )

    assert response.status_code == 403


def test_other_recruiter_cannot_shortlist(setup_accounts):
    data = setup_accounts

    create_user(
        data["session"],
        "other@example.com",
        "recruiter",
    )

    other_headers = login(
        data["http"], "other@example.com"
    )

    application = submit_application(data)
    application_id = application.json()["id"]

    response = data["http"].patch(
        f"/applications/{application_id}/shortlist",
        headers=other_headers,
    )

    assert response.status_code == 404


def test_cannot_apply_to_closed_job(setup_accounts):
    data = setup_accounts

    closed = data["http"].patch(
        f"/jobs/{data['job_id']}/close",
        headers=data["recruiter"],
    )

    assert closed.status_code == 200

    response = submit_application(data)

    assert response.status_code == 404


def test_application_pagination(setup_accounts):
    data = setup_accounts

    for i in range(5):
        job = sample_job()
        job["title"] = f"Python Developer {i}"

        created = data["http"].post(
            "/jobs",
            json=job,
            headers=data["recruiter"],
        )

        assert created.status_code == 201

        applied = data["http"].post(
            "/applications",
            json={"job_id": created.json()["id"]},
            headers=data["candidate"],
        )

        assert applied.status_code == 201

    response = data["http"].get(
        "/applications/me?page=2&page_size=2",
        headers=data["candidate"],
    )

    assert response.status_code == 200
    assert response.json()["total"] == 5
    assert response.json()["total_pages"] == 3
    assert len(response.json()["items"]) == 2
