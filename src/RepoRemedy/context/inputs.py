# noqa: CPY001
"""Resolve known template inputs with evidence, retaining missing decisions explicitly."""

from dataclasses import dataclass
import json
import re
from typing import TYPE_CHECKING

from pydantic import BaseModel

from RepoRemedy.context.github import Observation, get_repository_address
from RepoRemedy.context.repository_context import is_manifest_path

if TYPE_CHECKING:
    from pathlib import Path

    from RepoRemedy.catalog import Remedy, Route
    from RepoRemedy.context.repository_context import RepositoryContext
    from RepoRemedy.models import Issue

# Every current catalog input has an explicit source or a reason it needs human input.
MAINTAINER_INPUTS = {
    "approved_value",
    "approved_license_text",
    "approved_codeowners",
    "approved_code_of_conduct",
    "approved_citation_metadata",
    "reported_expected_value",
}
SECTIONS = {
    "installation_instructions": ("installation", "install", "getting started"),
    "usage_instructions": ("usage", "quick start", "quickstart"),
    "support_instructions": ("support", "getting help", "help"),
    "development_setup": ("development setup", "development", "setup", "building"),
    "test_instructions": ("testing", "tests", "running tests"),
    "contribution_process": ("submitting changes", "contributing", "pull requests", "contribution process"),
    "security_reporting_instructions": ("reporting a vulnerability", "reporting vulnerabilities"),
    "supported_versions": ("supported versions",),
}
FILE_STEMS = {
    "ra-read-me": {"readme"},
    "ra-contributing": {"contributing"},
    "ra-code-of-conduct": {"code_of_conduct"},
    "ra-license-file": {"license", "copying"},
    "ra-license": {"license", "copying"},
    "ossf-license": {"license", "copying"},
    "security-policy": {"security"},
    "ra-code-owners": {"codeowners"},
    "ra-citation": {"citation"},
    "ra-pull-request-template": {"pull_request_template"},
    "ra-issue-templates": {"issue_template"},
}
METADATA_KEYS = {
    "Description": "description",
    "TemplateRepository": "is_template",
    "WebCommitSignoff": "web_commit_signoff_required",
    "DefaultBranch": "default_branch",
    "SupportWikis": "has_wiki",
    "SupportIssues": "has_issues",
    "SupportDiscussions": "has_discussions",
    "SupportProjects": "has_projects",
    "MergeCommit": "allow_merge_commit",
    "SquashCommitMerge": "allow_squash_merge",
    "RebaseMergeCommit": "allow_rebase_merge",
    "SuggestUpdatingPullRequestBranches": "allow_update_branch",
    "AutoMerge": "allow_auto_merge",
    "DeleteHeadBranches": "delete_branch_on_merge",
    "Private": "private",
    "License": "license",
}


class ResolvedInput(BaseModel):
    """A usable value together with its origin; no inferred approval."""

    value: str
    source: str


@dataclass
class ResolvedInputs:
    """Values and unresolved requirements for one catalog route; neither implies approval."""

    values: dict[str, ResolvedInput]
    missing_inputs: dict[str, str]


def find_matching_files(context: RepositoryContext, remedy_id: str) -> list[Path]:
    """Locate file evidence including alternate community locations and issue forms."""
    stems = FILE_STEMS.get(remedy_id)
    if stems is None:
        return []
    return sorted(
        path
        for path in context.paths
        if path.name.lower().split(".")[0] in stems
        or any(
            f"{stem}/" in path.as_posix().lower()
            for stem in stems & {"issue_template", "pull_request_template"}
        )
    )


def _extract_section(context: RepositoryContext, names: tuple[str, ...]) -> ResolvedInput | None:
    """Extract one unambiguous heading value from available repository guidance.

    Ignore a leading BOM for heading recognition without changing saved content.
    Conflicting sections remain unresolved rather than choosing a file arbitrarily.
    """
    candidates = []
    for path, file in context.files.items():
        if file.status != "available" or not file.content:
            continue
        if path.name.lower().split(".")[0] not in {
            "readme",
            "contributing",
            "security",
            "support",
        }:
            continue
        for match in re.finditer(
            r"^#{1,6}\s+([^\n]+)\n(.*?)(?=^#{1,6}\s|\Z)",
            file.content.removeprefix("\ufeff"),
            re.MULTILINE | re.DOTALL,
        ):
            if match[1].strip().strip("#").strip().lower() in names and match[2].strip():
                candidates.append(  # noqa: PERF401 - filter requires two match groups
                    ResolvedInput(
                        value=match[2].strip(), source=f"file:{path.as_posix()}@{context.commit_sha}"
                    )
                )
    # Conflicting sections need a decision rather than an arbitrary first match.
    values = {c.value for c in candidates}
    return candidates[0] if len(values) == 1 else None


def _describe_observed_state(context: RepositoryContext, remedy_id: str, issue: Issue) -> ResolvedInput:
    """Describe file evidence or live observations without inferring desired policy."""
    if remedy_id in FILE_STEMS:
        value = {
            "matching_paths": [path.as_posix() for path in find_matching_files(context, remedy_id)],
            "tree_complete": context.tree_complete,
        }
        return ResolvedInput(value=json.dumps(value, sort_keys=True), source=f"tree:{context.tree_sha}")
    key = METADATA_KEYS.get(issue.check)
    metadata = context.observations["repository"]
    if key and isinstance(metadata.value, dict):
        value = {key: metadata.value.get(key), "available": key in metadata.value}
        return ResolvedInput(value=json.dumps(value, sort_keys=True), source="live:repository")
    if remedy_id == "ossf-webhooks":
        resources = ("webhooks",)
    elif remedy_id == "ra-dependabot-security-updates":
        resources = ("dependabot_security_updates",)
    elif remedy_id.startswith("ra-secret-scanning") or remedy_id in {
        "ra-merge-commit-message",
        "ra-squash-merge-commit-message",
        "ossf-maintained",
    }:
        resources = ("repository",)
    elif remedy_id in {"ossf-packaging", "ossf-signed-releases", "ossf-sbom"}:
        resources = ("releases",)
    elif remedy_id == "ossf-contributors":
        resources = ("contributors",)
    elif remedy_id in {"ossf-ci-tests", "ossf-sast"}:
        resources = ("check_runs", "commit_statuses")
    elif remedy_id in {
        "ossf-dangerous-workflow",
        "ossf-pinned-dependencies",
        "ossf-dependency-update-tool",
        "ossf-fuzzing",
        "ossf-binary-artifacts",
        "ossf-vulnerabilities",
    }:
        return ResolvedInput(
            value=json.dumps(
                {
                    "collected_paths": [path.as_posix() for path in sorted(context.files)],
                    "tree_complete": context.tree_complete,
                }
            ),
            source=f"tree:{context.tree_sha}",
        )
    elif remedy_id == "ossf-cii-best-practices":
        return ResolvedInput(
            value="Badge status is preserved in report evidence; no badge service query was performed",
            source="report",
        )
    else:
        resources = (
            "branch",
            "branch_protection",
            "branch_rules",
            "check_runs",
            "commit_statuses",
            "environments",
        )
    data = {
        name: context.observations.get(
            name, Observation(status="unavailable", reason="Not present in saved context")
        ).model_dump(mode="json")
        for name in resources
    }
    return ResolvedInput(value=json.dumps(data, sort_keys=True), source="live:" + ",".join(resources))


def resolve_inputs(
    context: RepositoryContext,
    remedy_id: str,
    remedy: Remedy,
    route: Route,
    issue: Issue,
) -> ResolvedInputs:
    """Return factual inputs and reasons for unresolved route requirements.

    Repository evidence supplies facts, never approval or policy decisions.
    Paths become POSIX strings only when inserted into template text or JSON.
    """
    _, web, _ = get_repository_address(context.repository)
    target = (
        ", ".join(f.path.as_posix() for f in remedy.pr.files)
        if remedy.pr
        else f"{web} (branch {context.settings_branch})"
    )
    values = {
        "repository": ResolvedInput(value=context.repository, source="report"),
        "origin": ResolvedInput(value=issue.origin, source="report"),
        "check": ResolvedInput(value=issue.check, source="report"),
        "evidence": ResolvedInput(value=issue.evidence, source=f"report:{issue.location}"),
        "target": ResolvedInput(value=target, source="catalog"),
        "observed_state": _describe_observed_state(context, remedy_id, issue),
        "verification_steps": ResolvedInput(
            value=f"Review the proposed response against repository guidance. {remedy.response}\n"
            f"After applying the change, verify the observed behavior and rerun {issue.origin} / {issue.check}. "
            "Record results; this preview has not executed validation.",
            source="catalog",
        ),
    }
    if "setting_location" in route.required_inputs:
        section = (
            "branches"
            if "branch" in remedy_id
            or remedy_id.startswith(
                (
                    "ra-require",
                    "ra-restrict",
                    "ra-allow",
                    "ra-dismiss",
                    "ra-ensure",
                    "ra-protected",
                    "ra-do-not",
                )
            )
            else "security_analysis"
            if "scanning" in remedy_id or "dependabot" in remedy_id
            else ""
        )
        values["setting_location"] = ResolvedInput(
            value=f"{web}/settings/{section}".rstrip("/"), source="repository URL + catalog"
        )
    if "affected_components" in route.required_inputs:
        components = sorted(
            path
            for path in context.files
            if path.as_posix().lower().startswith(".github/workflows/") or is_manifest_path(path)
        )
        if components:
            values["affected_components"] = ResolvedInput(
                value="Candidate components for review (not confirmed defects):\n"
                + "\n".join(path.as_posix() for path in components),
                source=f"tree:{context.tree_sha}",
            )
    metadata = context.observations["repository"].value
    if isinstance(metadata, dict):
        for field, name in (("project_name", "name"), ("project_summary", "description")):
            value = metadata.get(name)
            if isinstance(value, str) and value.strip():
                values[field] = ResolvedInput(value=value, source=f"live:repository.{name}")
    missing = {}
    for key in route.required_inputs:
        if key in SECTIONS:
            section_value = _extract_section(context, SECTIONS[key])
            if section_value:
                values[key] = section_value
        if key not in values:
            missing[key] = (
                "Requires an explicit audit expectation or maintainer-approved value; not inferred from current state"
                if key in MAINTAINER_INPUTS
                else "No unambiguous value found in the recorded repository context"
            )
    return ResolvedInputs(
        values={key: values[key] for key in route.required_inputs if key in values},
        missing_inputs=missing,
    )
