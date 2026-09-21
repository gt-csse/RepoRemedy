# noqa: CPY001
"""Resolve catalog inputs from recorded context without rendering or selecting proposals."""

import hashlib
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from RepoRemedy.catalog import load_catalog
from RepoRemedy.context.github import ContextError
from RepoRemedy.context.repository_context import GitSha  # noqa: TC001 - runtime model
from RepoRemedy.context.inputs import ResolvedInput, resolve_inputs

if TYPE_CHECKING:
    from RepoRemedy.context.repository_context import RepositoryContext
    from RepoRemedy.models import Report


class TemplateInputs(BaseModel):
    """Inputs for one declared route; completeness is not approval or applicability."""

    remedy_id: str | None
    origin: str
    check: str
    route: Literal["issue", "pr"]
    status: Literal["complete", "needs-input", "unavailable", "unsupported"]
    inputs: dict[str, ResolvedInput] = Field(default_factory=dict)
    missing_inputs: dict[str, str] = Field(default_factory=dict)
    reason: str | None = None


class InputResolution(BaseModel):
    """Recorded input values with report, context and catalog provenance."""

    schema_version: Literal[1] = 1
    repository: str
    commit_sha: GitSha
    report_sha256: str
    context_sha256: str
    catalog_sha256: str
    templates: list[TemplateInputs]
    notices: list[str]


PROTECTED_INPUTS = {"repository", "origin", "check", "evidence", "observed_state", "target"}


def resolve_template_inputs(
    report: Report,
    context: RepositoryContext,
    supplied: dict[str, dict[str, str]] | None = None,
) -> InputResolution:
    """Resolve both declared routes, keeping unknown checks and missing decisions visible.

    This operation combines catalog inputs with explicit user values; it does not
    select routes, render proposals or establish approval. Multi-part intermediate
    results use named dataclass fields; InputResolution is the saved JSON contract.
    """
    if report.repository != context.repository:
        message = "Report and context identify different repositories"
        raise ContextError(message)
    catalog = load_catalog()
    remedies = catalog.remedies
    supplied = supplied or {}
    for identifier, fields in supplied.items():
        if identifier not in remedies:
            message = "Inputs refer to an unknown remedy"
            raise ContextError(message)
        remedy = remedies[identifier]
        allowed = set(remedy.issue.required_inputs) | (set(remedy.pr.required_inputs) if remedy.pr else set())
        if not isinstance(fields, dict) or set(fields) - allowed or set(fields) & PROTECTED_INPUTS:
            message = "Inputs include unknown or report/context-owned fields"
            raise ContextError(message)
        if any(not isinstance(value, str) or not value.strip() for value in fields.values()):
            message = "Supplied template inputs must be nonempty strings"
            raise ContextError(message)
    lookup = {
        (origin, check): identifier
        for identifier, remedy in remedies.items()
        for origin, checks in remedy.sources.items()
        for check in checks
    }
    resolved = []
    for issue in report.issues:
        identifier = lookup.get((issue.origin, issue.check))
        if identifier is None or issue.status == "unavailable":
            resolved.append(
                TemplateInputs(
                    remedy_id=identifier,
                    origin=issue.origin,
                    check=issue.check,
                    route="issue",
                    status="unsupported" if identifier is None else "unavailable",
                    reason="No catalog mapping"
                    if identifier is None
                    else "Unavailable evidence does not establish a defect",
                )
            )
            continue
        remedy = remedies[identifier]
        for kind, route in (("issue", remedy.issue), ("pr", remedy.pr)):
            if route is None:
                continue
            resolved_inputs = resolve_inputs(context, identifier, remedy, route, issue)
            values = resolved_inputs.values
            missing = resolved_inputs.missing_inputs
            for key, value in supplied.get(identifier, {}).items():
                if key in route.required_inputs:
                    values[key] = ResolvedInput(value=value, source="user input; approval not established")
                    missing.pop(key, None)
            resolved.append(
                TemplateInputs(
                    remedy_id=identifier,
                    origin=issue.origin,
                    check=issue.check,
                    route=kind,
                    status="needs-input" if missing else "complete",
                    inputs=values,
                    missing_inputs=missing,
                )
            )
    notices = [
        *report.notices,
        *context.notices,
        "Input completeness does not establish applicability, approval or publication readiness.",
        "Both declared routes are represented. Rendering, route selection, guard evaluation and publication are deferred.",
        "Live settings are observations from collection time, not historical settings at the recorded commit.",
    ]
    if report.source.audited_commit and report.source.audited_commit.lower() != context.commit_sha:
        notices.append(
            "The report's audited commit differs from the context commit; findings must be rechecked against the reviewed state."
        )
    return InputResolution(
        repository=context.repository,
        commit_sha=context.commit_sha,
        report_sha256=report.source.sha256,
        context_sha256=hashlib.sha256(context.model_dump_json().encode()).hexdigest(),
        catalog_sha256=catalog.sha256,
        templates=resolved,
        notices=notices,
    )
