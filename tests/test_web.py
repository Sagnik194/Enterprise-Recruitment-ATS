
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import User, Job, Application
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

    with TestClient(app) as http:
        yield http, Session

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
        return user.id


def get_csrf(html):
    match = re.search(
        r'name="csrf"\s+value="([^"]+)"',
        html,
    )
    assert match is not None
    return match.group(1)


def browser_login(http, email):
    page = http.get("/login")
    assert page.status_code == 200

    csrf = get_csrf(page.text)

    return http.post(
        "/login",
        data={
            "email": email,
            "password": "StrongPassword123!",
            "csrf": csrf,
        },
        follow_redirects=False,
    )


def test_login_page(client):
    http, _ = client

    response = http.get("/login")

    assert response.status_code == 200
    assert "Welcome back" in response.text


def test_candidate_dashboard(client):
    http, Session = client

    create_user(
        Session,
        "candidate@example.com",
        "candidate",
    )

    response = browser_login(
        http, "candidate@example.com"
    )

    assert response.status_code == 303

    dashboard = http.get("/dashboard")

    assert dashboard.status_code == 200
    assert "Candidate Dashboard" in dashboard.text


def test_recruiter_dashboard(client):
    http, Session = client

    create_user(
        Session,
        "recruiter@example.com",
        "recruiter",
    )

    browser_login(
        http, "recruiter@example.com"
    )

    dashboard = http.get("/dashboard")

    assert dashboard.status_code == 200
    assert "Recruiter Dashboard" in dashboard.text


def test_admin_dashboard(client):
    http, Session = client

    create_user(
        Session,
        "admin@example.com",
        "admin",
    )

    browser_login(http, "admin@example.com")

    dashboard = http.get("/dashboard")

    assert dashboard.status_code == 200
    assert "Admin Dashboard" in dashboard.text


def test_unauthenticated_redirect(client):
    http, _ = client

    response = http.get(
        "/dashboard",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_invalid_csrf_rejected(client):
    http, Session = client

    create_user(
        Session,
        "candidate@example.com",
        "candidate",
    )

    response = http.post(
        "/login",
        data={
            "email": "candidate@example.com",
            "password": "StrongPassword123!",
            "csrf": "invalid",
        },
    )

    assert response.status_code == 403


def test_candidate_can_apply_from_web(client):
    http, Session = client

    create_user(
        Session,
        "candidate@example.com",
        "candidate",
    )

    recruiter_id = create_user(
        Session,
        "recruiter@example.com",
        "recruiter",
    )

    with Session() as db:
        job = Job(
            title="Python Developer",
            description=(
                "Develop backend APIs using Python "
                "and relational databases."
            ),
            location="Kolkata",
            recruiter_id=recruiter_id,
            status="open",
        )
        db.add(job)
        db.commit()
        job_id = job.id

    browser_login(http, "candidate@example.com")

    dashboard = http.get("/dashboard")
    csrf = get_csrf(dashboard.text)

    response = http.post(
        f"/web/apply/{job_id}",
        data={"csrf": csrf},
        follow_redirects=False,
    )

    assert response.status_code == 303

    with Session() as db:
        applications = db.query(Application).all()
        assert len(applications) == 1
        assert applications[0].job_id == job_id


def test_candidate_cannot_post_job(client):
    http, Session = client

    create_user(
        Session,
        "candidate@example.com",
        "candidate",
    )

    browser_login(http, "candidate@example.com")

    csrf = get_csrf(
        http.get("/dashboard").text
    )

    response = http.post(
        "/web/jobs",
        data={
            "csrf": csrf,
            "title": "Python Developer",
            "description": (
                "Develop backend APIs using "
                "Python and FastAPI."
            ),
            "location": "Kolkata",
        },
    )

    assert response.status_code == 403
