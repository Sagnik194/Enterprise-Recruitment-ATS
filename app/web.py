import secrets
import re
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from math import ceil
from pathlib import Path
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Depends, Form, File, UploadFile, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Application, Interview, Job, User
from app.phase7_models import JobRequirement
from app.phase10_models import ApplicationDetail, ApplicationDocument
from app.supabase_storage import upload_pdf, delete_document, get_signed_document_url
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
MAX_DOCUMENT_SIZE = 5 * 1024 * 1024
logger = logging.getLogger(__name__)


async def validate_application_pdf(uploaded_file: UploadFile | None, required=False):
    if uploaded_file is None or not uploaded_file.filename:
        if required:
            raise HTTPException(422, "Resume PDF is required")
        return None
    filename = uploaded_file.filename.replace("\\", "/").split("/")[-1]
    if len(filename) > 255 or not filename.lower().endswith(".pdf"):
        raise HTTPException(422, "Document must have a PDF filename")
    if uploaded_file.content_type != "application/pdf":
        raise HTTPException(422, "Only PDF documents are allowed")
    contents = await uploaded_file.read(MAX_DOCUMENT_SIZE + 1)
    if not contents or len(contents) > MAX_DOCUMENT_SIZE:
        raise HTTPException(422, "PDF must be nonempty and at most 5 MB")
    if not contents.startswith(b"%PDF-"):
        raise HTTPException(422, "Invalid PDF signature")
    return {"filename": filename, "contents": contents, "size_bytes": len(contents)}


def validate_profile_url(value: str):
    value = value.strip()
    if not value:
        return None
    if len(value) > 500:
        raise HTTPException(422, "Profile URL is too long")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(422, "Invalid profile URL")
    return value


def cleanup_application_uploads(keys):
    for key in keys:
        try:
            delete_document(key)
        except Exception:
            logger.exception("Could not remove orphaned document %s", key)


@router.post("/web/apply/{job_id}")
async def apply(
    job_id: int,
    request: Request,
    csrf: str = Form(...),
    full_name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
    city: str = Form(...),
    degree: str = Form(...),
    college: str = Form(...),
    graduation_year: int = Form(...),
    cgpa: Decimal | None = Form(None),
    active_backlogs: int = Form(0),
    tenth_percentage: Decimal | None = Form(None),
    twelfth_percentage: Decimal | None = Form(None),
    experience_months: int = Form(0),
    github_url: str = Form(""),
    linkedin_url: str = Form(""),
    skills: str = Form(...),
    resume: UploadFile = File(...),
    certificate: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    check_csrf(request, csrf)
    user = require_user(request, db, "candidate")
    if user is None:
        return redirect("/login")

    job = db.scalar(select(Job).where(Job.id == job_id, Job.status == "open"))
    if job is None:
        raise HTTPException(404, "Open job not found")
    if db.scalar(select(Application).where(Application.candidate_id == user.id, Application.job_id == job_id)):
        return redirect(notice="already_applied")

    full_name, phone, city = full_name.strip(), phone.strip(), city.strip()
    degree, college, skills = degree.strip(), college.strip(), skills.strip()
    if not 2 <= len(full_name) <= 120:
        raise HTTPException(422, "Invalid full name")
    if email.strip().lower() != user.email.lower():
        raise HTTPException(422, "Email does not match your account")
    if not re.fullmatch(r"[0-9+\-()\s]{7,30}", phone):
        raise HTTPException(422, "Invalid phone number")
    if not 2 <= len(city) <= 120 or not 2 <= len(degree) <= 120 or not 2 <= len(college) <= 200:
        raise HTTPException(422, "Invalid city, degree or college")
    if not 1950 <= graduation_year <= 2100:
        raise HTTPException(422, "Invalid graduation year")
    if not 0 <= active_backlogs <= 100 or not 0 <= experience_months <= 720:
        raise HTTPException(422, "Invalid backlogs or experience")
    if not 1 <= len(skills) <= 5000:
        raise HTTPException(422, "Skills must contain 1–5000 characters")
    if cgpa is not None and (not cgpa.is_finite() or not 0 <= cgpa <= 10):
        raise HTTPException(422, "CGPA must be between 0 and 10")
    for label, value in (("10th percentage", tenth_percentage), ("12th percentage", twelfth_percentage)):
        if value is not None and (not value.is_finite() or not 0 <= value <= 100):
            raise HTTPException(422, f"Invalid {label}")
    github_url = validate_profile_url(github_url)
    linkedin_url = validate_profile_url(linkedin_url)

    resume_data = await validate_application_pdf(resume, required=True)
    certificate_data = await validate_application_pdf(certificate)
    uploaded_keys = []
    try:
        resume_key = upload_pdf(resume_data["contents"], "resumes")
        uploaded_keys.append(resume_key)
        certificate_key = None
        if certificate_data:
            certificate_key = upload_pdf(certificate_data["contents"], "certificates")
            uploaded_keys.append(certificate_key)

        # Database uniqueness constraint prevents concurrent duplicate applications.
        application = Application(candidate_id=user.id, job_id=job_id, status="applied")
        db.add(application)
        db.flush()
        db.add(ApplicationDetail(
            application_id=application.id,
            full_name=full_name, email=user.email, phone=phone, city=city,
            degree=degree, college=college, graduation_year=graduation_year,
            cgpa=cgpa, active_backlogs=active_backlogs,
            tenth_percentage=tenth_percentage, twelfth_percentage=twelfth_percentage,
            experience_months=experience_months, github_url=github_url,
            linkedin_url=linkedin_url, skills=skills,
        ))
        db.add(ApplicationDocument(
            application_id=application.id, document_type="resume",
            storage_key=resume_key, original_filename=resume_data["filename"],
            content_type="application/pdf", size_bytes=resume_data["size_bytes"],
        ))
        if certificate_data:
            db.add(ApplicationDocument(
                application_id=application.id, document_type="certificate",
                storage_key=certificate_key, original_filename=certificate_data["filename"],
                content_type="application/pdf", size_bytes=certificate_data["size_bytes"],
            ))
        db.commit()
    except IntegrityError:
        # A concurrent submission may violate the unique candidate/job constraint.
        # Other integrity errors must not be reported as duplicate applications.
        db.rollback()
        logger.exception("Database integrity error while submitting application for job_id=%s", job_id)
        cleanup_application_uploads(uploaded_keys)
        existing = db.scalar(
            select(Application).where(
                Application.candidate_id == user.id,
                Application.job_id == job_id,
            )
        )
        if existing is not None:
            return redirect(notice="already_applied")
        raise HTTPException(503, "Application submission failed. Please try again.")
    except Exception:
        db.rollback()
        # Log the original exception before cleanup, which may also fail.
        logger.exception("Application submission failed for job_id=%s", job_id)
        cleanup_application_uploads(uploaded_keys)
        raise HTTPException(503, "Application submission failed. Please try again.")
    return redirect(notice="applied")




# Phase 10D: Recruiter-only candidate review and private document access.
@router.get("/web/recruiter/applications/{application_id}")
def recruiter_application_review(
    application_id: int, request: Request, db: Session = Depends(get_db)
):
    recruiter = require_user(request, db, "recruiter")
    if recruiter is None:
        return redirect("/login")
    application = owned_application(db, application_id, recruiter.id, lock=False)
    job = db.get(Job, application.job_id)
    candidate = db.get(User, application.candidate_id)
    detail = db.scalar(select(ApplicationDetail).where(ApplicationDetail.application_id == application.id))
    documents = db.scalars(
        select(ApplicationDocument).where(ApplicationDocument.application_id == application.id)
        .order_by(ApplicationDocument.id)
    ).all()
    return render(
        request, "application_review.html", user=recruiter, application=application,
        job=job, candidate=candidate, detail=detail, documents=documents,
    )


@router.get("/web/recruiter/applications/{application_id}/documents/{document_id}")
def recruiter_application_document(
    application_id: int, document_id: int, request: Request,
    db: Session = Depends(get_db),
):
    recruiter = require_user(request, db, "recruiter")
    if recruiter is None:
        return redirect("/login")
    application = owned_application(db, application_id, recruiter.id, lock=False)
    document = db.scalar(select(ApplicationDocument).where(
        ApplicationDocument.id == document_id,
        ApplicationDocument.application_id == application.id,
    ))
    if document is None:
        raise HTTPException(404, "Document not found")
    try:
        signed_url = get_signed_document_url(document.storage_key)
    except Exception:
        logger.exception("Unable to generate signed document URL for document_id=%s", document_id)
        raise HTTPException(503, "Document temporarily unavailable")
    if not signed_url or not isinstance(signed_url, str):
        logger.error("Storage returned an invalid signed URL for document_id=%s", document_id)
        raise HTTPException(503, "Document temporarily unavailable")
    response = RedirectResponse(signed_url, status_code=302)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.post("/web/recruiter/applications/{application_id}/evaluation")
def save_recruiter_evaluation(
    application_id: int, request: Request,
    csrf: str = Form(...),
    recruiter_notes: str = Form(""),
    evaluation_rating: int | None = Form(None),
    db: Session = Depends(get_db),
):
    check_csrf(request, csrf)
    recruiter = require_user(request, db, "recruiter")
    if recruiter is None:
        return redirect("/login")
    application = owned_application(db, application_id, recruiter.id)
    if len(recruiter_notes) > 5000:
        raise HTTPException(422, "Recruiter notes must be at most 5000 characters")
    if evaluation_rating is not None and not 1 <= evaluation_rating <= 5:
        raise HTTPException(422, "Rating must be between 1 and 5")
    detail = db.scalar(select(ApplicationDetail).where(ApplicationDetail.application_id == application.id))
    if detail is None:
        raise HTTPException(409, "This application has no Phase 10 candidate profile")
    detail.recruiter_notes = recruiter_notes.strip() or None
    detail.evaluation_rating = evaluation_rating
    db.commit()
    return redirect(f"/web/recruiter/applications/{application.id}", notice="evaluation_saved")


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
