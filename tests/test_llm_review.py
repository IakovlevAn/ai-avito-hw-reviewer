from app.services.github import CommitSummary, RepositorySnapshot
from app.services.llm_review import (
    AiUsageReason,
    AiUsageSignal,
    CriticDecision,
    CriticPayload,
    ModelReviewPayload,
    QualitativeDecision,
    apply_critic,
    merge_model_review,
    normalize_ai_usage_signal,
)
from app.services.review import evaluate


def source_snapshot() -> RepositorySnapshot:
    files = {
        "internal/usecase/courier.go": "package usecase\nfunc New() {}",
        "internal/repository/courier.go": "package repository",
    }
    return RepositorySnapshot(
        owner="example",
        repository="course-go",
        branch="main",
        commit_sha="abc123",
        files=files,
        all_paths=tuple(files),
    )


def payload(*, confidence: float = 0.91, evidence: str = "internal/usecase/courier.go") -> ModelReviewPayload:
    return ModelReviewPayload(
        qualitative_reviews=[
            QualitativeDecision(
                code="architecture.quality",
                status="pass",
                suggested_points=5,
                confidence=confidence,
                evidence_paths=[evidence],
                feedback="Логика разделена последовательно.",
            )
        ],
        ai_usage_signal=AiUsageSignal(
            status="insufficient_data",
            confidence=0.8,
            reasons=[],
            limitations="По одному снимку кода нельзя сделать надёжный вывод.",
        ),
    )


def test_model_decision_enriches_only_qualitative_criterion() -> None:
    snapshot = source_snapshot()
    deterministic = evaluate(snapshot)

    merged = merge_model_review(deterministic, payload(), snapshot)
    by_code = {finding.criterion.code: finding for finding in merged}

    assert by_code["architecture.quality"].status == "pass"
    assert by_code["architecture.quality"].suggested_points == 5
    assert by_code["architecture.quality"].confidence == 0.9
    assert by_code["architecture.quality"].evidence == ("internal/usecase/courier.go",)
    assert by_code["foundation.ping"].status == "fail"


def test_low_confidence_model_decision_is_deferred() -> None:
    snapshot = source_snapshot()
    merged = merge_model_review(evaluate(snapshot), payload(confidence=0.4), snapshot)
    finding = next(item for item in merged if item.criterion.code == "architecture.quality")

    assert finding.status == "needs_human"
    assert finding.suggested_points is None


def test_ai_usage_signal_requires_grounded_positive_evidence() -> None:
    snapshot = source_snapshot()
    unsupported = AiUsageSignal(
        status="high",
        confidence=0.95,
        reasons=[AiUsageReason(description="Резкая смена стиля", evidence_refs=["invented.go"])],
        limitations="Это только сигнал.",
    )

    normalized = normalize_ai_usage_signal(unsupported, snapshot)

    assert normalized.status == "insufficient_data"
    assert normalized.confidence == 0.0
    assert normalized.reasons == []


def test_ai_usage_signal_accepts_grounded_commit_reference() -> None:
    base = source_snapshot()
    commit = CommitSummary(
        sha="abc123",
        authored_at="2026-09-03T10:00:00Z",
        message="Implement service",
        author="student",
    )
    snapshot = RepositorySnapshot(
        owner=base.owner,
        repository=base.repository,
        branch=base.branch,
        commit_sha=base.commit_sha,
        files=base.files,
        all_paths=base.all_paths,
        commit_history=(commit,),
    )
    grounded = AiUsageSignal(
        status="medium",
        confidence=0.84,
        reasons=[
            AiUsageReason(
                description="Изменение появилось одним крупным коммитом.",
                evidence_refs=["commit:abc123"],
            )
        ],
        limitations="Сигнал требует решения ревьюера.",
    )

    normalized = normalize_ai_usage_signal(grounded, snapshot)

    assert normalized.status == "medium"
    assert normalized.confidence == 0.84
    assert normalized.reasons[0].evidence_refs == ["commit:abc123"]


def test_critic_can_only_lower_grounded_score() -> None:
    snapshot = source_snapshot()
    findings = evaluate(snapshot)
    current = next(item for item in findings if item.criterion.code == "foundation.structure")
    assert current.suggested_points == 5
    reviewed = apply_critic(
        findings,
        CriticPayload(
            decisions=[
                CriticDecision(
                    code="foundation.structure",
                    verdict="lower",
                    suggested_points=3,
                    confidence=0.86,
                    evidence_paths=["internal/usecase/courier.go"],
                    feedback="В снимке не подтверждены все заявленные границы слоёв.",
                )
            ]
        ),
        snapshot,
    )
    result = next(item for item in reviewed if item.criterion.code == "foundation.structure")

    assert result.status == "partial"
    assert result.suggested_points == 3
    assert result.confidence == 0.86


def test_critic_cannot_raise_score() -> None:
    snapshot = source_snapshot()
    findings = evaluate(snapshot)
    reviewed = apply_critic(
        findings,
        CriticPayload(
            decisions=[
                CriticDecision(
                    code="foundation.structure",
                    verdict="lower",
                    suggested_points=6,
                    confidence=0.9,
                    evidence_paths=["internal/usecase/courier.go"],
                    feedback="Попытка не является снижением.",
                )
            ]
        ),
        snapshot,
    )
    result = next(item for item in reviewed if item.criterion.code == "foundation.structure")

    assert result.status == "pass"
    assert result.suggested_points == 5


def test_unknown_evidence_path_is_deferred() -> None:
    snapshot = source_snapshot()
    merged = merge_model_review(evaluate(snapshot), payload(evidence="invented.go"), snapshot)
    finding = next(item for item in merged if item.criterion.code == "architecture.quality")

    assert finding.status == "needs_human"
    assert finding.suggested_points is None
