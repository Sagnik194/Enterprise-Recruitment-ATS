import secrets
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from math import ceil
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Application, Interview, Job, User
from app.phase7_models import JobRequirement
from app.security import verify_password

router = APIRouter(tags=["Web Dashboard"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


def redirect(path="/dashboard", notice=None):
    if notice:
        path += ("&" if "?" in path else "?") + urlencode({"notice": notice})
    return RedirectResponse(path, status_code=303)


def user_from_session(request: Request, db: Session):
    user_id = request.session.get("user_id")
    return db.get(User, user_id) if type(user_id) is int else None


def token_for(request: Request):
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return token


def check_csrf(request: Request, supplied: str):
    expected = request.session.get("csrf")
    if not isinstance(expected, str) or not secrets.compare_digest(expected, supplied):
        raise HTTPException(403, "Invalid form token")


def render(request: Request, name: str, **context):
    return templates.TemplateResponse(request=request, name=name, context={"csrf": token_for(request), **context})


def require_user(request: Request, db: Session, role=None):
    user = user_from_session(request, db)
    if user is None:
        return None
    if role and user.role != role:
        raise HTTPException(403, "Access denied")
    return user


def utc_naive(dt: datetime):
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise HTTPException(422, "Timezone offset required (example: +05:30)")
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def future_datetime(value: str):
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(422, "Invalid date/time")
    normalized = utc_naive(dt)
    if normalized <= datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=5):
        raise HTTPException(422, "Interview must be at least 5 minutes in the future")
    return normalized


def owned_application(db: Session, application_id: int, recruiter_id: int, lock=True):
    stmt = (select(Application).join(Job, Application.job_id == Job.id)
            .where(Application.id == application_id, Job.recruiter_id == recruiter_id))
    if lock:
        stmt = stmt.with_for_update(of=Application)
    application = db.scalar(stmt)
    if application is None:
        raise HTTPException(404, "Application not found")
    return application


def owned_interview(db: Session, interview_id: int, recruiter_id: int):
    # Locate the interview, lock the owning application, then refresh the interview.
    interview = db.scalar(select(Interview).join(Application).join(Job)
                          .where(Interview.id == interview_id, Job.recruiter_id == recruiter_id))
    if interview is None:
        raise HTTPException(404, "Interview not found")
    application = owned_application(db, interview.application_id, recruiter_id)
    db.refresh(interview)
    return interview, application


@router.get("/login")
def login_page(request: Request, db: Session = Depends(get_db)):
    if user_from_session(request, db):
        return redirect()
    return render(request, "login.html", error=None)


@router.post("/login")
def login_submit(request: Request, email: str = Form(...), password: str = Form(...),
                 csrf: str = Form(...), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not verify_password(password, user.password_hash):
        return render(request, "login.html", error="Invalid email or password")
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["csrf"] = secrets.token_urlsafe(32)
    return redirect()


@router.post("/logout")
def logout(request: Request, csrf: str = Form(...)):
    check_csrf(request, csrf)
    request.session.clear()
    return redirect("/login")


@router.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db),
              q: str = Query("", max_length=150), location: str = Query("", max_length=120),
              min_salary: int | None = Query(None, ge=0),
              page: int = Query(1, ge=1), page_size: int = Query(6, ge=1, le=50),
              app_status: str = Query("", max_length=30),
              candidate_q: str = Query("", max_length=150)):
    user = require_user(request, db)
    if user is None:
        return redirect("/login")
    if user.role == "candidate":
        stmt = select(Job).where(Job.status == "open")
        if q.strip():
            term = f"%{q.strip()}%"
            stmt = stmt.where(or_(Job.title.ilike(term), Job.description.ilike(term)))
        if location.strip():
            stmt = stmt.where(Job.location.ilike(f"%{location.strip()}%"))
        if min_salary is not None:
            stmt = stmt.where(Job.salary_max >= min_salary)
        total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
        jobs = db.scalars(stmt.order_by(Job.created_at.desc(), Job.id.desc())
                          .offset((page - 1) * page_size).limit(page_size)).all()
        applications = db.scalars(select(Application).where(Application.candidate_id == user.id)
                                  .order_by(Application.applied_at.desc(), Application.id.desc())).all()
        interviews = db.scalars(select(Interview).join(Application)
                                .where(Application.candidate_id == user.id)
                                .order_by(Interview.scheduled_at.desc(), Interview.id.desc())).all()
        job_ids = {a.job_id for a in applications}
        titles = {j.id: j.title for j in db.scalars(select(Job)).all()}
        params = {"q": q, "location": location, "page_size": page_size}
        if min_salary is not None:
            params["min_salary"] = min_salary
        return render(request, "candidate.html", user=user, jobs=jobs, applications=applications,
                      interviews=interviews, applied_job_ids=job_ids, job_titles=titles,
                      total_jobs=total, page=page, total_pages=ceil(total / page_size),
                      query_params=urlencode(params), q=q, location=location, min_salary=min_salary,
                      page_size=page_size)
    if user.role == "recruiter":
        jobs = db.scalars(select(Job).where(Job.recruiter_id == user.id)
                          .order_by(Job.created_at.desc(), Job.id.desc())).all()
        job_ids = [job.id for job in jobs]
        requirements = {}

        if job_ids:
            requirements = {
                req.job_id: req
                for req in db.scalars(
                    select(JobRequirement).where(
                        JobRequirement.job_id.in_(job_ids)
                    )
                ).all()
            }
        stmt = select(Application).join(Job).join(User, Application.candidate_id == User.id).where(Job.recruiter_id == user.id)
        allowed_statuses = {"applied", "shortlisted", "interview_scheduled", "selected", "rejected", "withdrawn"}
        if app_status in allowed_statuses:
            stmt = stmt.where(Application.status == app_status)
        if candidate_q.strip():
            term = f"%{candidate_q.strip()}%"
            stmt = stmt.where(or_(User.full_name.ilike(term), User.email.ilike(term), Job.title.ilike(term)))
        applications = db.scalars(stmt.order_by(Application.applied_at.desc(), Application.id.desc())).all()
        ids = {a.candidate_id for a in applications}
        candidates = {u.id: u.full_name for u in db.scalars(select(User).where(User.id.in_(ids))).all()} if ids else {}
        interviews = db.scalars(select(Interview).join(Application).join(Job)
                                .where(Job.recruiter_id == user.id)
                                .order_by(Interview.scheduled_at.desc(), Interview.id.desc())).all()
        return render(
            request,
            "recruiter.html",
            user=user,
            jobs=jobs,
            applications=applications,
            candidates=candidates,
            job_titles={j.id: j.title for j in jobs},
            interviews=interviews,
            app_status=app_status,
            candidate_q=candidate_q,
            requirements=requirements,
        )
    if user.role == "admin":
        stats = {"users": db.scalar(select(func.count(User.id))) or 0,
                 "jobs": db.scalar(select(func.count(Job.id))) or 0,
                 "applications": db.scalar(select(func.count(Application.id))) or 0,
                 "interviews": db.scalar(select(func.count(Interview.id))) or 0}
        users = db.scalars(select(User).order_by(User.created_at.desc()).limit(50)).all()
        return render(request, "admin.html", user=user, stats=stats, users=users)
    raise HTTPException(403, "Unknown role")

@router.get("/web/apply/{job_id}")
def application_form(
    job_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    user = require_user(request, db, "candidate")

    if user is None:
        return redirect("/login")

    job = db.scalar(
        select(Job).where(
            Job.id == job_id,
            Job.status == "open"
        )
    )

    if job is None:
        raise HTTPException(404, "Open job not found")

    existing = db.scalar(
        select(Application).where(
            Application.candidate_id == user.id,
            Application.job_id == job_id
        )
    )

    if existing is not None:
        return redirect(notice="already_applied")

    requirements = db.scalar(
        select(JobRequirement).where(
            JobRequirement.job_id == job_id
        )
    )

    return render(
        request,
        "apply_job.html",
        user=user,
        job=job,
        requirements=requirements
    )
@router.post("/web/apply/{job_id}")
def apply(job_id: int, request: Request, csrf: str = Form(...), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    user = require_user(request, db, "candidate")
    if user is None:
        return redirect("/login")
    job = db.scalar(select(Job).where(Job.id == job_id, Job.status == "open"))
    if job is None:
        raise HTTPException(404, "Open job not found")
    if db.scalar(select(Application).where(Application.candidate_id == user.id, Application.job_id == job_id)):
        return redirect(notice="already_applied")
    db.add(Application(candidate_id=user.id, job_id=job_id, status="applied"))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return redirect(notice="already_applied")
    return redirect(notice="applied")


@router.post("/web/jobs")
def create_job(request: Request, title: str = Form(...), description: str = Form(...),
               location: str = Form(...), csrf: str = Form(...), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    user = require_user(request, db, "recruiter")
    if user is None:
        return redirect("/login")
    title, description, location = title.strip(), description.strip(), location.strip()
    if not 3 <= len(title) <= 150 or len(description) < 20 or not 2 <= len(location) <= 120:
        raise HTTPException(422, "Invalid job details")
    db.add(Job(title=title, description=description, location=location,
               recruiter_id=user.id, status="open"))
    db.commit()
    return redirect(notice="job_created")


@router.post("/web/jobs/{job_id}/{action}")
def change_job(job_id: int, action: str, request: Request, csrf: str = Form(...), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    user = require_user(request, db, "recruiter")
    if user is None:
        return redirect("/login")
    if action not in {"close", "reopen"}:
        raise HTTPException(404, "Unknown action")
    job = db.scalar(select(Job).where(Job.id == job_id, Job.recruiter_id == user.id).with_for_update())
    if job is None:
        raise HTTPException(404, "Job not found")
    expected, new = ("open", "closed") if action == "close" else ("closed", "open")
    if job.status != expected:
        raise HTTPException(409, "Job is already in the requested state")
    job.status = new
    db.commit()
    return redirect(notice="job_updated")


@router.post("/web/applications/{application_id}/{action}")
def application_action(application_id: int, action: str, request: Request,
                       csrf: str = Form(...), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    user = require_user(request, db)
    if user is None:
        return redirect("/login")
    if action not in {"shortlist", "reject", "withdraw"}:
        raise HTTPException(404, "Unknown action")
    application = db.scalar(select(Application).where(Application.id == application_id).with_for_update())
    if application is None:
        raise HTTPException(404, "Application not found")
    if action == "withdraw":
        if user.role != "candidate" or application.candidate_id != user.id:
            raise HTTPException(404, "Application not found")
        if application.status != "applied":
            raise HTTPException(409, "Cannot withdraw")
        application.status = "withdrawn"
    else:
        job = db.get(Job, application.job_id)
        if user.role != "recruiter" or job.recruiter_id != user.id:
            raise HTTPException(404, "Application not found")
        if action == "shortlist" and application.status == "applied":
            application.status = "shortlisted"
        elif action == "reject" and application.status in {"applied", "shortlisted"}:
            application.status = "rejected"
        else:
            raise HTTPException(409, "Invalid application status transition")
    db.commit()
    return redirect(notice="updated")


@router.post("/web/interviews")
def schedule_interview(request: Request, application_id: int = Form(...),
                       scheduled_at: str = Form(...), duration_minutes: int = Form(60),
                       interview_mode: str = Form(...), meeting_details: str = Form(...),
                       csrf: str = Form(...), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    user = require_user(request, db, "recruiter")
    if user is None:
        return redirect("/login")
    application = owned_application(db, application_id, user.id)
    if application.status != "shortlisted":
        raise HTTPException(409, "Application must be shortlisted")
    if not 15 <= duration_minutes <= 240 or interview_mode not in {"online", "offline"}:
        raise HTTPException(422, "Invalid interview settings")
    meeting_details = meeting_details.strip()
    if not 5 <= len(meeting_details) <= 500:
        raise HTTPException(422, "Meeting details must be 5–500 characters")
    if db.scalar(select(Interview).where(Interview.application_id == application_id,
                                         Interview.status == "scheduled")):
        raise HTTPException(409, "An active interview already exists")
    interview = Interview(application_id=application_id, scheduled_at=future_datetime(scheduled_at),
                          duration_minutes=duration_minutes, interview_mode=interview_mode,
                          meeting_details=meeting_details, status="scheduled")
    application.status = "interview_scheduled"
    db.add(interview)
    db.commit()
    return redirect(notice="interview_scheduled")


@router.post("/web/interviews/{interview_id}/reschedule")
def reschedule_interview(interview_id: int, request: Request, scheduled_at: str = Form(...),
                         duration_minutes: int = Form(...), csrf: str = Form(...),
                         db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    user = require_user(request, db, "recruiter")
    if user is None:
        return redirect("/login")
    interview, application = owned_interview(db, interview_id, user.id)
    if interview.status != "scheduled" or application.status != "interview_scheduled":
        raise HTTPException(409, "Interview cannot be rescheduled")
    if not 15 <= duration_minutes <= 240:
        raise HTTPException(422, "Invalid duration")
    interview.scheduled_at = future_datetime(scheduled_at)
    interview.duration_minutes = duration_minutes
    db.commit()
    return redirect(notice="interview_rescheduled")


@router.post("/web/interviews/{interview_id}/cancel")
def cancel_interview(interview_id: int, request: Request, csrf: str = Form(...),
                     db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    user = require_user(request, db, "recruiter")
    if user is None:
        return redirect("/login")
    interview, application = owned_interview(db, interview_id, user.id)
    if interview.status != "scheduled" or application.status != "interview_scheduled":
        raise HTTPException(409, "Interview cannot be cancelled")
    interview.status = "cancelled"
    application.status = "shortlisted"
    db.commit()
    return redirect(notice="interview_cancelled")


@router.post("/web/interviews/{interview_id}/result")
def interview_result(interview_id: int, request: Request, result: str = Form(...),
                     feedback: str = Form(""), csrf: str = Form(...), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    user = require_user(request, db, "recruiter")
    if user is None:
        return redirect("/login")
    interview, application = owned_interview(db, interview_id, user.id)
    if interview.status != "scheduled" or application.status != "interview_scheduled":
        raise HTTPException(409, "Interview cannot be completed")
    if interview.scheduled_at > datetime.now(timezone.utc).replace(tzinfo=None):
        raise HTTPException(409, "Interview has not started yet")
    if result not in {"selected", "rejected"} or len(feedback) > 2000:
        raise HTTPException(422, "Invalid result or feedback")
    interview.status = "completed"
    interview.result = result
    interview.feedback = feedback.strip() or None
    application.status = result
    db.commit()
    return redirect(notice="interview_completed")
