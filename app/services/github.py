from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import quote, urlparse

import httpx

from app.config import Settings


GITHUB_HOSTS = {"github.com", "www.github.com"}
RELEVANT_FILENAMES = {"dockerfile", "makefile", ".env.example", "go.mod", "go.sum"}
RELEVANT_SUFFIXES = {".go", ".sql", ".yaml", ".yml", ".md", ".toml"}


@dataclass(frozen=True)
class GitHubLocation:
    owner: str
    repository: str
    pull_number: int | None = None


@dataclass(frozen=True)
class CommitSummary:
    sha: str
    authored_at: str
    message: str
    author: str | None


@dataclass(frozen=True)
class RepositorySnapshot:
    owner: str
    repository: str
    branch: str
    commit_sha: str
    files: dict[str, str]
    all_paths: tuple[str, ...]
    commit_history: tuple[CommitSummary, ...] = ()


def parse_github_url(value: str) -> GitHubLocation:
    text = value.strip()
    if not text:
        raise ValueError("Укажите ссылку на GitHub")
    if not re.match(r"^https?://", text):
        text = f"https://{text}"
    parsed = urlparse(text)
    if parsed.hostname not in GITHUB_HOSTS:
        raise ValueError("Поддерживаются только ссылки github.com")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise ValueError("Ссылка должна вести на репозиторий или Pull Request")
    owner, repository = parts[0], parts[1].removesuffix(".git")
    pull_number = None
    if len(parts) >= 4 and parts[2] == "pull" and parts[3].isdigit():
        pull_number = int(parts[3])
    return GitHubLocation(owner=owner, repository=repository, pull_number=pull_number)


class GitHubClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "avito-ai-reviewer",
        }
        if self.settings.github_token:
            headers["Authorization"] = f"Bearer {self.settings.github_token}"
        return headers

    async def fetch_snapshot(
        self,
        location: GitHubLocation,
        subdirectory: str = "",
        commit_sha_override: str | None = None,
    ) -> RepositorySnapshot:
        timeout = httpx.Timeout(self.settings.github_timeout_seconds)
        async with httpx.AsyncClient(
            base_url="https://api.github.com",
            headers=self._headers(),
            timeout=timeout,
            follow_redirects=True,
        ) as client:
            repo_response = await client.get(f"/repos/{location.owner}/{location.repository}")
            self._raise(repo_response, "Не удалось получить репозиторий")
            repo_data = repo_response.json()

            if commit_sha_override:
                branch = repo_data["default_branch"]
                commit_sha = commit_sha_override
            elif location.pull_number is not None:
                pull_response = await client.get(
                    f"/repos/{location.owner}/{location.repository}/pulls/{location.pull_number}"
                )
                self._raise(pull_response, "Не удалось получить Pull Request")
                pull_data = pull_response.json()
                branch = pull_data["head"]["ref"]
                commit_sha = pull_data["head"]["sha"]
            else:
                branch = repo_data["default_branch"]
                commit_response = await client.get(
                    f"/repos/{location.owner}/{location.repository}/commits/{quote(branch, safe='')}"
                )
                self._raise(commit_response, "Не удалось определить версию репозитория")
                commit_sha = commit_response.json()["sha"]

            tree_response = await client.get(
                f"/repos/{location.owner}/{location.repository}/git/trees/{commit_sha}",
                params={"recursive": "1"},
            )
            self._raise(tree_response, "Не удалось прочитать структуру репозитория")
            tree = tree_response.json().get("tree", [])

            history_params: dict[str, str | int] = {"sha": commit_sha, "per_page": 30}
            if subdirectory.strip("/"):
                history_params["path"] = subdirectory.strip("/")
            history_response = await client.get(
                f"/repos/{location.owner}/{location.repository}/commits",
                params=history_params,
            )
            history: list[CommitSummary] = []
            if history_response.status_code == 200:
                for item in history_response.json():
                    commit = item.get("commit") or {}
                    author_data = commit.get("author") or {}
                    github_author = item.get("author") or {}
                    history.append(
                        CommitSummary(
                            sha=str(item.get("sha", "")),
                            authored_at=str(author_data.get("date", "")),
                            message=str(commit.get("message", ""))[:500],
                            author=github_author.get("login") or author_data.get("name"),
                        )
                    )

        normalized_prefix = subdirectory.strip("/")
        all_paths: list[str] = []
        candidates: list[tuple[str, int]] = []
        for item in tree:
            if item.get("type") != "blob":
                continue
            original_path = str(item.get("path", ""))
            if normalized_prefix:
                prefix = f"{normalized_prefix}/"
                if not original_path.startswith(prefix):
                    continue
                relative_path = original_path[len(prefix) :]
            else:
                relative_path = original_path
            if not relative_path:
                continue
            all_paths.append(relative_path)
            path_obj = PurePosixPath(relative_path)
            is_relevant = path_obj.name.lower() in RELEVANT_FILENAMES or path_obj.suffix.lower() in RELEVANT_SUFFIXES
            size = int(item.get("size") or 0)
            if is_relevant and size <= self.settings.github_max_file_bytes:
                candidates.append((original_path, size))

        candidates = candidates[: self.settings.github_max_files]
        total = 0
        bounded: list[str] = []
        for original_path, size in candidates:
            if total + size > self.settings.github_max_total_bytes:
                break
            total += size
            bounded.append(original_path)

        semaphore = asyncio.Semaphore(10)
        raw_headers = {key: value for key, value in self._headers().items() if key != "Accept"}

        async def load_file(original_path: str) -> tuple[str, str]:
            async with semaphore:
                encoded_path = "/".join(quote(part, safe="") for part in original_path.split("/"))
                url = (
                    f"https://raw.githubusercontent.com/{location.owner}/{location.repository}/"
                    f"{commit_sha}/{encoded_path}"
                )
                async with httpx.AsyncClient(headers=raw_headers, timeout=timeout, follow_redirects=True) as raw_client:
                    response = await raw_client.get(url)
                    if response.status_code != 200:
                        return original_path, ""
                    text = response.text
                if normalized_prefix:
                    display_path = original_path[len(normalized_prefix) + 1 :]
                else:
                    display_path = original_path
                return display_path, text

        loaded = await asyncio.gather(*(load_file(file_path) for file_path in bounded))
        files = {file_path: content for file_path, content in loaded if content}
        return RepositorySnapshot(
            owner=location.owner,
            repository=location.repository,
            branch=branch,
            commit_sha=commit_sha,
            files=files,
            all_paths=tuple(sorted(all_paths)),
            commit_history=tuple(history),
        )

    @staticmethod
    def _raise(response: httpx.Response, message: str) -> None:
        if response.status_code < 400:
            return
        if response.status_code == 404:
            raise ValueError(f"{message}: репозиторий или работа не найдены")
        if response.status_code == 403:
            raise ValueError(f"{message}: GitHub отклонил запрос или исчерпан лимит")
        raise ValueError(f"{message}: GitHub вернул HTTP {response.status_code}")
