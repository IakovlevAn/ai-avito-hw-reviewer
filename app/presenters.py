from __future__ import annotations

import json
from datetime import datetime

from app.models import CriterionResult, Submission


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def criterion_payload(item: CriterionResult) -> dict:
    return {
        "id": item.id,
        "code": item.code,
        "section": item.section,
        "title": item.title,
        "max_points": item.max_points,
        "status": item.status,
        "suggested_points": item.suggested_points,
        "final_points": item.final_points,
        "confidence": item.confidence,
        "evidence": json.loads(item.evidence_json or "[]"),
        "feedback": item.feedback,
        "final_feedback": item.final_feedback,
        "human_decision": item.human_decision,
    }


def submission_payload(submission: Submission, *, include_details: bool = True) -> dict:
    criteria = [criterion_payload(item) for item in submission.criteria] if include_details else []
    confirmed_points = sum((item.final_points or 0) for item in submission.criteria)
    unresolved = sum(item.final_points is None for item in submission.criteria)
    ai_assessment = submission.ai_usage_assessment
    return {
        "id": submission.id,
        "title": submission.title,
        "repository_url": submission.repository_url,
        "repository_owner": submission.repository_owner,
        "repository_name": submission.repository_name,
        "subdirectory": submission.subdirectory,
        "branch": submission.branch,
        "commit_sha": submission.commit_sha,
        "status": submission.status,
        "error_message": submission.error_message,
        "reviewer": (
            {"id": submission.reviewer.id, "name": submission.reviewer.name}
            if submission.reviewer
            else None
        ),
        "suggested_points": submission.suggested_points,
        "assessed_points": submission.assessed_points,
        "confirmed_points": confirmed_points,
        "max_points": submission.max_points,
        "unresolved_criteria": unresolved,
        "created_at": iso(submission.created_at),
        "due_at": iso(submission.due_at),
        "approved_at": iso(submission.approved_at),
        "criteria": criteria,
        "ai_usage_signal": (
            {
                "status": ai_assessment.status,
                "confidence": ai_assessment.confidence,
                "reasons": json.loads(ai_assessment.reasons_json or "[]"),
                "limitations": ai_assessment.limitations,
                "model_version": ai_assessment.model_version,
            }
            if ai_assessment
            else {
                "status": "needs_review",
                "confidence": None,
                "reasons": [],
                "limitations": "Сигнал не влияет на баллы и требует отдельного решения ревьюера.",
                "model_version": None,
            }
        ),
        "model_runs": (
            [
                {
                    "provider": run.provider,
                    "model": run.model,
                    "status": run.status,
                    "prompt_tokens": run.prompt_tokens,
                    "completion_tokens": run.completion_tokens,
                    "error_type": run.error_type,
                    "created_at": iso(run.created_at),
                }
                for run in submission.model_runs
            ]
            if include_details
            else []
        ),
        "events": (
            [
                {
                    "id": event.id,
                    "kind": event.kind,
                    "message": event.message,
                    "created_at": iso(event.created_at),
                }
                for event in submission.events
            ]
            if include_details
            else []
        ),
    }
