from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Reviewer, Submission


ACTIVE_STATUSES = {"received", "assigned", "processing", "review_ready", "human_review"}


@dataclass(frozen=True)
class AssignmentDecision:
    reviewer: Reviewer
    active_reviews: int
    reason: str


def choose_reviewer(session: Session, specialization: str = "Go") -> AssignmentDecision:
    load_query = (
        select(Submission.reviewer_id, func.count(Submission.id))
        .where(Submission.status.in_(ACTIVE_STATUSES), Submission.reviewer_id.is_not(None))
        .group_by(Submission.reviewer_id)
    )
    loads = {reviewer_id: count for reviewer_id, count in session.execute(load_query)}

    candidates = list(
        session.scalars(
            select(Reviewer).where(
                Reviewer.is_active.is_(True),
                Reviewer.specialization == specialization,
            )
        )
    )
    available = [reviewer for reviewer in candidates if loads.get(reviewer.id, 0) < reviewer.capacity]
    if not available:
        raise ValueError("Нет свободного ревьюера с подходящей специализацией")

    def rank(reviewer: Reviewer) -> tuple[float, datetime, int]:
        active = loads.get(reviewer.id, 0)
        load_ratio = active / max(reviewer.capacity, 1)
        last_assigned = reviewer.last_assigned_at or datetime.min
        return load_ratio, last_assigned, reviewer.id

    selected = min(available, key=rank)
    active_reviews = loads.get(selected.id, 0)
    reason = (
        f"Подходит для курса Go; текущая загрузка — {active_reviews} из {selected.capacity}; "
        "среди доступных ревьюеров его очередь минимальна."
    )
    return AssignmentDecision(reviewer=selected, active_reviews=active_reviews, reason=reason)


def seed_reviewers(session: Session) -> None:
    if session.scalar(select(func.count(Reviewer.id))):
        return
    session.add_all(
        [
            Reviewer(name="Ревьюер 1", specialization="Go", capacity=2),
            Reviewer(name="Ревьюер 2", specialization="Go", capacity=3),
            Reviewer(name="Ревьюер 3", specialization="Go", capacity=2),
        ]
    )
    session.commit()
