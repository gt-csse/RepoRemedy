# noqa: CPY001
"""Manifest-driven proposal batches with isolated artifacts and partial results."""

from collections import Counter
from contextlib import suppress
from pathlib import Path
from string import Formatter
from typing import Annotated, Literal
import os
import tempfile

import httpx
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from RepoRemedy.context.github import ContextError
from RepoRemedy.context.repository_context import GitSha, RepositoryPath  # noqa: TC001 - runtime fields
from RepoRemedy.models import ReportType  # noqa: TC001 - runtime Pydantic fields
from RepoRemedy.propose import RouteChoice  # noqa: TC001 - runtime Pydantic fields
from RepoRemedy.readers.common import ReportError, repository_name
from RepoRemedy.workflow import propose_repository


def _validate_template(value: str) -> str:
    """Allow literal paths and named substitutions, without attribute access or formatting."""
    fields = {"owner", "repo", "report_type"}
    if not value.strip() or any(
        field is not None and (field not in fields or spec or conversion)
        for _, field, spec, conversion in Formatter().parse(value)
    ):
        message = "Path templates accept only {owner}, {repo}, and {report_type}"
        raise ValueError(message)
    return value


class ReportTemplate(BaseModel):
    """One reader and a path expression, resolved relative to the manifest unless absolute.

    path stays a string until {owner}, {repo}, and {report_type} are substituted.
    Owner/repository case is preserved for local files; resolved paths use Path.
    """

    model_config = ConfigDict(extra="forbid")
    report_type: ReportType
    path: str

    _path_template = field_validator("path")(_validate_template)


class RepositoryJob(BaseModel):
    """Options applied independently to every report type for one repository.

    ref overrides each report's audited commit; None uses that commit or main.
    inputs is an optional path expression using the same fields as ReportTemplate.
    token_env names a host-appropriate credential; it never contains the credential.
    Repository identity is checked during processing so invalid entries do not
    prevent other repositories from running. Duplicate entries are separate runs.
    """

    model_config = ConfigDict(extra="forbid")
    repository: str
    ref: str | None = None
    inputs: str | None = None
    route: RouteChoice = "auto"
    approve_inputs: list[str] = Field(default_factory=list)
    token_env: Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")] = "REPOREMEDY_TOKEN"  # noqa: S105

    @field_validator("inputs")
    @classmethod
    def validate_inputs(cls, value: str | None) -> str | None:
        """Validate optional input-file templates without reading any files."""
        return _validate_template(value) if value is not None else None


class BatchManifest(BaseModel):
    """A nonempty repository list crossed with distinct supported report types.

    Configuration is validated before output creation or network access. Files and
    repository identities are validated per report; iteration follows list order.
    """

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    reports: list[ReportTemplate] = Field(min_length=1)
    repositories: list[RepositoryJob] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_report_types(self) -> BatchManifest:
        """Keep report-type filenames unique within each repository directory."""
        if len({report.report_type for report in self.reports}) != len(self.reports):
            message = "Declare each report type at most once"
            raise ValueError(message)
        return self


class ReportResult(BaseModel):
    """Execution outcome and readiness counts; artifact paths are relative to output.

    Paths serialize as POSIX strings; commit identities use the shared SHA contract.
    succeeded means the bundle was saved, not that its proposals are ready to publish.
    Failed entries have a sanitized error and no artifact. Original reports are not
    copied; successful bundles retain normalized findings and source provenance.
    """

    report_type: ReportType
    status: Literal["succeeded", "failed"] = "failed"
    artifact: RepositoryPath | None = None
    report_sha256: str | None = None
    base_commit: GitSha | None = None
    proposal_statuses: dict[str, int] = Field(default_factory=dict)
    error: str | None = None


class RepositoryResult(BaseModel):
    """One repository's outcomes, located by its one-based manifest position.

    directory is relative to the output root, including in the per-repository JSON.
    repository is canonical, or None for an invalid identity. summary_error means
    this record is available only in the root summary, not in its own directory.
    """

    position: int
    repository: str | None = None
    directory: RepositoryPath
    reports: list[ReportResult] = Field(default_factory=list)
    summary_error: str | None = None


class BatchSummary(BaseModel):
    """Progress checkpoint updated after each repository and at completion.

    Report counts cover only entries in repositories; planned counts cover the entire
    manifest. running has no exit_code and can omit artifacts from an interrupted
    repository. completed means processing finished, including any recorded failures.
    exit_code describes the saved run; the CLI can still fail while printing it.
    """

    schema_version: Literal[1] = 1
    status: Literal["running", "completed"] = "running"
    planned_repositories: int
    planned_reports: int
    succeeded_reports: int = 0
    failed_reports: int = 0
    repositories: list[RepositoryResult] = Field(default_factory=list)
    exit_code: int | None = None


def _save(path: Path, value: BaseModel) -> None:
    """Replace an artifact atomically; never expose truncated JSON on failed writes."""
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(value.model_dump_json(indent=2).encode())
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _resolve_template_path(template: str, job: RepositoryJob, report_type: ReportType, root: Path) -> Path:
    """Expand a validated template and identity, preserving local path case.

    root is the manifest directory. An absolute template takes precedence over root.
    """
    owner, repo = job.repository.removeprefix("https://").rstrip("/").split("/")[-2:]
    name = repo[:-4] if repo.lower().endswith(".git") else repo
    return root / template.format(owner=owner, repo=name, report_type=report_type.value)


def _run_report(
    job: RepositoryJob, template: ReportTemplate, root: Path, directory: Path, client: httpx.Client
) -> ReportResult:
    """Use the shared workflow and save its bundle, recording expected failures locally."""
    result = ReportResult(report_type=template.report_type)
    try:
        repository_name(job.repository)
        directory.mkdir(exist_ok=True)
        bundle = propose_repository(
            _resolve_template_path(template.path, job, template.report_type, root),
            template.report_type,
            job.repository,
            client,
            ref=job.ref,
            inputs=_resolve_template_path(job.inputs, job, template.report_type, root)
            if job.inputs is not None
            else None,
            route=job.route,
            approved_inputs=set(job.approve_inputs),
            token=os.environ.get(job.token_env),
        )
        artifact = Path(f"{template.report_type.value}.proposals.json")
        _save(directory / artifact, bundle)
        result.status = "succeeded"
        result.artifact = Path(directory.name) / artifact
        result.report_sha256 = bundle.report_sha256
        result.base_commit = bundle.base_commit
        result.proposal_statuses = dict(Counter(proposal.status for proposal in bundle.proposals))
    except ReportError:
        result.error = "Invalid repository identity or unreadable/malformed report"
    except ContextError:
        result.error = "Cannot collect repository context or resolve remedy inputs"
    except ValueError, OSError, httpx.HTTPError, RecursionError:
        result.error = "Cannot validate inputs, complete requests, or persist proposals"
    return result


def run_batch(manifest_path: Path, output: Path, client: httpx.Client) -> BatchSummary:
    """Run sequentially into a new directory, continuing after per-report failures.

    Configuration/output-root errors abort before processing. Report and repository
    failures are recorded without exception bodies, then processing continues.
    Root summary writes are fatal: continuing without durable accounting would
    misrepresent the run. Already-written per-repository artifacts remain intact.
    Relative input templates use manifest_path.parent; output is relative to the
    caller's working directory. The caller owns the client; this function does not
    close it. Neither this function nor the shared workflow publishes remedies.

    Return a completed summary with exit_code 0 for success, 3 for mixed results,
    or 2 for no successes. Manifest validation and root filesystem errors propagate
    to the caller; the CLI reports those as exit 2. Use a new output directory for
    every run; existing directories are never resumed or overwritten.
    """
    with manifest_path.open("rb") as stream:
        if os.fstat(stream.fileno()).st_size > 1024 * 1024:
            message = "Batch manifest exceeds the 1 MiB size limit"
            raise ValueError(message)
        # Keep the bounded read and post-read check in case the file grows after fstat.
        raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        message = "Batch manifest exceeds the 1 MiB size limit"
        raise ValueError(message)
    manifest = BatchManifest.model_validate_json(raw)
    summary = BatchSummary(
        planned_repositories=len(manifest.repositories),
        planned_reports=len(manifest.repositories) * len(manifest.reports),
    )
    output.mkdir(parents=True, exist_ok=False)
    _save(output / "summary.json", summary)
    for index, job in enumerate(manifest.repositories, 1):
        result = RepositoryResult(position=index, directory=Path(f"{index:04d}"))
        # Invalid identities become per-report failures; never persist unvalidated credentials.
        with suppress(ReportError):
            result.repository = repository_name(job.repository)
        directory = output / result.directory
        for template in manifest.reports:
            result.reports.append(_run_report(job, template, manifest_path.parent, directory, client))
        try:
            directory.mkdir(exist_ok=True)
            _save(directory / "summary.json", result)
        except OSError:
            result.summary_error = "Cannot persist repository summary; consult the batch summary"
        summary.repositories.append(result)
        summary.succeeded_reports += sum(report.status == "succeeded" for report in result.reports)
        summary.failed_reports += sum(report.status == "failed" for report in result.reports)
        _save(output / "summary.json", summary)
    failed = summary.failed_reports > 0 or any(repo.summary_error for repo in summary.repositories)
    summary.status = "completed"
    if not failed:
        summary.exit_code = 0
    elif summary.succeeded_reports:
        summary.exit_code = 3
    else:
        summary.exit_code = 2
    _save(output / "summary.json", summary)
    return summary
