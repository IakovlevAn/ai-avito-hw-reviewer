import pytest

from app.services.github import parse_github_url


def test_parse_repository_url() -> None:
    location = parse_github_url("https://github.com/example/course-go")

    assert location.owner == "example"
    assert location.repository == "course-go"
    assert location.pull_number is None


def test_parse_pull_request_url() -> None:
    location = parse_github_url("github.com/example/course-go/pull/42")

    assert location.pull_number == 42


def test_reject_non_github_url() -> None:
    with pytest.raises(ValueError, match="github.com"):
        parse_github_url("https://gitlab.com/example/course-go")
