from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Reviewer(Base):
    __tablename__ = "reviewers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    specialization: Mapped[str] = mapped_column(String(120), default="Go")
    capacity: Mapped[int] = mapped_column(Integer, default=2)
    is_active: Mapped[bool] = mapped_column(default=True)
    last_assigned_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    submissions: Mapped[list[Submission]] = relationship(back_populates="reviewer")


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    repository_url: Mapped[str] = mapped_column(Text)
    repository_owner: Mapped[str] = mapped_column(String(120))
    repository_name: Mapped[str] = mapped_column(String(160))
    subdirectory: Mapped[str] = mapped_column(String(500), default="")
    branch: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    commit_sha: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="received")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("reviewers.id"), nullable=True)
    suggested_points: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    assessed_points: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_points: Mapped[int] = mapped_column(Integer, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    due_at: Mapped[datetime] = mapped_column(DateTime)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    reviewer: Mapped[Optional[Reviewer]] = relationship(back_populates="submissions")
    criteria: Mapped[list[CriterionResult]] = relationship(
        back_populates="submission",
        cascade="all, delete-orphan",
        order_by="CriterionResult.position",
    )
    events: Mapped[list[AuditEvent]] = relationship(
        back_populates="submission",
        cascade="all, delete-orphan",
        order_by="AuditEvent.created_at",
    )


class CriterionResult(Base):
    __tablename__ = "criterion_results"
    __table_args__ = (UniqueConstraint("submission_id", "code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(240))
    max_points: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40))
    suggested_points: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    final_points: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    feedback: Mapped[str] = mapped_column(Text, default="")
    final_feedback: Mapped[str] = mapped_column(Text, default="")
    human_decision: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)

    submission: Mapped[Submission] = relationship(back_populates="criteria")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), index=True)
    kind: Mapped[str] = mapped_column(String(80))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    submission: Mapped[Submission] = relationship(back_populates="events")
