# noqa: CPY001
"""GitHub publication requests and conservative duplicate detection."""

from dataclasses import dataclass
import json
from typing import TYPE_CHECKING, Literal

import httpx

from RepoRemedy.context.github import GitHubReader, MAX_PAGES, MAX_RESPONSE_BYTES
from RepoRemedy.publication.receipts import PublicationError

if TYPE_CHECKING:
    from pydantic import JsonValue

    from RepoRemedy.propose import Proposal


@dataclass
class PublishedTarget:
    """Identity and kind of an existing or newly created GitHub object."""

    number: int
    url: str
    route: Literal["issue", "pr"]


class GitHubPublisher(GitHubReader):
    """Reuse host-bound authentication for writes without redirects or automatic retries.

    Errors never include server response bodies or credentials. Issue listing uses
    state=all and includes PRs, so a remedy is not duplicated across routes or after
    closure. Pagination failure or malformed records cannot establish absence.
    """

    def read_object(self, suffix: str = "") -> dict[str, JsonValue]:
        """Require a readable object; an inaccessible target is never absent."""
        result = self.read(suffix)
        if result.status != "available" or not isinstance(result.value, dict):
            message = "Cannot read GitHub publication state"
            raise PublicationError(message)
        return result.value

    def post(self, suffix: str, payload: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """Perform one bounded POST; callers journal uncertain writes before calling."""
        try:
            with self.client.stream(
                "POST",
                self.api_url + suffix,
                json=payload,
                headers=self.headers,
                follow_redirects=False,
                timeout=30,
            ) as response:
                if response.status_code != httpx.codes.CREATED:
                    message = (
                        f"GitHub publication HTTP {response.status_code}; inspect receipts before retrying"
                    )
                    raise PublicationError(message)
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAX_RESPONSE_BYTES:
                        message = "GitHub publication response exceeds size limit"
                        raise PublicationError(message)
                result = json.loads(raw)
                if not isinstance(result, dict):
                    message = "Unexpected GitHub publication response"
                    raise PublicationError(message)
                return result
        except (httpx.HTTPError, json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
            message = (
                "GitHub publication failed or returned an invalid response; inspect receipts before retrying"
            )
            raise PublicationError(message) from exc

    def identify_target(self, data: dict[str, JsonValue], route: Literal["issue", "pr"]) -> PublishedTarget:
        """Construct the canonical target URL rather than trusting response links."""
        number = data.get("number")
        if type(number) is not int or number <= 0:
            message = "GitHub publication response has no valid object number"
            raise PublicationError(message)
        return PublishedTarget(
            number, f"{self.web_url}/{'pull' if route == 'pr' else 'issues'}/{number}", route
        )

    def find_duplicate(self, proposal: Proposal, marker: str) -> PublishedTarget | None:
        """Find managed markers or identical titles, including closed issues and PRs."""
        assert proposal.content is not None
        matches = []
        for page in range(1, MAX_PAGES + 1):
            result = self.read("/issues", {"state": "all", "per_page": 100, "page": page})
            if result.status != "available" or not isinstance(result.value, list):
                message = "Cannot establish duplicate absence from GitHub issues and PRs"
                raise PublicationError(message)
            for item in result.value:
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("title"), str)
                    or not isinstance(item.get("body"), str | type(None))
                ):
                    message = "Malformed GitHub issue prevents duplicate checks"
                    raise PublicationError(message)
                if marker in (item.get("body") or "") or item["title"] == proposal.content.title:
                    matches.append(self.identify_target(item, "pr" if "pull_request" in item else "issue"))
            if len(result.value) < 100:  # noqa: PLR2004 - GitHub page size
                if len(matches) > 1:
                    message = "Multiple matching issues or PRs exist; reconcile them before publication"
                    raise PublicationError(message)
                return matches[0] if matches else None
        message = "Duplicate scan exceeded the pagination limit; no publication attempted"
        raise PublicationError(message)
