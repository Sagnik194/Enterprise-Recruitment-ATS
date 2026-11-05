"""Additive Phase 7 tests. Run with python -m pytest tests/test_phase7.py -v."""
import re
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base, get_db
from app.main import app
from app.models import User, Job, Application
from app.phase7_models import CandidateProfile, JobRequirement
from app.phase7_service import evaluate
from app.security import hash_password

@pytest.fixture
def setup(tmp_path, monkeypatch):
    from app.routers import phase7
    monkeypatch.setattr(phase7, 'STORAGE', tmp_path / 'resumes')
    engine = create_engine('sqlite+pysqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    def override():
        with Session() as db:
            yield db
    app.dependency_overrides[get_db] = override
    with Session() as db:
        c = User(full_name='Candidate', email='c@example.com', password_hash=hash_password('StrongPassword123!'), role='candidate')
        r = User(full_name='Recruiter', email='r@example.com', password_hash=hash_password('StrongPassword123!'), role='recruiter')
        x = User(full_name='Other', email='x@example.com', password_hash=hash_password('StrongPassword123!'), role='recruiter')
        db.add_all([c,r,x]); db.flush()
        j = Job(title='Backend Developer', description='Build secure Python APIs with SQL databases.', location='Kolkata', recruiter_id=r.id, status='open')
        db.add(j); db.flush()
        a = Application(candidate_id=c.id, job_id=j.id, status='applied')
        db.add(a); db.commit()
        ids = (c.id, r.id, x.id, j.id)
    with TestClient(app) as client:
        yield client, Session, ids
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()

def login(client, email):
    page = client.get('/login')
    token = re.search(r'name="csrf"\s+value="([^"]+)"', page.text).group(1)
    r = client.post('/login', data={'email': email, 'password': 'StrongPassword123!', 'csrf': token}, follow_redirects=False)
    assert r.status_code == 303

def csrf(client):
    page = client.get('/phase7')
    return re.search(r'name="csrf"\s+value="([^"]+)"', page.text).group(1)

def test_screening_eligible():
    p = CandidateProfile(graduation_year=2027, experience_months=0, skills='Python, SQL')
    r = JobRequirement(graduation_year_min=2026, graduation_year_max=2028, minimum_experience_months=0, required_skills='python,sql')
    assert evaluate(p,r)['status'] == 'eligible'

def test_screening_missing_information():
    assert evaluate(None, JobRequirement(required_skills='Python'))['status'] == 'insufficient_information'

def test_screening_not_eligible():
    p = CandidateProfile(graduation_year=2025, experience_months=0, skills='Java')
    r = JobRequirement(graduation_year_min=2027, required_skills='Python')
    assert evaluate(p,r)['status'] == 'not_eligible'

def test_candidate_profile_and_screening(setup):
    http, Session, ids = setup
    login(http,'c@example.com')
    r = http.post('/phase7/profile', data={'csrf': csrf(http), 'graduation_year':'2027', 'experience_months':'0', 'skills':'Python, SQL'}, follow_redirects=False)
    assert r.status_code == 303
    with Session() as db:
        assert db.scalar(select(CandidateProfile).where(CandidateProfile.user_id==ids[0])).graduation_year == 2027

def test_candidate_cannot_set_requirements(setup):
    http, _, ids = setup
    login(http,'c@example.com')
    r = http.post(f'/phase7/requirements/{ids[3]}', data={'csrf':csrf(http), 'required_skills':'Python'})
    assert r.status_code == 403

def test_recruiter_cannot_change_other_job(setup):
    http, _, ids = setup
    login(http,'x@example.com')
    r = http.post(f'/phase7/requirements/{ids[3]}', data={'csrf':csrf(http), 'required_skills':'Python'})
    assert r.status_code == 404

def test_recruiter_requirements_and_analytics(setup):
    http, Session, ids = setup
    login(http,'r@example.com')
    r = http.post(f'/phase7/requirements/{ids[3]}', data={'csrf':csrf(http), 'required_skills':'Python, SQL', 'graduation_year_min':'2026'}, follow_redirects=False)
    assert r.status_code == 303
    with Session() as db:
        assert db.scalar(select(JobRequirement).where(JobRequirement.job_id==ids[3])).required_skills == 'Python, SQL'
    a = http.get('/phase7/analytics')
    assert a.status_code == 200 and a.json()['applications'] == 1

def test_resume_upload_download_and_access(setup):
    http, _, ids = setup
    login(http,'c@example.com')
    content = b'%PDF-1.4\n1 0 obj <<>> endobj\n%%EOF'
    r = http.post('/phase7/resume', data={'csrf':csrf(http)}, files={'resume':('cv.pdf',content,'application/pdf')}, follow_redirects=False)
    assert r.status_code == 303
    assert http.get(f'/phase7/resume/{ids[0]}').content == content
    token = csrf(http)
    http.post('/logout', data={'csrf':token}, follow_redirects=False)
    login(http,'x@example.com')
    assert http.get(f'/phase7/resume/{ids[0]}').status_code == 404

def test_resume_rejects_non_pdf(setup):
    http, _, _ = setup
    login(http,'c@example.com')
    r = http.post('/phase7/resume', data={'csrf':csrf(http)}, files={'resume':('fake.pdf',b'not a pdf','application/pdf')})
    assert r.status_code == 422

def test_invalid_csrf_profile(setup):
    http, _, _ = setup
    login(http,'c@example.com')
    assert http.post('/phase7/profile', data={'csrf':'bad', 'skills':'Python'}).status_code == 403
