# noqa: CPY001
"""Bounded, read-only GitHub API access with host-specific authentication."""

import json
from typing import TYPE_CHECKING
from urllib.parse import quote

import httpx

from RepoRemedy.context.models import Observation
from RepoRemedy.readers.common import repository_name

if TYPE_CHECKING:
    from pydantic import JsonValue

MAX_RESPONSE_BYTES = 10 * 1024 * 1024
MAX_PAGES = 10


class ContextError(ValueError):
    """Repository context cannot be collected or used reliably."""


def repository_address(repository: str) -> tuple[str, str, str]:
    """Return canonical identity, web base and API repository path."""
    identity = repository_name(repository)
    parts = identity.split("/")
    host, owner, name = parts if len(parts) == 3 else ["github.com", *parts]  # noqa: PLR2004
    api = "https://api.github.com" if host == "github.com" else f"https://{host}/api/v3"
    return identity, f"https://{host}/{owner}/{name}", f"{api}/repos/{owner}/{name}"


class GitHubReader:
    """Read one repository without redirects, cross-host links or error-body disclosure."""

    def __init__(self, repository: str, client: httpx.Client, token: str | None = None) -> None:
        self.repository, self.web_url, self.api_url = repository_address(repository)
        self.client = client
        self.headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def read(self, suffix: str = "", params: dict[str, str | int] | None = None) -> Observation:
        """Return sanitized availability rather than interpreting inaccessible data as absent."""
        try:
            with self.client.stream(
                "GET",
                self.api_url + suffix,
                params=params,
                headers=self.headers,
                follow_redirects=False,
                timeout=30,
            ) as response:
                if response.status_code != httpx.codes.OK:
                    return Observation(status="unavailable", reason=f"GitHub HTTP {response.status_code}")
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAX_RESPONSE_BYTES:
                        return Observation(status="unavailable", reason="API response exceeds size limit")
                return Observation(value=json.loads(raw))
        except httpx.HTTPError, ValueError, RecursionError:
            return Observation(status="unavailable", reason="GitHub request failed or returned invalid JSON")

    def pages(self, suffix: str, key: str | None = None) -> Observation:
        """Collect bounded pagination using local page numbers, never server-provided URLs."""
        items: list[JsonValue] = []
        for page in range(1, MAX_PAGES + 1):
            result = self.read(suffix, {"per_page": 100, "page": page})
            value = result.value
            batch = value.get(key) if key and isinstance(value, dict) else value
            if result.status != "available" or not isinstance(batch, list):
                return Observation(
                    status="partial" if items else "unavailable",
                    value=items,
                    reason=result.reason or "Unexpected paginated response",
                )
            items.extend(batch)
            if len(batch) < 100:  # noqa: PLR2004 - GitHub page size
                return Observation(value=items)
        return Observation(status="partial", value=items, reason="Pagination limit reached")


def segment(value: str) -> str:
    """Encode refs and paths as one API segment."""
    return quote(value, safe="")
