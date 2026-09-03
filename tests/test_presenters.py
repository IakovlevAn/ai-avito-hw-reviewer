from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import CodeComment, Reviewer, Submission, utcnow
from app.presenters import submission_payload


def test_submission_payload_links_to_fixed_commit_and_includes_code_comments() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        reviewer = Reviewer(name="Ревьюер", specialization="Go")
        submission = Submission(
            title="Домашняя работа · Сервис курьеров · Студент",
            repository_url="https://github.com/example/course",
            repository_owner="example",
            repository_name="course",
            subdirectory="GO/Решение",
            commit_sha="abc123",
            reviewer=reviewer,
            due_at=utcnow() + timedelta(days=1),
        )
        submission.code_comments.append(
            CodeComment(file_path="cmd/main.go", line_number=12, body="Проверьте обработку ошибки")
        )
        session.add(submission)
        session.commit()

        payload = submission_payload(submission)

        assert payload["source_url"].endswith("/tree/abc123/GO/%D0%A0%D0%B5%D1%88%D0%B5%D0%BD%D0%B8%D0%B5")
        assert len(payload["code_comments"]) == 1
        assert payload["code_comments"][0]["file_path"] == "cmd/main.go"
        assert payload["code_comments"][0]["line_number"] == 12
        assert payload["code_comments"][0]["body"] == "Проверьте обработку ошибки"
