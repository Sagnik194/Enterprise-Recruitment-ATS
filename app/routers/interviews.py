
from datetime import datetime, timezone
from math import ceil
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    get_current_user,
    require_roles,
)
from app.models import Application, Interview, Job, User
from app.schemas import (
    InterviewCreate,
    InterviewReschedule,
    InterviewResultUpdate,
    InterviewResponse,
    PaginatedInterviews,
)


router = APIRouter(
    prefix="/interviews",
    tags=["Interview Management"],
)

DB = Annotated[Session, Depends(get_db)]

Recruiter = Annotated[
    User,
    Depends(require_roles("recruiter")),
]

Candidate = Annotated[
    User,
    Depends(require_roles("candidate")),
]

CurrentUser = Annotated[
    User,
    Depends(get_current_user),
]


# ==========================================
# HELPER FUNCTIONS
# ==========================================

def to_utc_naive(value: datetime) -> datetime:
    return value.astimezone(
        timezone.utc
    ).replace(tzinfo=None)


def get_owned_application_locked(
    db: Session,
    application_id: int,
    recruiter_id: int,
) -> Application:
    application = db.scalar(
        select(Application)
        .join(
            Job,
            Application.job_id == Job.id
        )
        .where(
            Application.id == application_id,
            Job.recruiter_id == recruiter_id,
        )
        .with_for_update(of=Application)
    )

    if application is None:
        raise HTTPException(
            status_code=404,
            detail="Application not found",
        )

    return application


def get_owned_interview_locked(
    db: Session,
    interview_id: int,
    recruiter_id: int,
):
    # First find the interview and its application.
    # Ownership is checked before any modification.
    interview = db.scalar(
        select(Interview)
        .join(
            Application,
            Interview.application_id == Application.id
        )
        .join(
            Job,
            Application.job_id == Job.id
        )
        .where(
            Interview.id == interview_id,
            Job.recruiter_id == recruiter_id,
        )
    )

    if interview is None:
        raise HTTPException(
            status_code=404,
            detail="Interview not found",
        )

    # Lock the parent application row.
    application = get_owned_application_locked(
        db,
        interview.application_id,
        recruiter_id,
    )

    # Reload the interview after obtaining the lock.
    db.refresh(interview)

    return interview, application


def paginate(
    db: Session,
    statement,
    page: int,
    page_size: int,
):
    total = db.scalar(
        select(func.count()).select_from(
            statement.order_by(None).subquery()
        )
    ) or 0

    items = db.scalars(
        statement
        .order_by(
            Interview.scheduled_at.desc(),
            Interview.id.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": ceil(total / page_size),
    }


# ==========================================
# 1. SCHEDULE INTERVIEW
# ==========================================

@router.post(
    "",
    response_model=InterviewResponse,
    status_code=status.HTTP_201_CREATED,
)
def schedule_interview(
    data: InterviewCreate,
    db: DB,
    recruiter: Recruiter,
):
    application = get_owned_application_locked(
        db,
        data.application_id,
        recruiter.id,
    )

    if application.status != "shortlisted":
        raise HTTPException(
            status_code=409,
            detail="Application must be shortlisted",
        )

    existing = db.scalar(
        select(Interview).where(
            Interview.application_id == application.id,
            Interview.status == "scheduled",
        )
    )

    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="An interview is already scheduled",
        )

    interview = Interview(
        application_id=application.id,
        scheduled_at=to_utc_naive(
            data.scheduled_at
        ),
        duration_minutes=data.duration_minutes,
        interview_mode=data.interview_mode,
        meeting_details=data.meeting_details,
        status="scheduled",
    )

    application.status = "interview_scheduled"

    db.add(interview)
    db.commit()
    db.refresh(interview)

    return interview


# ==========================================
# 2. CANDIDATE VIEWS OWN INTERVIEWS
# ==========================================

@router.get(
    "/me",
    response_model=PaginatedInterviews,
)
def my_interviews(
    db: DB,
    candidate: Candidate,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(
        default=10,
        ge=1,
        le=100
    ),
):
    statement = (
        select(Interview)
        .join(
            Application,
            Interview.application_id == Application.id
        )
        .where(
            Application.candidate_id == candidate.id
        )
    )

    return paginate(
        db,
        statement,
        page,
        page_size,
    )


# ==========================================
# 3. RECRUITER VIEWS JOB INTERVIEWS
# ==========================================

@router.get(
    "/job/{job_id}",
    response_model=PaginatedInterviews,
)
def job_interviews(
    job_id: int,
    db: DB,
    recruiter: Recruiter,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(
        default=10,
        ge=1,
        le=100
    ),
):
    job = db.scalar(
        select(Job).where(
            Job.id == job_id,
            Job.recruiter_id == recruiter.id,
        )
    )

    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Job not found",
        )

    statement = (
        select(Interview)
        .join(
            Application,
            Interview.application_id == Application.id
        )
        .where(
            Application.job_id == job_id
        )
    )

    return paginate(
        db,
        statement,
        page,
        page_size,
    )


# ==========================================
# 4. VIEW INTERVIEW DETAILS
# ==========================================

@router.get(
    "/{interview_id}",
    response_model=InterviewResponse,
)
def interview_details(
    interview_id: int,
    db: DB,
    current_user: CurrentUser,
):
    interview = db.get(
        Interview,
        interview_id,
    )

    if interview is None:
        raise HTTPException(
            status_code=404,
            detail="Interview not found",
        )

    application = db.get(
        Application,
        interview.application_id,
    )

    allowed = False

    if current_user.role == "candidate":
        allowed = (
            application.candidate_id == current_user.id
        )

    elif current_user.role == "recruiter":
        job = db.get(
            Job,
            application.job_id,
        )

        allowed = (
            job is not None
            and job.recruiter_id == current_user.id
        )

    if not allowed:
        raise HTTPException(
            status_code=404,
            detail="Interview not found",
        )

    return interview


# ==========================================
# 5. RESCHEDULE INTERVIEW
# ==========================================

@router.patch(
    "/{interview_id}/reschedule",
    response_model=InterviewResponse,
)
def reschedule_interview(
    interview_id: int,
    data: InterviewReschedule,
    db: DB,
    recruiter: Recruiter,
):
    interview, application = (
        get_owned_interview_locked(
            db,
            interview_id,
            recruiter.id,
        )
    )

    if (
        interview.status != "scheduled"
        or application.status != "interview_scheduled"
    ):
        raise HTTPException(
            status_code=409,
            detail="Only active interviews can be rescheduled",
        )

    interview.scheduled_at = to_utc_naive(
        data.scheduled_at
    )

    if data.duration_minutes is not None:
        interview.duration_minutes = (
            data.duration_minutes
        )

    db.commit()
    db.refresh(interview)

    return interview


# ==========================================
# 6. CANCEL INTERVIEW
# ==========================================

@router.patch(
    "/{interview_id}/cancel",
    response_model=InterviewResponse,
)
def cancel_interview(
    interview_id: int,
    db: DB,
    recruiter: Recruiter,
):
    interview, application = (
        get_owned_interview_locked(
            db,
            interview_id,
            recruiter.id,
        )
    )

    if (
        interview.status != "scheduled"
        or application.status != "interview_scheduled"
    ):
        raise HTTPException(
            status_code=409,
            detail="Interview cannot be cancelled",
        )

    interview.status = "cancelled"
    application.status = "shortlisted"

    db.commit()
    db.refresh(interview)

    return interview


# ==========================================
# 7. RECORD INTERVIEW RESULT
# ==========================================

@router.patch(
    "/{interview_id}/result",
    response_model=InterviewResponse,
)
def record_result(
    interview_id: int,
    data: InterviewResultUpdate,
    db: DB,
    recruiter: Recruiter,
):
    interview, application = (
        get_owned_interview_locked(
            db,
            interview_id,
            recruiter.id,
        )
    )

    if (
        interview.status != "scheduled"
        or application.status != "interview_scheduled"
    ):
        raise HTTPException(
            status_code=409,
            detail="Interview cannot be completed",
        )

    now_utc = datetime.now(
        timezone.utc
    ).replace(tzinfo=None)

    if interview.scheduled_at > now_utc:
        raise HTTPException(
            status_code=409,
            detail="Interview has not started yet",
        )

    interview.status = "completed"
    interview.result = data.result
    interview.feedback = data.feedback

    application.status = data.result

    db.commit()
    db.refresh(interview)

    return interview
