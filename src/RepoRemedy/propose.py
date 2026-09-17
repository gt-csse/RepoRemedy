# noqa: CPY001
"""Prepare concrete catalog remedies for review and a separate publication step."""

from dataclasses import dataclass
from difflib import unified_diff
from string import Template
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from RepoRemedy.catalog import Remedy, Route, read_asset, load_catalog
from RepoRemedy.context.inputs import ResolvedInput, find_matching_files
from RepoRemedy.context.repository_context import (  # noqa: TC001 - runtime models
    GitSha,
    RepositoryContext,
    RepositoryPath,
)
from RepoRemedy.context.github import ContextError
from RepoRemedy.context.resolve import InputResolution, TemplateInputs, resolve_template_inputs
from RepoRemedy.models import Issue, Report  # noqa: TC001 - runtime models

if TYPE_CHECKING:
    from collections.abc import Mapping

RouteChoice = Literal["auto", "issue", "pr"]


class FileChange(BaseModel):
    """Exact new content and a reviewable diff for a typed repository path.

    Paths serialize as POSIX strings; rendering only proposes file creation.
    Existing targets and unsafe parents are blocked by the file guards.
    """

    path: RepositoryPath
    operation: Literal["create"] = "create"
    content: str
    diff: str


class PublicationContent(BaseModel):
    """Content for a later publisher, distinct from private collection provenance."""

    title: str
    body: str
    files: list[FileChange] = Field(default_factory=list)
    draft: bool = False


class Proposal(BaseModel):
    """One selected remedy, including why it can or cannot proceed to publication."""

    remedy_id: str | None
    findings: list[Issue]
    route: Literal["issue", "pr"]
    status: Literal["ready", "needs-input", "needs-review", "unavailable", "unsupported"]
    content: PublicationContent | None = None
    inputs: dict[str, ResolvedInput] = Field(default_factory=dict)
    missing_inputs: dict[str, str] = Field(default_factory=dict)
    guards: dict[str, bool] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)


class ProposalBundle(BaseModel):
    """Self-contained local artifact: publish selected content, never the whole snapshot."""

    schema_version: Literal[1] = 1
    repository: str
    base_commit: GitSha
    report: Report
    context: RepositoryContext
    report_sha256: str
    context_sha256: str
    catalog_sha256: str
    approved_inputs: list[str]
    proposals: list[Proposal]
    notices: list[str]


COMMUNITY_KEYS = {
    "ra-read-me": "readme",
    "ra-contributing": "contributing",
    "ra-code-of-conduct": "code_of_conduct",
    "ra-license-file": "license",
    "ra-issue-templates": "issue_template",
    "ra-pull-request-template": "pull_request_template",
    "security-policy": "security",
}


def _evaluate_file_guards(context: RepositoryContext, identifier: str, route: Route) -> dict[str, bool]:
    """Require complete inventory and account for alternate and inherited community files."""
    paths = {path.as_posix().lower() for path in context.paths}
    tree = context.observations.get("tree")
    tree_data = tree.value if tree else None
    directories = tree_data.get("directories", []) if isinstance(tree_data, dict) else []
    absent = context.tree_complete and all(
        file.path.as_posix().lower() not in paths
        and not any(
            parent.as_posix().lower() in paths and parent.as_posix() not in directories
            for parent in file.path.parents
            if parent.as_posix() != "."
        )
        for file in route.files
    )
    equivalent_absent = context.tree_complete and not find_matching_files(context, identifier)
    key = COMMUNITY_KEYS.get(identifier)
    if key:
        profile = context.observations.get("community_profile")
        data = profile.value if profile and profile.status == "available" else None
        files = data.get("files") if isinstance(data, dict) else None
        equivalent_absent = equivalent_absent and isinstance(files, dict) and not files.get(key)
    return {
        "confirmed_gap": absent and equivalent_absent,
        "target_absent": absent,
        "no_equivalent_file": equivalent_absent,
    }


def _render_content(route: Route, remedy: Remedy, values: Mapping[str, ResolvedInput]) -> PublicationContent:
    """Render once so placeholders inside supplied content stay literal.

    The diff uses POSIX destination names on every platform and creates files
    from /dev/null; this operation never writes to the repository.
    """
    substitutions = {key: value.value for key, value in values.items()}
    substitutions["response"] = remedy.response
    substitutions["change_summary"] = route.change_summary or ""
    changes = []
    for file in route.files:
        content = Template(read_asset("files", file.template)).substitute(substitutions)
        changes.append(
            FileChange(
                path=file.path,
                content=content,
                diff="".join(
                    unified_diff(
                        [],
                        content.splitlines(keepends=True),
                        fromfile="/dev/null",
                        tofile=f"b/{file.path.as_posix()}",
                    )
                ),
            )
        )
    return PublicationContent(
        title=Template(route.title).substitute(substitutions),
        body=Template(read_asset("bodies", route.body)).substitute(substitutions),
        files=changes,
        draft=bool(changes),
    )


@dataclass
class RouteSelection:
    """Selected route inputs with the creation guard results and blocking reasons."""

    inputs: TemplateInputs
    guards: dict[str, bool]
    reasons: list[str]


def _select_route(
    records: list[TemplateInputs],
    remedy: Remedy,
    context: RepositoryContext,
    approved: set[str],
    choice: RouteChoice,
) -> RouteSelection:
    """Prefer an eligible PR; explicit PR requests retain every blocking reason."""
    issue = records[0]
    identifier = issue.remedy_id
    assert identifier is not None
    if choice == "issue":
        return RouteSelection(inputs=issue, guards={}, reasons=[])
    if remedy.pr is None:
        return RouteSelection(
            inputs=issue,
            guards={},
            reasons=["This catalog remedy supports issues only"] if choice == "pr" else [],
        )
    pr = records[1]
    guards = _evaluate_file_guards(context, identifier, remedy.pr)
    guards["approved_inputs"] = identifier in approved
    reasons = [f"PR guard did not pass: {guard}" for guard, passed in guards.items() if not passed]
    # These assets need dedicated format/access validators before automated PR publication.
    if identifier in {"ra-citation", "ra-code-owners"}:
        reasons.append("This PR requires a dedicated citation/CODEOWNERS validator; use the issue route")
    if pr.missing_inputs:
        reasons.append("PR content needs inputs: " + ", ".join(sorted(pr.missing_inputs)))
    return RouteSelection(
        inputs=pr if choice == "pr" or not reasons else issue,
        guards=guards,
        reasons=reasons,
    )


def _build_proposal(
    records: list[TemplateInputs],
    remedy: Remedy | None,
    finding: Issue,
    context: RepositoryContext,
    approved: set[str],
    choice: RouteChoice,
) -> Proposal:
    """Build reviewable content and readiness without treating evidence as approval.

    Unavailable findings do not establish defects. Complete inputs alone do not
    bypass file guards, maintainer approval or content validation.
    """
    record = records[0]
    if record.status in {"unsupported", "unavailable"}:
        return Proposal(
            remedy_id=record.remedy_id,
            findings=[finding],
            route="issue",
            status=record.status,
            reasons=[record.reason or record.status],
        )
    assert remedy is not None
    selection = _select_route(records, remedy, context, approved, choice)
    selected = selection.inputs
    guards = selection.guards
    reasons = selection.reasons
    status = "needs-input" if selected.missing_inputs else "ready"
    if (selected.route == "pr" and reasons) or (choice == "pr" and remedy.pr is None):
        status = "needs-input" if selected.missing_inputs else "needs-review"
    if selected.route == "issue" and remedy.pr:
        file_guards = _evaluate_file_guards(context, selected.remedy_id or "", remedy.pr)
        if not file_guards["confirmed_gap"]:
            status = "needs-review"
            reasons.append(
                "File absence is not confirmed; inspect existing, inherited or unavailable evidence"
            )
    if "approved_value" in selected.inputs and selected.remedy_id not in approved:
        status = "needs-review"
        reasons.append("The proposed setting value requires explicit input approval")
    route = remedy.pr if selected.route == "pr" else remedy.issue
    assert route is not None
    content = None if selected.missing_inputs else _render_content(route, remedy, selected.inputs)
    if content and (
        not content.title.strip()
        or "\n" in content.title
        or any(
            "\x00" in value for value in [content.title, content.body, *(f.content for f in content.files)]
        )
        or any(not file.content.strip() for file in content.files)
    ):
        status = "needs-review"
        reasons.append("Rendered content failed text validation")
    return Proposal(
        remedy_id=selected.remedy_id,
        findings=[finding],
        route=selected.route,
        status=status,
        content=content,
        inputs=selected.inputs,
        missing_inputs=selected.missing_inputs,
        guards=guards,
        reasons=reasons,
    )


def propose_remedies(
    report: Report,
    context: RepositoryContext,
    supplied: dict[str, dict[str, str]] | None = None,
    *,
    approved_inputs: set[str] | None = None,
    route: RouteChoice = "auto",
) -> ProposalBundle:
    """Resolve, select and render locally; only ready records may enter later publication."""
    resolution: InputResolution = resolve_template_inputs(report, context, supplied)
    remedies = load_catalog().remedies
    approved = approved_inputs or set()
    if approved - remedies.keys():
        message = "Input approval refers to an unknown remedy"
        raise ContextError(message)
    proposals = []
    offset = 0
    for finding in report.issues:
        record = resolution.templates[offset]
        remedy = remedies.get(record.remedy_id or "")
        count = 2 if remedy and remedy.pr and record.status not in {"unavailable", "unsupported"} else 1
        proposal = _build_proposal(
            resolution.templates[offset : offset + count], remedy, finding, context, approved, route
        )
        offset += count
        if report.source.audited_commit and report.source.audited_commit.lower() != context.commit_sha:
            if proposal.status == "ready":
                proposal.status = "needs-review"
            proposal.reasons.append(
                "Report and context commits differ; recheck the finding before publication"
            )
        proposals.append(proposal)
    return ProposalBundle(
        repository=context.repository,
        base_commit=context.commit_sha,
        report=report,
        context=context,
        report_sha256=resolution.report_sha256,
        context_sha256=resolution.context_sha256,
        catalog_sha256=resolution.catalog_sha256,
        approved_inputs=sorted(approved),
        proposals=proposals,
        notices=[
            *report.notices,
            *context.notices,
            "Ready means complete issue or draft PR content. Publication remains a separate, explicitly selected action.",
            "Only publish selected proposal content, not this local bundle or its repository snapshot.",
            "The publisher must recheck target state, permissions and duplicates. Repository validation commands have not run.",
        ],
    )
