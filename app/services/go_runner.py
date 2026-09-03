from __future__ import annotations

import asyncio
import hashlib
import re
import tempfile
import time
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from app.config import Settings
from app.services.github import RepositorySnapshot
from app.services.review import ReviewFinding


ALLOWED_GO_LINES = {"1.22", "1.23", "1.24", "1.25"}


@dataclass(frozen=True)
class GoExecutionResult:
    status: str
    go_version: str | None
    dependencies_ok: bool | None
    tests_ok: bool | None
    vet_ok: bool | None
    has_tests: bool
    duration_seconds: float
    output_summary: str


def requested_go_line(snapshot: RepositorySnapshot) -> str:
    go_mod = next((content for path, content in snapshot.files.items() if path == "go.mod"), "")
    match = re.search(r"(?m)^go\s+(1\.\d+)(?:\.\d+)?\s*$", go_mod)
    line = match.group(1) if match else "1.24"
    return line if line in ALLOWED_GO_LINES else "1.24"


def _safe_write_snapshot(snapshot: RepositorySnapshot, root: Path) -> None:
    for raw_path, content in snapshot.files.items():
        relative = PurePosixPath(raw_path)
        if relative.is_absolute() or ".." in relative.parts:
            continue
        destination = root.joinpath(*relative.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")


async def _run_command(args: list[str], timeout: float) -> tuple[int, str]:
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.communicate()
        return 124, "Проверка превысила лимит времени."
    text = output.decode("utf-8", errors="replace")
    return process.returncode or 0, text[-4_000:]


async def run_go_checks(snapshot: RepositorySnapshot, settings: Settings) -> GoExecutionResult:
    started = time.monotonic()
    go_line = requested_go_line(snapshot)
    image = f"golang:{go_line}-alpine"
    has_tests = any(path.endswith("_test.go") for path in snapshot.all_paths)

    go_mod = snapshot.files.get("go.mod", "")
    go_sum = snapshot.files.get("go.sum", "")
    cache_key = hashlib.sha256(f"{go_mod}\n{go_sum}".encode()).hexdigest()[:24]
    module_dir = (settings.go_runner_cache_dir / cache_key).resolve()
    module_dir.mkdir(parents=True, exist_ok=True)
    ready_marker = module_dir / ".ready"
    build_key = hashlib.sha256(f"{go_line}:{snapshot.commit_sha}".encode()).hexdigest()[:24]
    build_dir = (settings.go_runner_build_cache_dir / build_key).resolve()
    build_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="ai-reviewer-source-") as source_dir_name:
        source_dir = Path(source_dir_name)
        _safe_write_snapshot(snapshot, source_dir)

        base = [
            "docker",
            "run",
            "--rm",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--memory",
            "768m",
            "--cpus",
            "1",
            "--pids-limit",
            "256",
            "-v",
            f"{source_dir}:/workspace:ro",
            "-w",
            "/workspace",
        ]
        dependency_args = [
            *base,
            "-v",
            f"{module_dir}:/gomod",
            "-e",
            "GOMODCACHE=/gomod",
            image,
            "sh",
            "-c",
            "go mod download all",
        ]
        try:
            if ready_marker.exists():
                dependency_code, dependency_output = 0, ""
            else:
                dependency_code, dependency_output = await _run_command(
                    dependency_args,
                    settings.go_runner_timeout_seconds,
                )
                if dependency_code == 0:
                    ready_marker.touch()
        except FileNotFoundError:
            return GoExecutionResult(
                status="unavailable",
                go_version=go_line,
                dependencies_ok=None,
                tests_ok=None,
                vet_ok=None,
                has_tests=has_tests,
                duration_seconds=round(time.monotonic() - started, 3),
                output_summary="Docker недоступен; выполнение передано ревьюеру.",
            )

        if dependency_code != 0:
            return GoExecutionResult(
                status="dependency_error",
                go_version=go_line,
                dependencies_ok=False,
                tests_ok=None,
                vet_ok=None,
                has_tests=has_tests,
                duration_seconds=round(time.monotonic() - started, 3),
                output_summary=dependency_output,
            )

        isolated = [
            *base,
            "--network",
            "none",
            "--tmpfs",
            "/tmp:rw,nosuid,size=512m",
            "-v",
            f"{module_dir}:/gomod:ro",
            "-v",
            f"{build_dir}:/gocache",
            "-e",
            "GOMODCACHE=/gomod",
            "-e",
            "GOCACHE=/gocache",
            image,
            "sh",
            "-c",
        ]
        test_code, test_output = await _run_command(
            [*isolated, "go test ./..."],
            settings.go_runner_timeout_seconds,
        )
        vet_code, vet_output = await _run_command(
            [*isolated, "go vet ./..."],
            settings.go_runner_timeout_seconds,
        )

    tests_ok = test_code == 0
    vet_ok = vet_code == 0
    status = "pass" if tests_ok and vet_ok else "fail"
    summary_parts = [
        f"go test: {'успешно' if tests_ok else 'ошибка'}",
        f"go vet: {'успешно' if vet_ok else 'ошибка'}",
        "тесты найдены" if has_tests else "тестов в проекте нет",
    ]
    failure_output = "\n".join(part for part in (test_output, vet_output) if part and part.strip())
    if failure_output and not (tests_ok and vet_ok):
        summary_parts.append(failure_output[-2_000:])
    return GoExecutionResult(
        status=status,
        go_version=go_line,
        dependencies_ok=True,
        tests_ok=tests_ok,
        vet_ok=vet_ok,
        has_tests=has_tests,
        duration_seconds=round(time.monotonic() - started, 3),
        output_summary="; ".join(summary_parts),
    )


def apply_execution_result(
    findings: list[ReviewFinding],
    execution: GoExecutionResult,
) -> list[ReviewFinding]:
    result: list[ReviewFinding] = []
    for finding in findings:
        if finding.criterion.code != "architecture.works":
            result.append(finding)
            continue
        if execution.status == "unavailable" or execution.dependencies_ok is False:
            result.append(
                replace(
                    finding,
                    status="needs_human",
                    suggested_points=None,
                    confidence=None,
                    feedback=execution.output_summary,
                )
            )
        elif execution.tests_ok and execution.vet_ok:
            points = finding.criterion.max_points if execution.has_tests else 1
            result.append(
                replace(
                    finding,
                    status="pass" if execution.has_tests else "partial",
                    suggested_points=points,
                    confidence=0.98,
                    evidence=("go test ./...", "go vet ./..."),
                    feedback=execution.output_summary,
                )
            )
        else:
            result.append(
                replace(
                    finding,
                    status="fail",
                    suggested_points=0,
                    confidence=0.98,
                    feedback=execution.output_summary,
                )
            )
    return result
