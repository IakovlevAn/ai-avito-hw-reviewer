from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.rubric import Criterion, RUBRIC
from app.services.github import RepositorySnapshot


@dataclass(frozen=True)
class ReviewFinding:
    criterion: Criterion
    status: str
    suggested_points: int | None
    confidence: float | None
    evidence: tuple[str, ...]
    feedback: str


def _matching_paths(snapshot: RepositorySnapshot, pattern: str) -> list[str]:
    regex = re.compile(pattern, re.IGNORECASE)
    return [path for path in snapshot.all_paths if regex.search(path)]


def _matching_content(snapshot: RepositorySnapshot, patterns: tuple[str, ...]) -> list[str]:
    found: list[str] = []
    regexes = [re.compile(pattern, re.IGNORECASE | re.MULTILINE) for pattern in patterns]
    for path, content in snapshot.files.items():
        if any(regex.search(content) for regex in regexes):
            found.append(path)
    return found


def _all_content_patterns(snapshot: RepositorySnapshot, patterns: tuple[str, ...]) -> list[str]:
    evidence: list[str] = []
    for pattern in patterns:
        matches = _matching_content(snapshot, (pattern,))
        if not matches:
            return []
        evidence.extend(matches)
    return list(dict.fromkeys(evidence))


def _finding(
    criterion: Criterion,
    matched: list[str],
    *,
    missing_feedback: str,
    success_feedback: str,
    confidence: float = 0.92,
) -> ReviewFinding:
    unique = tuple(dict.fromkeys(matched))[:5]
    if unique:
        return ReviewFinding(
            criterion=criterion,
            status="pass",
            suggested_points=criterion.max_points,
            confidence=confidence,
            evidence=unique,
            feedback=success_feedback,
        )
    return ReviewFinding(
        criterion=criterion,
        status="fail",
        suggested_points=0,
        confidence=0.72,
        evidence=(),
        feedback=missing_feedback,
    )


def _human(criterion: Criterion, reason: str) -> ReviewFinding:
    return ReviewFinding(
        criterion=criterion,
        status="needs_human",
        suggested_points=None,
        confidence=None,
        evidence=(),
        feedback=reason,
    )


def evaluate(snapshot: RepositorySnapshot) -> list[ReviewFinding]:
    findings: list[ReviewFinding] = []
    for criterion in RUBRIC:
        if criterion.qualitative:
            findings.append(
                _human(
                    criterion,
                    "Критерий требует инженерного суждения. Система оставила его ревьюеру без предложенного балла.",
                )
            )
            continue

        rule = criterion.rule
        matched: list[str]
        missing = "Не найдено достаточного подтверждения выполнения требования."
        success = "В работе найдено подтверждение выполнения требования."

        if rule == "project_structure":
            matched = _matching_paths(snapshot, r"(^|/)cmd/|(^|/)internal/|(^|/)pkg/")
        elif rule == "http_server":
            matched = _matching_content(snapshot, (r"http\.Server", r"http\.ListenAndServe"))
        elif rule == "port_env":
            matched = _matching_content(snapshot, (r"Getenv\([\"']PORT", r"LookupEnv\([\"']PORT", r"envconfig"))
        elif rule == "port_flag":
            matched = _matching_content(snapshot, (r"[\"']port[\"']", r"--port", r"\.Int\w*\([\"']port"))
        elif rule == "ping":
            matched = _all_content_patterns(snapshot, (r"[\"']/ping[\"']", r"[\"']pong[\"']"))
        elif rule == "healthcheck":
            route_matches = _matching_content(snapshot, (r"healthcheck",))
            response_matches = _matching_content(snapshot, (r"StatusNoContent", r"\b204\b"))
            matched = (
                list(dict.fromkeys(route_matches + response_matches))
                if route_matches and response_matches
                else []
            )
        elif rule == "graceful_shutdown":
            signal_matches = _matching_content(snapshot, (r"signal\.Notify", r"NotifyContext"))
            shutdown_matches = _matching_content(snapshot, (r"\.Shutdown\(",))
            matched = (
                list(dict.fromkeys(signal_matches + shutdown_matches))
                if signal_matches and shutdown_matches
                else []
            )
        elif rule == "shutdown_log":
            matched = _matching_content(snapshot, (r"Shutting down service-courier",))
        elif rule == "postgres":
            matched = _matching_content(snapshot, (r"pgx", r"postgres", r"DATABASE_URL", r"DB_HOST"))
        elif rule == "goose":
            matched = list(
                dict.fromkeys(
                    _matching_paths(snapshot, r"migration")
                    + _matching_content(snapshot, (r"goose", r"\+goose Up"))
                )
            )
        elif rule == "courier_schema":
            matched = _all_content_patterns(
                snapshot,
                (r"CREATE\s+TABLE\s+(IF\s+NOT\s+EXISTS\s+)?couriers", r"phone\s+.*UNIQUE"),
            )
        elif rule == "get_courier":
            matched = _matching_content(snapshot, (r"GET.*?/courier/", r"Get\([\"']/courier/"))
        elif rule == "get_couriers":
            matched = _matching_content(snapshot, (r"GET.*?/couriers", r"Get\([\"']/couriers"))
        elif rule == "post_courier":
            matched = _matching_content(snapshot, (r"POST.*?/courier", r"Post\([\"']/courier"))
        elif rule == "put_courier":
            matched = _matching_content(snapshot, (r"PUT.*?/courier", r"Put\([\"']/courier"))
        elif rule == "sql_placeholders":
            matched = _matching_content(snapshot, (r"\$1", r"\$2"))
        elif rule == "layers":
            required = (r"(^|/)handler", r"(^|/)usecase", r"(^|/)repository", r"(^|/)model")
            layer_hits = [_matching_paths(snapshot, part) for part in required]
            matched = [paths[0] for paths in layer_hits if paths] if all(layer_hits) else []
        elif rule == "handler_interface":
            matched = _matching_content(snapshot, (r"type\s+\w*(Handler|Usecase|Service)\w*\s+interface",))
        elif rule == "repository_interface":
            matched = _matching_content(snapshot, (r"type\s+\w*Repositor\w*\s+interface",))
        elif rule == "constructors":
            matched = _matching_content(snapshot, (r"func\s+New\w+\s*\(",))
        elif rule == "main_wiring":
            matched = [path for path in _matching_paths(snapshot, r"(^|/)main\.go$") if "New" in snapshot.files.get(path, "")]
        elif rule == "tests":
            matched = _matching_paths(snapshot, r"_test\.go$")
        else:
            findings.append(_human(criterion, "Для критерия ещё не настроена надёжная автоматическая проверка."))
            continue

        findings.append(
            _finding(
                criterion,
                matched,
                missing_feedback=missing,
                success_feedback=success,
            )
        )
    return findings


def evidence_json(finding: ReviewFinding) -> str:
    return json.dumps(list(finding.evidence), ensure_ascii=False)
