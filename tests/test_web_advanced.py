"""Phase 6 advanced browser integration tests (isolated SQLite)."""
import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Application, Interview, Job, User
from app.security import hash_password


@pytest.fixture
def setup():
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        with Session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as http:
        yield http, Session
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def create_user(Session, email, role):
    with Session() as db:
        user = User(full_name=email.split('@')[0], email=email, password_hash=hash_password('StrongPassword123!'), role=role)
        db.add(user)
        db.commit()
        return user.id


def csrf(html):
    match = re.search(r'name="csrf"\s+value="([^"]+)"', html)
    assert match
    return match.group(1)


def login(http, email):
    token = csrf(http.get('/login').text)
    r = http.post('/login', data={'email': email, 'password': 'StrongPassword123!', 'csrf': token}, follow_redirects=False)
    assert r.status_code == 303


def post(http, url, **data):
    token = csrf(http.get('/dashboard').text)
    return http.post(url, data={'csrf': token, **data}, follow_redirects=False)


def seed(setup):
    http, Session = setup
    candidate = create_user(Session, 'candidate@example.com', 'candidate')
    recruiter = create_user(Session, 'recruiter@example.com', 'recruiter')
    other = create_user(Session, 'other@example.com', 'recruiter')
    with Session() as db:
        job = Job(title='Python Developer', description='Build reliable Python APIs using FastAPI and SQL.', location='Kolkata', recruiter_id=recruiter, status='open', salary_min=400000, salary_max=900000)
        job2 = Job(title='Java Developer', description='Build reliable Java services and database applications.', location='Pune', recruiter_id=other, status='open', salary_min=300000, salary_max=600000)
        db.add_all([job, job2]); db.flush()
        application = Application(candidate_id=candidate, job_id=job.id, status='shortlisted')
        db.add(application); db.commit()
        return candidate, recruiter, other, job.id, job2.id, application.id


def future():
    return (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()


def schedule(http, app_id):
    return post(http, '/web/interviews', application_id=str(app_id), scheduled_at=future(), duration_minutes='60', interview_mode='online', meeting_details='Online interview meeting')


def test_job_search_and_location_filter(setup):
    http, Session = setup
    seed(setup)
    login(http, 'candidate@example.com')
    r = http.get('/dashboard?q=Python&location=Kolkata')
    assert r.status_code == 200
    assert 'Python Developer' in r.text
    assert 'Java Developer' not in r.text


def test_job_salary_filter(setup):
    http, Session = setup
    seed(setup)
    login(http, 'candidate@example.com')
    r = http.get('/dashboard?min_salary=800000')
    assert 'Python Developer' in r.text
    assert 'Java Developer' not in r.text


def test_job_pagination(setup):
    http, Session = setup
    seed(setup)
    login(http, 'candidate@example.com')
    first = http.get('/dashboard?page_size=1&page=1')
    second = http.get('/dashboard?page_size=1&page=2')
    assert first.status_code == second.status_code == 200
    assert 'page=2' in first.text
    assert first.text != second.text


def test_recruiter_closes_and_reopens_job(setup):
    http, Session = setup
    _, _, _, job_id, _, _ = seed(setup)
    login(http, 'recruiter@example.com')
    assert post(http, f'/web/jobs/{job_id}/close').status_code == 303
    with Session() as db:
        assert db.get(Job, job_id).status == 'closed'
    assert post(http, f'/web/jobs/{job_id}/reopen').status_code == 303
    with Session() as db:
        assert db.get(Job, job_id).status == 'open'


def test_other_recruiter_cannot_close_job(setup):
    http, Session = setup
    _, _, _, job_id, _, _ = seed(setup)
    login(http, 'other@example.com')
    assert post(http, f'/web/jobs/{job_id}/close').status_code == 404


def test_recruiter_schedule_interview(setup):
    http, Session = setup
    _, _, _, _, _, app_id = seed(setup)
    login(http, 'recruiter@example.com')
    assert schedule(http, app_id).status_code == 303
    with Session() as db:
        assert db.get(Application, app_id).status == 'interview_scheduled'
        assert db.scalar(select(Interview).where(Interview.application_id == app_id)).status == 'scheduled'


def test_candidate_cannot_schedule_interview(setup):
    http, Session = setup
    _, _, _, _, _, app_id = seed(setup)
    login(http, 'candidate@example.com')
    assert schedule(http, app_id).status_code == 403


def test_other_recruiter_cannot_schedule_interview(setup):
    http, Session = setup
    _, _, _, _, _, app_id = seed(setup)
    login(http, 'other@example.com')
    assert schedule(http, app_id).status_code == 404


def test_duplicate_schedule_conflict(setup):
    http, Session = setup
    _, _, _, _, _, app_id = seed(setup)
    login(http, 'recruiter@example.com')
    assert schedule(http, app_id).status_code == 303
    assert schedule(http, app_id).status_code == 409


def test_reschedule_and_cancel(setup):
    http, Session = setup
    _, _, _, _, _, app_id = seed(setup)
    login(http, 'recruiter@example.com')
    schedule(http, app_id)
    with Session() as db:
        interview_id = db.scalar(select(Interview).where(Interview.application_id == app_id)).id
    r = post(http, f'/web/interviews/{interview_id}/reschedule', scheduled_at=future(), duration_minutes='45')
    assert r.status_code == 303
    with Session() as db:
        assert db.get(Interview, interview_id).duration_minutes == 45
    assert post(http, f'/web/interviews/{interview_id}/cancel').status_code == 303
    with Session() as db:
        assert db.get(Interview, interview_id).status == 'cancelled'
        assert db.get(Application, app_id).status == 'shortlisted'


def test_cancelled_interview_can_be_replaced(setup):
    http, Session = setup
    _, _, _, _, _, app_id = seed(setup)
    login(http, 'recruiter@example.com')
    schedule(http, app_id)
    with Session() as db:
        interview_id = db.scalar(select(Interview).where(Interview.application_id == app_id)).id
    post(http, f'/web/interviews/{interview_id}/cancel')
    assert schedule(http, app_id).status_code == 303
    with Session() as db:
        assert len(db.scalars(select(Interview).where(Interview.application_id == app_id)).all()) == 2


def test_result_requires_started_interview(setup):
    http, Session = setup
    _, _, _, _, _, app_id = seed(setup)
    login(http, 'recruiter@example.com')
    schedule(http, app_id)
    with Session() as db:
        interview_id = db.scalar(select(Interview).where(Interview.application_id == app_id)).id
    assert post(http, f'/web/interviews/{interview_id}/result', result='selected', feedback='Strong candidate').status_code == 409


def test_result_selected_updates_application(setup):
    http, Session = setup
    _, _, _, _, _, app_id = seed(setup)
    login(http, 'recruiter@example.com')
    schedule(http, app_id)
    with Session() as db:
        interview = db.scalar(select(Interview).where(Interview.application_id == app_id))
        interview_id = interview.id
        interview.scheduled_at = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(tzinfo=None)
        db.commit()
    assert post(http, f'/web/interviews/{interview_id}/result', result='selected', feedback='Good').status_code == 303
    with Session() as db:
        assert db.get(Application, app_id).status == 'selected'
        assert db.get(Interview, interview_id).status == 'completed'


def test_csrf_required_for_interview_actions(setup):
    http, Session = setup
    _, _, _, _, _, app_id = seed(setup)
    login(http, 'recruiter@example.com')
    r = http.post('/web/interviews', data={'csrf':'wrong','application_id':app_id,'scheduled_at':future(),'interview_mode':'online','meeting_details':'Online meeting'})
    assert r.status_code == 403


def test_recruiter_application_filter(setup):
    http, Session = setup
    seed(setup)
    login(http, 'recruiter@example.com')
    assert 'candidate' in http.get('/dashboard?app_status=shortlisted&candidate_q=candidate').text
    assert 'No matching applications' in http.get('/dashboard?app_status=rejected').text
