
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)


# ==========================================
# PHASE 2 — AUTHENTICATION
# ==========================================

class UserRegister(BaseModel):
    full_name: str = Field(
        min_length=2,
        max_length=120
    )
    email: EmailStr
    password: str = Field(
        min_length=8,
        max_length=128
    )

    @field_validator("full_name")
    @classmethod
    def validate_name(cls, value: str):
        value = value.strip()

        if len(value) < 2:
            raise ValueError("Name is too short")

        return value


class UserResponse(BaseModel):
    id: int
    full_name: str
    email: EmailStr
    role: Literal[
        "candidate", "recruiter", "admin"
    ]
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True
    )


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class MessageResponse(BaseModel):
    message: str


# ==========================================
# PHASE 3 — JOB MANAGEMENT
# ==========================================

JobStatus = Literal["open", "closed"]


class JobBase(BaseModel):
    title: str = Field(
        min_length=3,
        max_length=150
    )
    description: str = Field(
        min_length=20
    )
    location: str = Field(
        min_length=2,
        max_length=120
    )
    salary_min: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=12,
        decimal_places=2
    )
    salary_max: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=12,
        decimal_places=2
    )

    @field_validator(
        "title", "description", "location"
    )
    @classmethod
    def clean_text(cls, value: str):
        value = value.strip()

        if not value:
            raise ValueError("Field cannot be empty")

        return value

    @model_validator(mode="after")
    def check_salary(self):
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_min > self.salary_max
        ):
            raise ValueError(
                "Minimum salary cannot exceed maximum salary"
            )

        return self


class JobCreate(JobBase):
    pass


class JobUpdate(BaseModel):
    title: str | None = Field(
        default=None,
        min_length=3,
        max_length=150
    )
    description: str | None = Field(
        default=None,
        min_length=20
    )
    location: str | None = Field(
        default=None,
        min_length=2,
        max_length=120
    )
    salary_min: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=12,
        decimal_places=2
    )
    salary_max: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=12,
        decimal_places=2
    )

    @field_validator(
        "title", "description", "location"
    )
    @classmethod
    def clean_text(cls, value: str | None):
        if value is None:
            return value

        value = value.strip()

        if not value:
            raise ValueError("Field cannot be empty")

        return value


class JobResponse(BaseModel):
    id: int
    title: str
    description: str
    location: str
    salary_min: Decimal | None
    salary_max: Decimal | None
    status: JobStatus
    recruiter_id: int
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True
    )


class PaginatedJobs(BaseModel):
    items: list[JobResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# ==========================================
# PHASE 4 — APPLICATION MANAGEMENT
# ==========================================

ApplicationStatus = Literal[
    "applied",
    "shortlisted",
    "interview_scheduled",
    "interview_completed",
    "selected",
    "rejected",
    "withdrawn",
]


class ApplicationCreate(BaseModel):
    job_id: int = Field(gt=0)


class ApplicationResponse(BaseModel):
    id: int
    candidate_id: int
    job_id: int
    status: ApplicationStatus
    applied_at: datetime

    model_config = ConfigDict(
        from_attributes=True
    )


class ApplicationDetail(ApplicationResponse):
    job_title: str
    candidate_name: str


class PaginatedApplications(BaseModel):
    items: list[ApplicationResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# ==========================================
# PHASE 5 — INTERVIEW MANAGEMENT
# ==========================================

InterviewMode = Literal[
    "online",
    "offline",
]

InterviewStatus = Literal[
    "scheduled",
    "completed",
    "cancelled",
]

InterviewResult = Literal[
    "selected",
    "rejected",
]


class InterviewCreate(BaseModel):
    application_id: int = Field(gt=0)
    scheduled_at: datetime

    duration_minutes: int = Field(
        default=60,
        ge=15,
        le=240
    )

    interview_mode: InterviewMode

    meeting_details: str = Field(
        min_length=5,
        max_length=500
    )

    @field_validator("scheduled_at")
    @classmethod
    def validate_schedule(cls, value: datetime):
        if (
            value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise ValueError(
                "Timezone is required"
            )

        minimum_time = (
            datetime.now(timezone.utc)
            + timedelta(minutes=5)
        )

        if value.astimezone(timezone.utc) <= minimum_time:
            raise ValueError(
                "Interview must be at least "
                "5 minutes in the future"
            )

        return value

    @field_validator("meeting_details")
    @classmethod
    def clean_details(cls, value: str):
        value = value.strip()

        if len(value) < 5:
            raise ValueError(
                "Meeting details must contain "
                "at least 5 characters"
            )

        return value


class InterviewReschedule(BaseModel):
    scheduled_at: datetime

    duration_minutes: int | None = Field(
        default=None,
        ge=15,
        le=240
    )

    @field_validator("scheduled_at")
    @classmethod
    def validate_schedule(cls, value: datetime):
        if (
            value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise ValueError(
                "Timezone is required"
            )

        minimum_time = (
            datetime.now(timezone.utc)
            + timedelta(minutes=5)
        )

        if value.astimezone(timezone.utc) <= minimum_time:
            raise ValueError(
                "New interview time must be at "
                "least 5 minutes in the future"
            )

        return value


class InterviewResultUpdate(BaseModel):
    result: InterviewResult

    feedback: str | None = Field(
        default=None,
        max_length=2000
    )


class InterviewResponse(BaseModel):
    id: int
    application_id: int
    scheduled_at: datetime
    duration_minutes: int
    interview_mode: InterviewMode
    meeting_details: str
    status: InterviewStatus
    result: InterviewResult | None
    feedback: str | None
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True
    )

    @field_validator(
        "scheduled_at",
        "created_at",
        mode="after"
    )
    @classmethod
    def attach_utc(cls, value: datetime):
        if value.tzinfo is None:
            return value.replace(
                tzinfo=timezone.utc
            )

        return value.astimezone(
            timezone.utc
        )


class PaginatedInterviews(BaseModel):
    items: list[InterviewResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
