"""Audit event ORM model and safe writer; import model before Alembic metadata scan."""
from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class AuditEvent(Base):
    __tablename__ = 'audit_events'
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    resource_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


def add_audit_event(db, *, action: str, outcome: str, actor_user_id: int | None = None, resource_type: str | None = None, resource_id: int | None = None, ip_address: str | None = None):
    """Add to caller's transaction. Caller must commit or rollback."""
    event = AuditEvent(action=action, outcome=outcome, actor_user_id=actor_user_id, resource_type=resource_type, resource_id=resource_id, ip_address=ip_address)
    db.add(event)
    return event
