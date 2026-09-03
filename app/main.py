from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.database import SessionLocal, create_schema, get_session
from app.models import AuditEvent, CriterionResult, Reviewer, Submission, utcnow
from app.presenters import submission_payload
from app.rubric import RUBRIC, TOTAL_POINTS
from app.services.assignment import ACTIVE_STATUSES, choose_reviewer, seed_reviewers
from app.services.export import build_submission_workbook
from app.services.github import GitHubClient, parse_github_url
from app.services.notifications import send_telegram
from app.services.review import evaluate, evidence_json


settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Path("data").mkdir(exist_ok=True)
    create_schema()
    with SessionLocal() as session:
        seed_reviewers(session)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SubmissionCreate(BaseModel):
    repository_url: str = Field(min_length=8)
    subdirectory: str = ""
    title: str | None = None
    due_hours: int = Field(default=settings.review_due_hours, ge=1, le=168)


class CriterionUpdate(BaseModel):
    final_points: int = Field(ge=0)
    final_feedback: str = Field(default="", max_length=4000)


def get_submission_or_404(session: Session, submission_id: int) -> Submission:
    item = session.scalar(
        select(Submission)
        .where(Submission.id == submission_id)
        .options(
            selectinload(Submission.reviewer),
            selectinload(Submission.criteria),
            selectinload(Submission.events),
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Работа не найдена")
    return item


async def process_submission(submission_id: int) -> None:
    location = None
    try:
        with SessionLocal() as session:
            submission = session.get(Submission, submission_id)
            if submission is None:
                return
            submission.status = "processing"
            submission.events.append(AuditEvent(kind="review_started", message="Началась предварительная проверка"))
            location = parse_github_url(submission.repository_url)
            session.commit()

        snapshot = await GitHubClient(settings).fetch_snapshot(location, submission.subdirectory)
        findings = evaluate(snapshot)

        with SessionLocal() as session:
            submission = session.get(Submission, submission_id)
            if submission is None:
                return
            submission.branch = snapshot.branch
            submission.commit_sha = snapshot.commit_sha
            submission.criteria.clear()
            for position, finding in enumerate(findings, start=1):
                submission.criteria.append(
                    CriterionResult(
                        position=position,
                        section=finding.criterion.section,
                        code=finding.criterion.code,
                        title=finding.criterion.title,
                        max_points=finding.criterion.max_points,
                        status=finding.status,
                        suggested_points=finding.suggested_points,
                        final_points=finding.suggested_points,
                        confidence=finding.confidence,
                        evidence_json=evidence_json(finding),
                        feedback=finding.feedback,
                        final_feedback=finding.feedback,
                    )
                )
            assessed = [finding for finding in findings if finding.suggested_points is not None]
            submission.suggested_points = sum(finding.suggested_points or 0 for finding in assessed)
            submission.assessed_points = sum(finding.criterion.max_points for finding in assessed)
            submission.max_points = TOTAL_POINTS
            submission.status = "review_ready"
            submission.events.append(
                AuditEvent(
                    kind="review_ready",
                    message=f"Черновик готов: оценено {submission.assessed_points} из {TOTAL_POINTS} возможных баллов",
                )
            )
            reviewer_name = submission.reviewer.name if submission.reviewer else "ревьюер"
            session.commit()

        await send_telegram(
            settings,
            f"Avito AI Reviewer: работа #{submission_id} готова к проверке. Назначен {reviewer_name}.",
        )
    except Exception as exc:  # noqa: BLE001 - boundary converts failures into product state
        message = str(exc)[:500] or "Неизвестная ошибка проверки"
        with SessionLocal() as session:
            submission = session.get(Submission, submission_id)
            if submission is None:
                return
            submission.status = "error"
            submission.error_message = message
            submission.events.append(AuditEvent(kind="review_error", message=message))
            session.commit()


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/dashboard")
def dashboard(session: Session = Depends(get_session)) -> dict:
    submissions = list(
        session.scalars(
            select(Submission)
            .options(selectinload(Submission.reviewer), selectinload(Submission.criteria))
            .order_by(Submission.created_at.desc())
        )
    )
    loads = {
        reviewer_id: count
        for reviewer_id, count in session.execute(
            select(Submission.reviewer_id, func.count(Submission.id))
            .where(Submission.status.in_(ACTIVE_STATUSES), Submission.reviewer_id.is_not(None))
            .group_by(Submission.reviewer_id)
        )
    }
    reviewers = list(session.scalars(select(Reviewer).order_by(Reviewer.id)))
    now = utcnow()
    return {
        "stats": {
            "total": len(submissions),
            "ready": sum(item.status == "review_ready" for item in submissions),
            "approved": sum(item.status == "approved" for item in submissions),
            "overdue": sum(item.status != "approved" and item.due_at < now for item in submissions),
        },
        "reviewers": [
            {
                "id": reviewer.id,
                "name": reviewer.name,
                "specialization": reviewer.specialization,
                "capacity": reviewer.capacity,
                "active_reviews": loads.get(reviewer.id, 0),
            }
            for reviewer in reviewers
        ],
        "submissions": [submission_payload(item, include_details=False) for item in submissions],
    }


@app.post("/api/submissions", status_code=status.HTTP_202_ACCEPTED)
def create_submission(
    payload: SubmissionCreate,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> dict:
    try:
        location = parse_github_url(payload.repository_url)
        decision = choose_reviewer(session)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    decision.reviewer.last_assigned_at = utcnow()
    title = payload.title or f"{location.owner}/{location.repository}"
    submission = Submission(
        title=title,
        repository_url=payload.repository_url,
        repository_owner=location.owner,
        repository_name=location.repository,
        subdirectory=payload.subdirectory.strip("/"),
        reviewer=decision.reviewer,
        status="assigned",
        due_at=utcnow() + timedelta(hours=payload.due_hours),
        max_points=TOTAL_POINTS,
    )
    submission.events.append(AuditEvent(kind="received", message="Работа получена из GitHub"))
    submission.events.append(AuditEvent(kind="assigned", message=decision.reason))
    session.add(submission)
    session.commit()
    session.refresh(submission)
    background_tasks.add_task(process_submission, submission.id)
    return submission_payload(get_submission_or_404(session, submission.id))


@app.get("/api/submissions/{submission_id}")
def get_submission(submission_id: int, session: Session = Depends(get_session)) -> dict:
    return submission_payload(get_submission_or_404(session, submission_id))


@app.patch("/api/submissions/{submission_id}/criteria/{criterion_id}")
def update_criterion(
    submission_id: int,
    criterion_id: int,
    payload: CriterionUpdate,
    session: Session = Depends(get_session),
) -> dict:
    submission = get_submission_or_404(session, submission_id)
    criterion = next((item for item in submission.criteria if item.id == criterion_id), None)
    if criterion is None:
        raise HTTPException(status_code=404, detail="Критерий не найден")
    if payload.final_points > criterion.max_points:
        raise HTTPException(status_code=422, detail="Балл выше максимума по критерию")
    criterion.final_points = payload.final_points
    criterion.final_feedback = payload.final_feedback.strip() or criterion.feedback
    criterion.human_decision = "accepted" if payload.final_points == criterion.suggested_points else "edited"
    submission.status = "human_review"
    submission.events.append(
        AuditEvent(kind="criterion_updated", message=f"Ревьюер обновил критерий: {criterion.title}")
    )
    session.commit()
    return submission_payload(get_submission_or_404(session, submission_id))


@app.post("/api/submissions/{submission_id}/approve")
async def approve_submission(submission_id: int, session: Session = Depends(get_session)) -> dict:
    submission = get_submission_or_404(session, submission_id)
    unresolved = [item for item in submission.criteria if item.final_points is None]
    if unresolved:
        raise HTTPException(
            status_code=409,
            detail=f"Нужно проверить ещё {len(unresolved)} критериев без предложенного балла",
        )
    submission.status = "approved"
    submission.approved_at = utcnow()
    submission.events.append(AuditEvent(kind="approved", message="Ревьюер подтвердил итоговый результат"))
    session.commit()
    await send_telegram(settings, f"Avito AI Reviewer: работа #{submission.id} проверена и подтверждена.")
    return submission_payload(get_submission_or_404(session, submission_id))


@app.get("/api/submissions/{submission_id}/export.xlsx")
def export_submission(submission_id: int, session: Session = Depends(get_session)) -> StreamingResponse:
    submission = get_submission_or_404(session, submission_id)
    buffer = build_submission_workbook(submission)
    filename = f"submission-{submission.id}-review.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/rubric")
def rubric() -> dict:
    return {
        "total_points": TOTAL_POINTS,
        "criteria": [
            {
                "code": item.code,
                "section": item.section,
                "title": item.title,
                "max_points": item.max_points,
            }
            for item in RUBRIC
        ],
    }


dist_dir = settings.web_dist_dir
if dist_dir.exists():
    assets_dir = dist_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{path_name:path}", include_in_schema=False)
    def web_app(path_name: str) -> Response:
        candidate = dist_dir / path_name
        if path_name and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist_dir / "index.html")
else:

    @app.get("/", include_in_schema=False)
    def development_hint() -> dict[str, str]:
        return {
            "message": "Frontend не собран. Запустите npm run dev в каталоге web.",
            "api_docs": "/docs",
        }
