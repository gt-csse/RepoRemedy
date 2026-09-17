# noqa: CPY001
"""Recorded repository evidence and its availability."""

import datetime  # noqa: TC003 - Pydantic resolves annotations
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from RepoRemedy.readers.common import repository_name


class Observation(BaseModel):
    """A read result; unavailable never means disabled or absent."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["available", "unavailable", "partial"] = "available"
    scope: Literal["commit", "live"] = "live"
    value: JsonValue = None
    reason: str | None = None


class RepositoryFile(BaseModel):
    """Content read by blob identity, without checking out or executing it."""

    model_config = ConfigDict(extra="forbid")
    path: str
    blob_sha: str = Field(pattern=r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
    status: Literal["available", "unavailable"]
    content: str | None = None
    reason: str | None = None


class RepositoryContext(BaseModel):
    """Commit-pinned file evidence and separately identified live observations."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    repository: str
    requested_ref: str
    commit_sha: str = Field(pattern=r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
    tree_sha: str = Field(pattern=r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
    started_at: datetime.datetime
    completed_at: datetime.datetime
    settings_branch: str
    tree_complete: bool
    paths: list[str]
    files: dict[str, RepositoryFile]
    observations: dict[str, Observation]
    notices: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_snapshot(self) -> RepositoryContext:
        """Reject inconsistent saved snapshots before using their fields as evidence."""
        metadata = self.observations.get("repository")
        if (
            repository_name(self.repository) != self.repository
            or metadata is None
            or metadata.status != "available"
            or not isinstance(metadata.value, dict)
        ):
            message = "Context must contain a canonical repository identity and available repository metadata"
            raise ValueError(message)
        if (
            self.started_at.tzinfo is None
            or self.completed_at.tzinfo is None
            or self.completed_at < self.started_at
        ):
            message = "Context collection timestamps must be ordered and timezone-aware"
            raise ValueError(message)
        if any(
            key != file.path or (file.status == "available" and file.content is None)
            for key, file in self.files.items()
        ):
            message = "Context file paths and availability must agree with their content"
            raise ValueError(message)
        return self
