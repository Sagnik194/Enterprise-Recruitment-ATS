
from decimal import Decimal
from math import ceil
from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Response,
    status,
)
from sqlalchemy import (
    func,
    or_,
    select,
)
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    get_current_user,
    require_roles,
)
from app.models import Application, Job, User
from app.schemas import (
    JobCreate,
    JobUpdate,
    JobResponse,
    PaginatedJobs,
)


router = APIRouter(
    prefix="/jobs",
    tags=["Job Management"]
)

DB = Annotated[Session, Depends(get_db)]

Recruiter = Annotated[
    User,
    Depends(require_roles("recruiter"))
]


# ---------------------------------
# Helper functions
# ---------------------------------

def get_owned_job(
    job_id: int,
    db: Session,
    recruiter: User
) -> Job:

    job = db.scalar(
        select(Job).where(
            Job.id == job_id,
            Job.recruiter_id == recruiter.id
        )
    )

    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Job not found"
        )

    return job


def validate_salary_range(
    salary_min: Decimal | None,
    salary_max: Decimal | None
):
    if (
        salary_min is not None
        and salary_max is not None
        and salary_min > salary_max
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "Minimum salary cannot exceed "
                "maximum salary"
            )
        )


def paginated_result(
    db: Session,
    statement,
    page: int,
    page_size: int
):
    total = db.scalar(
        select(func.count()).select_from(
            statement.order_by(None).subquery()
        )
    ) or 0

    jobs = db.scalars(
        statement
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return {
        "items": jobs,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": ceil(total / page_size)
    }


# ---------------------------------
# Create job
# ---------------------------------

@router.post(
    "",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED
)
def create_job(
    data: JobCreate,
    db: DB,
    recruiter: Recruiter
):
    job = Job(
        **data.model_dump(),
        recruiter_id=recruiter.id,
        status="open"
    )

    db.add(job)
    db.commit()
    db.refresh(job)

    return job


# ---------------------------------
# Get public jobs
# ---------------------------------

@router.get(
    "",
    response_model=PaginatedJobs
)
def list_jobs(
    db: DB,
    search: str | None = Query(
        default=None, max_length=150
    ),
    location: str | None = Query(
        default=None, max_length=120
    ),
    min_salary: Decimal | None = Query(
        default=None, ge=0
    ),
    max_salary: Decimal | None = Query(
        default=None, ge=0
    ),
    sort_by: Literal[
        "newest",
        "oldest",
        "salary_min",
        "salary_max"
    ] = "newest",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(
        default=10, ge=1, le=100
    )
):
    statement = select(Job).where(
        Job.status == "open"
    )

    if search:
        pattern = f"%{search.strip()}%"

        statement = statement.where(
            or_(
                Job.title.ilike(pattern),
                Job.description.ilike(pattern)
            )
        )

    if location:
        statement = statement.where(
            Job.location.ilike(
                f"%{location.strip()}%"
            )
        )

    # Job salary range overlaps the
    # requested salary range.
    if min_salary is not None:
        statement = statement.where(
            Job.salary_max >= min_salary
        )

    if max_salary is not None:
        statement = statement.where(
            Job.salary_min <= max_salary
        )

    sort_options = {
        "newest": Job.created_at.desc(),
        "oldest": Job.created_at.asc(),
        "salary_min": Job.salary_min.asc(),
        "salary_max": Job.salary_max.desc(),
    }

    statement = statement.order_by(
        sort_options[sort_by],
        Job.id.desc()
    )

    return paginated_result(
        db, statement, page, page_size
    )


# ---------------------------------
# Recruiter's own jobs
# ---------------------------------

@router.get(
    "/recruiter/mine",
    response_model=PaginatedJobs
)
def my_jobs(
    db: DB,
    recruiter: Recruiter,
    job_status: Literal[
        "open", "closed"
    ] | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(
        default=10, ge=1, le=100
    )
):
    statement = select(Job).where(
        Job.recruiter_id == recruiter.id
    )

    if job_status:
        statement = statement.where(
            Job.status == job_status
        )

    statement = statement.order_by(
        Job.created_at.desc(),
        Job.id.desc()
    )

    return paginated_result(
        db, statement, page, page_size
    )


# ---------------------------------
# Get single public job
# ---------------------------------

@router.get(
    "/{job_id}",
    response_model=JobResponse
)
def get_job(
    job_id: int,
    db: DB
):
    job = db.scalar(
        select(Job).where(
            Job.id == job_id,
            Job.status == "open"
        )
    )

    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Job not found"
        )

    return job


# ---------------------------------
# Update job
# ---------------------------------

@router.patch(
    "/{job_id}",
    response_model=JobResponse
)
def update_job(
    job_id: int,
    data: JobUpdate,
    db: DB,
    recruiter: Recruiter
):
    job = get_owned_job(
        job_id, db, recruiter
    )

    if job.status != "open":
        raise HTTPException(
            status_code=409,
            detail="Closed jobs cannot be edited"
        )

    changes = data.model_dump(
        exclude_unset=True
    )

    # These database fields are not nullable.
    for field in (
        "title", "description", "location"
    ):
        if field in changes and changes[field] is None:
            raise HTTPException(
                status_code=422,
                detail=f"{field} cannot be null"
            )

    salary_min = changes.get(
        "salary_min", job.salary_min
    )

    salary_max = changes.get(
        "salary_max", job.salary_max
    )

    validate_salary_range(
        salary_min, salary_max
    )

    for field, value in changes.items():
        setattr(job, field, value)

    db.commit()
    db.refresh(job)

    return job


# ---------------------------------
# Close job
# ---------------------------------

@router.patch(
    "/{job_id}/close",
    response_model=JobResponse
)
def close_job(
    job_id: int,
    db: DB,
    recruiter: Recruiter
):
    job = get_owned_job(
        job_id, db, recruiter
    )

    if job.status == "closed":
        raise HTTPException(
            status_code=409,
            detail="Job is already closed"
        )

    job.status = "closed"

    db.commit()
    db.refresh(job)

    return job


# ---------------------------------
# Reopen job
# ---------------------------------

@router.patch(
    "/{job_id}/reopen",
    response_model=JobResponse
)
def reopen_job(
    job_id: int,
    db: DB,
    recruiter: Recruiter
):
    job = get_owned_job(
        job_id, db, recruiter
    )

    if job.status == "open":
        raise HTTPException(
            status_code=409,
            detail="Job is already open"
        )

    job.status = "open"

    db.commit()
    db.refresh(job)

    return job


# ---------------------------------
# Delete job
# ---------------------------------

@router.delete(
    "/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT
)
def delete_job(
    job_id: int,
    db: DB,
    recruiter: Recruiter
):
    job = get_owned_job(
        job_id, db, recruiter
    )

    # For now, protect application history.
    if db.scalar(
        select(func.count(Application.id)).where(
            Application.job_id == job.id
        )
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Job has applications and "
                "cannot be deleted"
            )
        )

    db.delete(job)
    db.commit()

    return Response(
        status_code=status.HTTP_204_NO_CONTENT
    )
