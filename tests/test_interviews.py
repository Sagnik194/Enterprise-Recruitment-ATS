
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import User, Interview, Application
from app.security import hash_password


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(bind=engine)

    Session = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    def override_db():
        with Session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    http = TestClient(app)

    try:
        yield http, Session
    finally:
        http.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def add_user(session_factory, email, role):
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
    return {
        "Authorization": (
            f"Bearer {response.json()['access_token']}"
        )
    }


@pytest.fixture
def prepared(client):
    http, Session = client

    add_user(
        Session, "candidate@example.com", "candidate"
    )
    add_user(
        Session, "recruiter@example.com", "recruiter"
    )
    add_user(
        Session, "other@example.com", "recruiter"
    )

    candidate = login(http, "candidate@example.com")
    recruiter = login(http, "recruiter@example.com")
    other = login(http, "other@example.com")

    job = http.post(
        "/jobs",
        headers=recruiter,
        json={
            "title": "Python Developer",
            "description": (
                "Develop Python REST APIs using "
                "FastAPI and relational databases."
            ),
            "location": "Kolkata",
            "salary_min": 600000,
            "salary_max": 900000,
        },
    )
    assert job.status_code == 201

    application = http.post(
        "/applications",
        headers=candidate,
        json={"job_id": job.json()["id"]},
    )
    assert application.status_code == 201

    application_id = application.json()["id"]

    shortlisted = http.patch(
        f"/applications/{application_id}/shortlist",
        headers=recruiter,
    )
    assert shortlisted.status_code == 200

    return {
        "http": http,
        "Session": Session,
        "candidate": candidate,
        "recruiter": recruiter,
        "other": other,
        "application_id": application_id,
        "job_id": job.json()["id"],
    }


def future_time():
    return (
        datetime.now(timezone.utc)
        + timedelta(days=2)
    ).isoformat()


def schedule(data):
    return data["http"].post(
        "/interviews",
        headers=data["recruiter"],
        json={
            "application_id": data["application_id"],
            "scheduled_at": future_time(),
            "duration_minutes": 60,
            "interview_mode": "online",
            "meeting_details": "Online meeting room A",
        },
    )


def test_schedule_interview(prepared):
    response = schedule(prepared)

    assert response.status_code == 201
    assert response.json()["status"] == "scheduled"

    with prepared["Session"]() as db:
        application = db.get(
            Application, prepared["application_id"]
        )
        assert application.status == "interview_scheduled"


def test_duplicate_active_interview(prepared):
    first = schedule(prepared)
    second = schedule(prepared)

    assert first.status_code == 201
    assert second.status_code == 409


def test_candidate_views_interview(prepared):
    created = schedule(prepared)
    assert created.status_code == 201

    response = prepared["http"].get(
        "/interviews/me",
        headers=prepared["candidate"],
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1


def test_other_recruiter_cannot_reschedule(prepared):
    created = schedule(prepared)
    interview_id = created.json()["id"]

    response = prepared["http"].patch(
        f"/interviews/{interview_id}/reschedule",
        headers=prepared["other"],
        json={
            "scheduled_at": future_time(),
            "duration_minutes": 45,
        },
    )

    assert response.status_code == 404


def test_reschedule_interview(prepared):
    created = schedule(prepared)
    interview_id = created.json()["id"]

    response = prepared["http"].patch(
        f"/interviews/{interview_id}/reschedule",
        headers=prepared["recruiter"],
        json={
            "scheduled_at": (
                datetime.now(timezone.utc)
                + timedelta(days=4)
            ).isoformat(),
            "duration_minutes": 45,
        },
    )

    assert response.status_code == 200
    assert response.json()["duration_minutes"] == 45


def test_cancel_interview(prepared):
    created = schedule(prepared)
    interview_id = created.json()["id"]

    response = prepared["http"].patch(
        f"/interviews/{interview_id}/cancel",
        headers=prepared["recruiter"],
    )

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"

    with prepared["Session"]() as db:
        application = db.get(
            Application, prepared["application_id"]
        )
        assert application.status == "shortlisted"


def test_candidate_cannot_cancel(prepared):
    created = schedule(prepared)
    interview_id = created.json()["id"]

    response = prepared["http"].patch(
        f"/interviews/{interview_id}/cancel",
        headers=prepared["candidate"],
    )

    assert response.status_code == 403


def test_result_before_interview_rejected(prepared):
    created = schedule(prepared)
    interview_id = created.json()["id"]

    response = prepared["http"].patch(
        f"/interviews/{interview_id}/result",
        headers=prepared["recruiter"],
        json={
            "result": "selected",
            "feedback": "Good performance",
        },
    )

    assert response.status_code == 409


def test_complete_interview(prepared):
    created = schedule(prepared)
    interview_id = created.json()["id"]

    # Set a past interview time directly in
    # the isolated test database.
    with prepared["Session"]() as db:
        interview = db.get(Interview, interview_id)
        interview.scheduled_at = (
            datetime.now(timezone.utc)
            - timedelta(hours=2)
        ).replace(tzinfo=None)
        db.commit()

    response = prepared["http"].patch(
        f"/interviews/{interview_id}/result",
        headers=prepared["recruiter"],
        json={
            "result": "selected",
            "feedback": "Strong technical performance",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["result"] == "selected"

    with prepared["Session"]() as db:
        application = db.get(
            Application, prepared["application_id"]
        )
        assert application.status == "selected"
