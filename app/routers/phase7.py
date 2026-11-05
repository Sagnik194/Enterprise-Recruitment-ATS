"""Phase 7 browser and JSON endpoints. Uses existing signed session and CSRF utilities."""
import os
import secrets
from pathlib import Path
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, Job, Application, Interview
from app.phase7_models import CandidateProfile, Resume, JobRequirement
from app.phase7_service import evaluate
from app.web import require_user, check_csrf, render

router = APIRouter(tags=['Phase 7'])
MAX_BYTES = 5 * 1024 * 1024
STORAGE = Path(os.getenv('ATS_RESUME_STORAGE', 'private_uploads/resumes')).resolve()

def go(path):
    return RedirectResponse(path, status_code=303)

def auth(request, db, role):
    user = require_user(request, db, role)
    if user is None:
        raise HTTPException(401, 'Please log in')
    return user

def owned_job(db, job_id, recruiter_id):
    job = db.scalar(select(Job).where(Job.id == job_id, Job.recruiter_id == recruiter_id))
    if job is None:
        raise HTTPException(404, 'Job not found')
    return job

def resume_access(db, candidate_id, user):
    if user.role == 'candidate' and user.id == candidate_id:
        return
    if user.role == 'recruiter':
        permitted = db.scalar(select(Application.id).join(Job).where(
            Application.candidate_id == candidate_id, Job.recruiter_id == user.id).limit(1))
        if permitted is not None:
            return
    raise HTTPException(404, 'Resume not found')

@router.get('/phase7')
def phase7_home(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if user is None:
        return go('/login')
    if user.role == 'candidate':
        profile = db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == user.id))
        resume = db.scalar(select(Resume).where(Resume.candidate_id == user.id))
        applications = db.scalars(select(Application).where(Application.candidate_id == user.id)).all()
        jobs = {j.id: j for j in db.scalars(select(Job).where(Job.id.in_([a.job_id for a in applications]))).all()} if applications else {}
        requirements = {r.job_id: r for r in db.scalars(select(JobRequirement).where(JobRequirement.job_id.in_(list(jobs)))).all()} if jobs else {}
        screening = [{'job': jobs[a.job_id], 'application': a, 'result': evaluate(profile, requirements.get(a.job_id))} for a in applications]
        return render(request, 'phase7_candidate.html', user=user, profile=profile, resume=resume, screening=screening)
    if user.role == 'recruiter':
        jobs = db.scalars(select(Job).where(Job.recruiter_id == user.id)).all()
        requirements = {r.job_id: r for r in db.scalars(select(JobRequirement).where(JobRequirement.job_id.in_([j.id for j in jobs]))).all()} if jobs else {}
        applications = db.scalars(select(Application).join(Job).where(Job.recruiter_id == user.id)).all()
        candidate_ids = list({a.candidate_id for a in applications})
        profiles = {p.user_id: p for p in db.scalars(select(CandidateProfile).where(CandidateProfile.user_id.in_(candidate_ids))).all()} if candidate_ids else {}
        users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(candidate_ids))).all()} if candidate_ids else {}
        job_lookup = {j.id: j for j in jobs}
        screening = [{'application': a, 'candidate': users[a.candidate_id], 'job': job_lookup[a.job_id], 'result': evaluate(profiles.get(a.candidate_id), requirements.get(a.job_id))} for a in applications]
        return render(request, 'phase7_recruiter.html', user=user, jobs=jobs, requirements=requirements, screening=screening)
    return go('/dashboard')

@router.post('/phase7/profile')
def save_profile(request: Request, csrf: str = Form(...), graduation_year: int | None = Form(None),
                 degree: str = Form(''), experience_months: int | None = Form(None), skills: str = Form(''),
                 db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    user = auth(request, db, 'candidate')
    if graduation_year is not None and not 1950 <= graduation_year <= 2100:
        raise HTTPException(422, 'Invalid graduation year')
    if experience_months is not None and not 0 <= experience_months <= 900:
        raise HTTPException(422, 'Invalid experience')
    if len(degree) > 100 or len(skills) > 2000:
        raise HTTPException(422, 'Profile fields too long')
    profile = db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == user.id).with_for_update())
    if profile is None:
        profile = CandidateProfile(user_id=user.id)
        db.add(profile)
    profile.graduation_year = graduation_year
    profile.degree = degree.strip() or None
    profile.experience_months = experience_months
    profile.skills = skills.strip() or None
    db.commit()
    return go('/phase7?notice=profile_saved')

@router.post('/phase7/resume')
async def upload_resume(request: Request, csrf: str = Form(...), resume: UploadFile = File(...), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    user = auth(request, db, 'candidate')
    if not resume.filename or not resume.filename.lower().endswith('.pdf'):
        raise HTTPException(422, 'Only PDF files are accepted')
    content = await resume.read(MAX_BYTES + 1)
    await resume.close()
    if not content or len(content) > MAX_BYTES:
        raise HTTPException(413, 'Resume must be between 1 byte and 5 MB')
    if not content.startswith(b'%PDF-') or b'%%EOF' not in content[-2048:]:
        raise HTTPException(422, 'Invalid PDF file')
    STORAGE.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(24) + '.pdf'
    dest = STORAGE / key
    # Exclusive creation prevents accidental overwrite.
    with dest.open('xb') as handle:
        handle.write(content)
    try:
        old = db.scalar(select(Resume).where(Resume.candidate_id == user.id).with_for_update())
        previous_key = old.storage_key if old else None
        if old is None:
            old = Resume(candidate_id=user.id, storage_key=key, original_filename='resume.pdf', size_bytes=len(content))
            db.add(old)
        else:
            old.storage_key = key
            old.original_filename = 'resume.pdf'
            old.size_bytes = len(content)
        db.commit()
    except Exception:
        db.rollback()
        dest.unlink(missing_ok=True)
        raise
    if previous_key:
        (STORAGE / previous_key).unlink(missing_ok=True)
    return go('/phase7?notice=resume_uploaded')

@router.get('/phase7/resume/{candidate_id}')
def download_resume(candidate_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    if user is None:
        raise HTTPException(401, 'Please log in')
    resume_access(db, candidate_id, user)
    resume = db.scalar(select(Resume).where(Resume.candidate_id == candidate_id))
    if resume is None:
        raise HTTPException(404, 'Resume not found')
    path = STORAGE / resume.storage_key
    if not path.is_file():
        raise HTTPException(404, 'Resume file missing')
    return FileResponse(path, media_type='application/pdf', filename='resume.pdf', headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})

@router.post('/phase7/requirements/{job_id}')
def save_requirements(job_id: int, request: Request, csrf: str = Form(...),
                      graduation_year_min: int | None = Form(None), graduation_year_max: int | None = Form(None),
                      minimum_experience_months: int | None = Form(None), required_skills: str = Form(''),
                      db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    user = auth(request, db, 'recruiter')
    owned_job(db, job_id, user.id)
    for year in (graduation_year_min, graduation_year_max):
        if year is not None and not 1950 <= year <= 2100:
            raise HTTPException(422, 'Invalid year')
    if graduation_year_min is not None and graduation_year_max is not None and graduation_year_min > graduation_year_max:
        raise HTTPException(422, 'Minimum year exceeds maximum')
    if minimum_experience_months is not None and not 0 <= minimum_experience_months <= 900:
        raise HTTPException(422, 'Invalid experience')
    if len(required_skills) > 2000:
        raise HTTPException(422, 'Skills field too long')
    requirement = db.scalar(select(JobRequirement).where(JobRequirement.job_id == job_id).with_for_update())
    if requirement is None:
        requirement = JobRequirement(job_id=job_id)
        db.add(requirement)
    requirement.graduation_year_min = graduation_year_min
    requirement.graduation_year_max = graduation_year_max
    requirement.minimum_experience_months = minimum_experience_months
    requirement.required_skills = required_skills.strip() or None
    db.commit()
    return go('/phase7?notice=requirements_saved')

@router.get('/phase7/analytics')
def analytics(request: Request, db: Session = Depends(get_db)):
    user = auth(request, db, 'recruiter')
    jobs = db.scalars(select(Job).where(Job.recruiter_id == user.id)).all()
    apps = db.scalars(select(Application).join(Job).where(Job.recruiter_id == user.id)).all()
    interviews = db.scalars(select(Interview).join(Application).join(Job).where(Job.recruiter_id == user.id)).all()
    counts = {s: sum(a.status == s for a in apps) for s in ('applied','shortlisted','interview_scheduled','selected','rejected','withdrawn')}
    total = len(apps)
    data = {'jobs': len(jobs), 'applications': total, 'interviews': len(interviews), 'application_status': counts,
            'selection_rate_percent': round(100 * counts['selected'] / total, 2) if total else 0}
    return data
