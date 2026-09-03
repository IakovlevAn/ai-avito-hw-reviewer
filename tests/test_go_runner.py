from app.services.github import RepositorySnapshot
from app.services.go_runner import GoExecutionResult, apply_execution_result, requested_go_line
from app.services.review import evaluate


def snapshot(go_version: str = "1.25.3") -> RepositorySnapshot:
    files = {
        "go.mod": f"module example\n\ngo {go_version}\n",
        "main.go": "package main\nfunc main() {}\n",
    }
    return RepositorySnapshot(
        owner="example",
        repository="repo",
        branch="main",
        commit_sha="abc",
        files=files,
        all_paths=tuple(files),
    )


def test_requested_go_line_uses_supported_minor_version() -> None:
    assert requested_go_line(snapshot("1.25.3")) == "1.25"
    assert requested_go_line(snapshot("1.99")) == "1.24"


def test_successful_build_without_tests_gets_partial_working_score() -> None:
    findings = evaluate(snapshot())
    execution = GoExecutionResult(
        status="pass",
        go_version="1.25",
        dependencies_ok=True,
        tests_ok=True,
        vet_ok=True,
        has_tests=False,
        duration_seconds=1.2,
        output_summary="go test: успешно; go vet: успешно; тестов в проекте нет",
    )

    reviewed = apply_execution_result(findings, execution)
    result = next(item for item in reviewed if item.criterion.code == "architecture.works")

    assert result.status == "partial"
    assert result.suggested_points == 1
    assert result.confidence == 0.98


def test_failed_build_sets_zero_working_score() -> None:
    findings = evaluate(snapshot())
    execution = GoExecutionResult(
        status="fail",
        go_version="1.25",
        dependencies_ok=True,
        tests_ok=False,
        vet_ok=False,
        has_tests=False,
        duration_seconds=1.2,
        output_summary="go test: ошибка; go vet: ошибка",
    )

    reviewed = apply_execution_result(findings, execution)
    result = next(item for item in reviewed if item.criterion.code == "architecture.works")

    assert result.status == "fail"
    assert result.suggested_points == 0
