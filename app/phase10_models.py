
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ApplicationDetail(Base):
    __tablename__ = "application_details"

    id: Mapped[int] = mapped_column(primary_key=True)

    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id"),
        unique=True,
        nullable=False,
    )

    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(30), nullable=False)
    city: Mapped[str] = mapped_column(String(120), nullable=False)

    degree: Mapped[str] = mapped_column(String(120), nullable=False)
    college: Mapped[str] = mapped_column(String(200), nullable=False)
    graduation_year: Mapped[int] = mapped_column(Integer, nullable=False)

    cgpa: Mapped[float | None] = mapped_column(Numeric(4, 2))
    active_backlogs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tenth_percentage: Mapped[float | None] = mapped_column(Numeric(5, 2))
    twelfth_percentage: Mapped[float | None] = mapped_column(Numeric(5, 2))

    experience_months: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    github_url: Mapped[str | None] = mapped_column(String(500))
    linkedin_url: Mapped[str | None] = mapped_column(String(500))
    skills: Mapped[str] = mapped_column(Text, nullable=False)

    recruiter_notes: Mapped[str | None] = mapped_column(Text)
    evaluation_rating: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
        nullable=False,
    )

    application = relationship("Application", back_populates="detail")


class ApplicationDocument(Base):
    __tablename__ = "application_documents"

    __table_args__ = (
        UniqueConstraint(
            "application_id",
            "document_type",
            name="uq_application_document_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id"),
        nullable=False,
        index=True,
    )

    document_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    storage_key: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
    )

    original_filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    content_type: Mapped[str] = mapped_column(
        String(100),
        default="application/pdf",
        nullable=False,
    )

    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
        nullable=False,
    )

    application = relationship("Application", back_populates="documents")
