# noqa: CPY001
"""Persist publication attempts before remote writes and reconcile them on retry."""

import datetime  # noqa: TC003 - runtime models
from pathlib import Path
from typing import Literal, Self
import os
import tempfile

from pydantic import BaseModel, ConfigDict, Field

from RepoRemedy.context.github import ContextError
from RepoRemedy.context.repository_context import GitSha  # noqa: TC001 - runtime model


class PublicationError(ContextError):
    """Publication cannot safely continue; receipts retain any earlier progress."""


class PublicationReceipt(BaseModel):
    """One remedy's latest attempt, including incomplete or uncertain remote writes.

    uncertain is persisted before creating an issue or PR. If the response is lost,
    a retry must find the remote object or stop for manual reconciliation.
    A pending PR can resume only with its recorded commit on its dedicated branch.
    """

    model_config = ConfigDict(extra="forbid")
    remedy_id: str
    route: Literal["issue", "pr"]
    base_commit: GitSha
    content_sha256: str
    status: Literal["pending", "uncertain", "created", "existing"] = "pending"
    updated_at: datetime.datetime
    number: int | None = None
    url: str | None = None
    branch: str | None = None
    commit_sha: GitSha | None = None


class ReceiptJournal(BaseModel):
    """A repository-bound journal; it contains receipts, never tokens or file contents."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    repository: str
    receipts: dict[str, PublicationReceipt] = Field(default_factory=dict)


class ReceiptStore:
    """Hold an exclusive local lock and atomically replace the receipt file.

    A lock is never stolen automatically: a crash may leave it behind, requiring
    the operator to establish that no publisher remains before removing it.
    Every save flushes and fsyncs a private temporary file before replacement.
    Separate machines or different journal paths are not a distributed lock.
    """

    def __init__(self, path: Path, repository: str) -> None:
        self.path = path
        self.lock_path = path.with_name(path.name + ".lock")
        self.journal = ReceiptJournal(repository=repository)

    def __enter__(self) -> Self:
        try:
            descriptor = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            message = "Receipt journal is locked; check for another publisher before removing its .lock file"
            raise PublicationError(message) from exc
        os.close(descriptor)
        try:
            if self.path.exists():
                loaded = ReceiptJournal.model_validate_json(self.path.read_bytes())
                if loaded.repository != self.journal.repository or any(
                    key != receipt.remedy_id for key, receipt in loaded.receipts.items()
                ):
                    message = "Receipt journal repository or remedy identities do not match"
                    raise PublicationError(message)  # noqa: TRY301 - release lock on validation failure
                self.journal = loaded
            self.save()
        except BaseException:
            self.lock_path.unlink()
            raise
        return self

    def __exit__(self, *args: object) -> None:
        self.lock_path.unlink()

    def save(self) -> None:
        """Durably save each transition before any dependent remote operation."""
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(self.journal.model_dump_json(indent=2).encode())
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
