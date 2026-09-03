from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Reviewer, Submission, utcnow
from app.services.assignment import choose_reviewer


def test_choose_reviewer_uses_relative_load() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        first = Reviewer(name="Первый", specialization="Go", capacity=2)
        second = Reviewer(name="Второй", specialization="Go", capacity=4)
        session.add_all([first, second])
        session.flush()
        session.add(
            Submission(
                title="Работа",
                repository_url="https://github.com/example/repo",
                repository_owner="example",
                repository_name="repo",
                status="review_ready",
                reviewer=first,
                due_at=utcnow() + timedelta(days=1),
            )
        )
        session.commit()

        decision = choose_reviewer(session)

        assert decision.reviewer.id == second.id
        assert decision.active_reviews == 0
        assert "0 из 4" in decision.reason
