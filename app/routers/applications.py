
from math import ceil
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    get_current_user,
    require_roles,
)
from app.models import Application, Job, User
from app.schemas import (
    ApplicationCreate,
    ApplicationResponse,
    ApplicationDetail,
    PaginatedApplications,
)


router = APIRouter(
    prefix="/applications",
    tags=["Application Management"],
)

DB = Annotated[Session, Depends(get_db)]

Candidate = Annotated[
    User,
    Depends(require_roles("candidate")),
]

Recruiter = Annotated[
    User,
    Depends(require_roles("recruiter")),
]

CurrentUser = Annotated[
    User,
    Depends(get_current_user),
]


# ==========================================
# HELPER FUNCTIONS
# ==========================================

def get_application_or_404(
    db: Session,
    application_id: int,
) -> Application:
    application = db.get(Application, application_id)

    if application is None:
        raise HTTPException(
            status_code=404,
            detail="Application not found",
        )

    return application


def get_owned_job_or_404(
    db: Session,
    job_id: int,
    recruiter_id: int,
) -> Job:
    job = db.scalar(
        select(Job).where(
            Job.id == job_id,
            Job.recruiter_id == recruiter_id,
        )
    )

    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Job not found",
        )

    return job


def get_recruiter_application(
    db: Session,
    application_id: int,
    recruiter_id: int,
) -> Application:
    application = db.scalar(
        select(Application)
        .join(Job, Application.job_id == Job.id)
        .where(
            Application.id == application_id,
            Job.recruiter_id == recruiter_id,
        )
    )

    if application is None:
        raise HTTPException(
            status_code=404,
            detail="Application not found",
        )

    return application


def application_details(
    db: Session,
    application: Application,
) -> dict:
    job = db.get(Job, application.job_id)
    candidate = db.get(User, application.candidate_id)

    return {
        "id": application.id,
        "candidate_id": application.candidate_id,
        "job_id": application.job_id,
        "status": application.status,
        "applied_at": application.applied_at,
        "job_title": job.title,
        "candidate_name": candidate.full_name,
    }


def paginate_applications(
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
            Application.applied_at.desc(),
            Application.id.desc(),
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


def change_application_status(
    db: Session,
    application_id: int,
    expected_status: str,
    new_status: str,
) -> Application:
    # Conditional UPDATE prevents two concurrent
    # requests from changing the same status twice.
    result = db.execute(
        update(Application)
        .where(
            Application.id == application_id,
            Application.status == expected_status,
        )
        .values(status=new_status)
    )

    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Application status has changed",
        )

    db.commit()

    return get_application_or_404(
        db, application_id
    )


# ==========================================
# 1. CANDIDATE APPLIES FOR A JOB
# ==========================================

@router.post(
    "",
    response_model=ApplicationResponse,
    status_code=status.HTTP_201_CREATED,
)
def apply_for_job(
    data: ApplicationCreate,
    db: DB,
    candidate: Candidate,
):
    job = db.scalar(
        select(Job).where(
            Job.id == data.job_id,
            Job.status == "open",
        )
    )

    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Open job not found",
        )

    existing = db.scalar(
        select(Application).where(
            Application.candidate_id == candidate.id,
            Application.job_id == data.job_id,
        )
    )

    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="You have already applied for this job",
        )

    application = Application(
        candidate_id=candidate.id,
        job_id=data.job_id,
        status="applied",
    )

    db.add(application)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Application could not be created",
        )

    db.refresh(application)

    return application


# ==========================================
# 2. CANDIDATE VIEWS OWN APPLICATIONS
# ==========================================

@router.get(
    "/me",
    response_model=PaginatedApplications,
)
def my_applications(
    db: DB,
    candidate: Candidate,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(
        default=10, ge=1, le=100
    ),
):
    statement = select(Application).where(
        Application.candidate_id == candidate.id
    )

    return paginate_applications(
        db, statement, page, page_size
    )


# ==========================================
# 3. CANDIDATE VIEWS ONE APPLICATION
# ==========================================

@router.get(
    "/me/{application_id}",
    response_model=ApplicationDetail,
)
def my_application_detail(
    application_id: int,
    db: DB,
    candidate: Candidate,
):
    application = db.scalar(
        select(Application).where(
            Application.id == application_id,
            Application.candidate_id == candidate.id,
        )
    )

    if application is None:
        raise HTTPException(
            status_code=404,
            detail="Application not found",
        )

    return application_details(db, application)


# ==========================================
# 4. RECRUITER VIEWS JOB APPLICATIONS
# ==========================================

@router.get(
    "/job/{job_id}",
    response_model=PaginatedApplications,
)
def applications_for_job(
    job_id: int,
    db: DB,
    recruiter: Recruiter,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(
        default=10, ge=1, le=100
    ),
):
    get_owned_job_or_404(
        db, job_id, recruiter.id
    )

    statement = select(Application).where(
        Application.job_id == job_id
    )

    return paginate_applications(
        db, statement, page, page_size
    )


# ==========================================
# 5. AUTHORIZED APPLICATION DETAILS
# ==========================================

@router.get(
    "/{application_id}",
    response_model=ApplicationDetail,
)
def get_application_detail(
    application_id: int,
    db: DB,
    current_user: CurrentUser,
):
    application = get_application_or_404(
        db, application_id
    )

    if current_user.role == "candidate":
        allowed = (
            application.candidate_id == current_user.id
        )

    elif current_user.role == "recruiter":
        job = db.get(Job, application.job_id)
        allowed = (
            job is not None
            and job.recruiter_id == current_user.id
        )

    else:
        allowed = False

    if not allowed:
        raise HTTPException(
            status_code=404,
            detail="Application not found",
        )

    return application_details(db, application)


# ==========================================
# 6. CANDIDATE WITHDRAWS APPLICATION
# ==========================================

@router.patch(
    "/{application_id}/withdraw",
    response_model=ApplicationResponse,
)
def withdraw_application(
    application_id: int,
    db: DB,
    candidate: Candidate,
):
    application = db.scalar(
        select(Application).where(
            Application.id == application_id,
            Application.candidate_id == candidate.id,
        )
    )

    if application is None:
        raise HTTPException(
            status_code=404,
            detail="Application not found",
        )

    if application.status != "applied":
        raise HTTPException(
            status_code=409,
            detail="Only applied applications can be withdrawn",
        )

    return change_application_status(
        db, application_id,
        "applied", "withdrawn"
    )


# ==========================================
# 7. RECRUITER SHORTLISTS CANDIDATE
# ==========================================

@router.patch(
    "/{application_id}/shortlist",
    response_model=ApplicationResponse,
)
def shortlist_application(
    application_id: int,
    db: DB,
    recruiter: Recruiter,
):
    application = get_recruiter_application(
        db, application_id, recruiter.id
    )

    if application.status != "applied":
        raise HTTPException(
            status_code=409,
            detail="Only applied candidates can be shortlisted",
        )

    return change_application_status(
        db, application_id,
        "applied", "shortlisted"
    )


# ==========================================
# 8. RECRUITER REJECTS CANDIDATE
# ==========================================

@router.patch(
    "/{application_id}/reject",
    response_model=ApplicationResponse,
)
def reject_application(
    application_id: int,
    db: DB,
    recruiter: Recruiter,
):
    application = get_recruiter_application(
        db, application_id, recruiter.id
    )

    if application.status not in (
        "applied", "shortlisted"
    ):
        raise HTTPException(
            status_code=409,
            detail="Application cannot be rejected",
        )

    return change_application_status(
        db, application_id,
        application.status, "rejected"
    )
