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
    ai_usage_assessment: Mapped[Optional[AiUsageAssessment]] = relationship(
        back_populates="submission",
        cascade="all, delete-orphan",
        uselist=False,
    )
    model_runs: Mapped[list[ModelRun]] = relationship(
        back_populates="submission",
        cascade="all, delete-orphan",
        order_by="ModelRun.created_at",
    )
    execution_check: Mapped[Optional[ExecutionCheck]] = relationship(
        back_populates="submission",
        cascade="all, delete-orphan",
        uselist=False,
    )
    code_comments: Mapped[list[CodeComment]] = relationship(
        back_populates="submission",
        cascade="all, delete-orphan",
        order_by="CodeComment.created_at",
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


class CodeComment(Base):
    __tablename__ = "code_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), index=True)
    file_path: Mapped[str] = mapped_column(String(500))
    line_number: Mapped[int] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    submission: Mapped[Submission] = relationship(back_populates="code_comments")


class AiUsageAssessment(Base):
    __tablename__ = "ai_usage_assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="insufficient_data")
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reasons_json: Mapped[str] = mapped_column(Text, default="[]")
    limitations: Mapped[str] = mapped_column(Text, default="")
    model_version: Mapped[str] = mapped_column(String(160), default="")

    submission: Mapped[Submission] = relationship(back_populates="ai_usage_assessment")


class ModelRun(Base):
    __tablename__ = "model_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), index=True)
    provider: Mapped[str] = mapped_column(String(60), default="yandex_cloud")
    model: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(40))
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_type: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    submission: Mapped[Submission] = relationship(back_populates="model_runs")


class ExecutionCheck(Base):
    __tablename__ = "execution_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(40))
    go_version: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    dependencies_ok: Mapped[Optional[bool]] = mapped_column(nullable=True)
    tests_ok: Mapped[Optional[bool]] = mapped_column(nullable=True)
    vet_ok: Mapped[Optional[bool]] = mapped_column(nullable=True)
    has_tests: Mapped[bool] = mapped_column(default=False)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    output_summary: Mapped[str] = mapped_column(Text, default="")

    submission: Mapped[Submission] = relationship(back_populates="execution_check")
