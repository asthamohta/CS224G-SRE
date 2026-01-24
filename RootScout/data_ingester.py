"""
data_ingester.py
- Fetches richer details from GitHub API (commit files, PR files)
- Filters to only ingest changes under WATCH_PATH_PREFIX (folder within repo)
- Emits normalized ChangeEvent objects through a sink interface (PrintSink for now)

Later you can replace PrintSink with a DB sink and add richer mapping
(service ownership, config change detection, dependency propagation).
"""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx


@dataclass(frozen=True)
class IngestConfig:
    github_token: str
    webhook_secret: str

    # If set, only ingest events from this repo
    watch_repo_owner: str
    watch_repo_name: str

    # Folder path inside repo to watch; empty means whole repo
    watch_path_prefix: str

    # Optional: explicit service_id, otherwise derived from watch_path_prefix
    service_id: str


class ChangeSink:
    """
    Sink interface so you can swap persistence without changing ingestion logic.
    For Week 1: PrintSink.
    Later: SQLite/Postgres sink.
    """
    def emit(self, change_event: Dict[str, Any]) -> None:
        raise NotImplementedError


class PrintSink(ChangeSink):
    def emit(self, change_event: Dict[str, Any]) -> None:
        print("CHANGE_EVENT:")
        print(change_event)


@dataclass(frozen=True)
class ChangeEvent:
    ingested_at: str
    event_type: str
    repo_owner: str
    repo_name: str
    service_id: str
    watch_path_prefix: str

    # One of these will be set depending on event type
    commit_sha: Optional[str] = None
    pr_number: Optional[int] = None

    # Helpful metadata
    title: Optional[str] = None
    url: Optional[str] = None

    # Changed files (filtered to watch_path_prefix)
    files: Optional[List[Dict[str, Any]]] = None


class GitHubClient:
    """
    Minimal GitHub REST API wrapper.
    - Uses token auth (PAT or GitHub App installation token)
    - Keep it reliable and simple for early weeks.
    """

    def __init__(self, token: str):
        self._token = token
        self._base = "https://api.github.com"

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "rootscout-github-ingester",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def get_commit(self, owner: str, repo: str, sha: str) -> Dict[str, Any]:
        """
        GET /repos/{owner}/{repo}/commits/{sha}
        Includes:
        - commit message
        - author timestamp
        - files with patches (best-effort)
        """
        url = f"{self._base}/repos/{owner}/{repo}/commits/{sha}"
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(url, headers=self._headers())
            if r.status_code >= 400:
                raise RuntimeError(f"GitHub get_commit failed: {r.status_code} {r.text}")
            return r.json()

    async def list_pull_request_files(self, owner: str, repo: str, pr_number: int) -> List[Dict[str, Any]]:
        """
        GET /repos/{owner}/{repo}/pulls/{pull_number}/files
        Returns list of files changed in PR (paginated).
        """
        files: List[Dict[str, Any]] = []
        url = f"{self._base}/repos/{owner}/{repo}/pulls/{pr_number}/files?per_page=100"
        async with httpx.AsyncClient(timeout=20) as client:
            while url:
                r = await client.get(url, headers=self._headers())
                if r.status_code >= 400:
                    raise RuntimeError(f"GitHub list_pull_request_files failed: {r.status_code} {r.text}")
                files.extend(r.json())

                next_url = None
                link = r.headers.get("Link", "")
                # Very small parser for GitHub pagination links
                for part in link.split(","):
                    part = part.strip()
                    if 'rel="next"' in part:
                        left = part.find("<")
                        right = part.find(">")
                        if left != -1 and right != -1 and right > left:
                            next_url = part[left + 1:right]
                url = next_url

        return files


class GitHubIngester:
    def __init__(self, config: IngestConfig, sink: ChangeSink):
        self._config = config
        self._sink = sink
        self._gh = GitHubClient(token=config.github_token)

    def _should_ingest_repo(self, owner: str, repo: str) -> bool:
        if self._config.watch_repo_owner and owner != self._config.watch_repo_owner:
            return False
        if self._config.watch_repo_name and repo != self._config.watch_repo_name:
            return False
        return True

    def _derive_service_id(self) -> str:
        if self._config.service_id:
            return self._config.service_id
        if self._config.watch_path_prefix:
            # Example: "services/cart" -> "cart"
            parts = [p for p in self._config.watch_path_prefix.split("/") if p]
            if parts:
                return parts[-1]
        return "unknown-service"

    def _filter_files(self, files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        prefix = self._config.watch_path_prefix.strip("/")
        if not prefix:
            return files

        filtered: List[Dict[str, Any]] = []
        for f in files:
            filename = (f.get("filename") or f.get("path") or "").lstrip("/")
            if filename.startswith(prefix + "/") or filename == prefix:
                filtered.append(f)
        return filtered

    async def handle_event(self, event_type: str, repo_owner: str, repo_name: str, payload: Dict[str, Any]) -> None:
        """
        All GitHub + ingestion logic lives here.
        main.py only extracts repo_owner/repo_name and dispatches.
        """
        try:
            if not self._should_ingest_repo(repo_owner, repo_name):
                return

            if event_type == "push":
                await self._handle_push(repo_owner, repo_name, payload)
                return

            if event_type == "pull_request":
                await self._handle_pull_request(repo_owner, repo_name, payload)
                return

            # Ignore anything else for Week 1
            return

        except Exception as e:
            # You can replace this with structured logging later
            print(f"[GitHubIngester] Error handling {event_type} for {repo_owner}/{repo_name}: {e}")

    async def _handle_push(self, owner: str, repo: str, payload: Dict[str, Any]) -> None:
        service_id = self._derive_service_id()

        # Prefer commits array from webhook. Fallback to payload["after"].
        commits = payload.get("commits") or []
        shas = [c.get("id") for c in commits if c.get("id")]  # commit SHA strings
        if not shas and payload.get("after"):
            shas = [payload["after"]]

        for sha in shas:
            commit = await self._gh.get_commit(owner, repo, sha)

            files = commit.get("files") or []
            # Normalize to include "filename" key (GitHub uses filename)
            filtered_files = self._filter_files(files)

            # If watching a prefix and nothing relevant changed, skip emitting
            if self._config.watch_path_prefix and not filtered_files:
                continue

            message = ((commit.get("commit") or {}).get("message")) or None
            html_url = commit.get("html_url") or None

            event = ChangeEvent(
                ingested_at=datetime.now(timezone.utc).isoformat(),
                event_type="push",
                repo_owner=owner,
                repo_name=repo,
                service_id=service_id,
                watch_path_prefix=self._config.watch_path_prefix,
                commit_sha=sha,
                title=message,
                url=html_url,
                files=filtered_files,
            )
            self._sink.emit(asdict(event))

    async def _handle_pull_request(self, owner: str, repo: str, payload: Dict[str, Any]) -> None:
        service_id = self._derive_service_id()

        action = payload.get("action") or ""
        pr = payload.get("pull_request") or {}
        pr_number = pr.get("number")

        # Only ingest PR actions that represent meaningful changes
        meaningful_actions = {"opened", "reopened", "synchronize", "ready_for_review", "edited"}
        if action and action not in meaningful_actions:
            return

        if not isinstance(pr_number, int):
            return

        pr_title = pr.get("title") or None
        pr_url = pr.get("html_url") or None

        files = await self._gh.list_pull_request_files(owner, repo, pr_number)
        # GitHub PR files use "filename"
        filtered_files = self._filter_files(files)

        if self._config.watch_path_prefix and not filtered_files:
            return

        event = ChangeEvent(
            ingested_at=datetime.now(timezone.utc).isoformat(),
            event_type="pull_request",
            repo_owner=owner,
            repo_name=repo,
            service_id=service_id,
            watch_path_prefix=self._config.watch_path_prefix,
            pr_number=pr_number,
            title=pr_title,
            url=pr_url,
            files=filtered_files,
        )
        self._sink.emit(asdict(event))
