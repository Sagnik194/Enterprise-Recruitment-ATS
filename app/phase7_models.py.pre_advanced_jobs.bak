"""Phase 7 additive models. Import in Alembic env.py and application startup."""
from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

def now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)

class CandidateProfile(Base):
    __tablename__ = 'candidate_profiles'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), unique=True, nullable=False)
    graduation_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    degree: Mapped[str | None] = mapped_column(String(100), nullable=True)
    experience_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skills: Mapped[str | None] = mapped_column(Text, nullable=True)

class Resume(Base):
    __tablename__ = 'resumes'
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey('users.id'), unique=True, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)

class JobRequirement(Base):
    __tablename__ = 'job_requirements'
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey('jobs.id'), unique=True, nullable=False)
    graduation_year_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    graduation_year_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    minimum_experience_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    required_skills: Mapped[str | None] = mapped_column(Text, nullable=True)
