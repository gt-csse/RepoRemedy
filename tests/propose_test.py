"""Concrete proposal rendering, route selection and creation guards."""

import json
from pathlib import Path

import pytest

from RepoRemedy.context.github import ContextError
from RepoRemedy.propose import ProposalBundle, propose_remedies
from remedy_fixtures import make_report
from repository_context_test import COMMIT, TREE, FakeGitHub


def test_propose_renders_issue_and_saves_reproducible_local_bundle():
    context = FakeGitHub().snapshot()
    result = propose_remedies(make_report(), context)
    proposal = result.proposals[0]
    assert proposal.status == "ready" and proposal.route == "issue"
    assert proposal.content is not None
    assert "Security policy" in proposal.content.title
    assert "Example evidence" in proposal.content.body and "acme/demo" in proposal.content.body
    assert not proposal.content.files and not proposal.content.draft
    assert not proposal.guards["approved_inputs"]
    assert "PR content needs inputs" in " ".join(proposal.reasons)
    assert result.context == context and result.report.source.path == Path("audit.txt")
    assert ProposalBundle.model_validate_json(result.model_dump_json()) == result
    assert result.base_commit == COMMIT and len(result.catalog_sha256) == 64


def test_auto_selects_approved_pr_with_actual_files_and_diffs():
    context = FakeGitHub().snapshot()
    result = propose_remedies(make_report("IssueTemplates"), context, approved_inputs={"ra-issue-templates"})
    proposal = result.proposals[0]
    assert proposal.status == "ready" and proposal.route == "pr" and all(proposal.guards.values())
    assert proposal.content is not None
    assert proposal.content.draft and len(proposal.content.files) == 2
    for file in proposal.content.files:
        assert file.operation == "create" and file.content.strip()
        assert isinstance(file.path, Path)
        assert f"+++ b/{file.path.as_posix()}" in file.diff
        assert file.diff.startswith("--- /dev/null\n+++ b/.github/ISSUE_TEMPLATE/")
    assert "acme/demo" in proposal.content.title
    assert result.approved_inputs == ["ra-issue-templates"]
    serialized = json.loads(result.model_dump_json())
    assert (
        serialized["proposals"][0]["content"]["files"][0]["path"] == proposal.content.files[0].path.as_posix()
    )
    assert ProposalBundle.model_validate_json(result.model_dump_json()) == result


def test_rendering_preserves_literal_inserted_placeholders():
    result = propose_remedies(
        make_report("LicenseFile"),
        FakeGitHub().snapshot(),
        {"ra-license-file": {"approved_license_text": "License for ${repository} and $HOME"}},
        approved_inputs={"ra-license-file"},
    )
    assert result.proposals[0].status == "ready"
    assert result.proposals[0].content is not None
    assert result.proposals[0].content.files[0].content == "License for ${repository} and $HOME\n"


@pytest.mark.parametrize("path", ["SECURITY.md", "docs/security.rst", "nested/SECURITY.txt"])
def test_existing_or_alternate_file_prevents_creation_and_false_ready_issue(path):
    api = FakeGitHub()
    api.file(path, "Existing policy")
    result = propose_remedies(make_report(), api.snapshot(), approved_inputs={"security-policy"})
    proposal = result.proposals[0]
    assert proposal.route == "issue" and proposal.status == "needs-review"
    assert proposal.content is not None
    assert not proposal.guards["confirmed_gap"] and not proposal.content.files


@pytest.mark.parametrize("profile", [None, {"files": {"security": {"html_url": "inherited"}}}, {}])
def test_missing_or_inherited_community_evidence_blocks_absence(profile):
    api = FakeGitHub()
    api.responses["/community/profile"] = profile
    proposal = propose_remedies(make_report(), api.snapshot()).proposals[0]
    assert proposal.status == "needs-review" and not proposal.guards["no_equivalent_file"]


def test_incomplete_tree_and_existing_parent_block_pr():
    api = FakeGitHub()
    api.responses[f"/git/trees/{TREE}"]["truncated"] = True
    proposal = propose_remedies(
        make_report("IssueTemplates"), api.snapshot(), route="pr", approved_inputs={"ra-issue-templates"}
    ).proposals[0]
    assert proposal.status == "needs-review" and not proposal.guards["target_absent"]
    api = FakeGitHub()
    api.file(".github", "elsewhere", mode="120000")
    proposal = propose_remedies(
        make_report("IssueTemplates"), api.snapshot(), route="pr", approved_inputs={"ra-issue-templates"}
    ).proposals[0]
    assert proposal.status == "needs-review" and not proposal.guards["target_absent"]


def test_real_parent_directories_allow_creation():
    api = FakeGitHub()
    api.file(".github", b"", mode="040000", kind="tree")
    api.file(".github/workflows/check.yml", "name: CI")
    proposal = propose_remedies(
        make_report("IssueTemplates"), api.snapshot(), approved_inputs={"ra-issue-templates"}
    ).proposals[0]
    assert proposal.status == "ready" and proposal.route == "pr"


def test_alternate_pr_template_directory_blocks_duplicate_creation():
    api = FakeGitHub()
    api.file("docs/PULL_REQUEST_TEMPLATE/change.md", "Existing template")
    proposal = propose_remedies(
        make_report("PullRequestTemplate"),
        api.snapshot(),
        route="pr",
        approved_inputs={"ra-pull-request-template"},
    ).proposals[0]
    assert proposal.status == "needs-review" and not proposal.guards["no_equivalent_file"]


def test_explicit_routes_keep_missing_values_and_blocked_guards_visible():
    context = FakeGitHub().snapshot()
    proposal = propose_remedies(make_report(), context, route="pr").proposals[0]
    assert proposal.status == "needs-input" and proposal.content is None
    assert set(proposal.missing_inputs) == {"supported_versions", "security_reporting_instructions"}
    issue = propose_remedies(
        make_report("IssueTemplates"), context, route="issue", approved_inputs={"ra-issue-templates"}
    ).proposals[0]
    assert issue.content is not None
    assert issue.route == "issue" and not issue.content.files
    unsupported = propose_remedies(make_report("Private"), context, route="pr").proposals[0]
    assert unsupported.status == "needs-review" and "issues only" in unsupported.reasons[0]


def test_settings_need_explicit_values_and_approval():
    context = FakeGitHub().snapshot()
    source = make_report("RequireApprovals")
    assert propose_remedies(source, context).proposals[0].status == "needs-input"
    supplied = {"ra-require-approvals": {"approved_value": "3", "reported_expected_value": "3"}}
    assert propose_remedies(source, context, supplied).proposals[0].status == "needs-review"
    ready = propose_remedies(source, context, supplied, approved_inputs={"ra-require-approvals"}).proposals[0]
    assert ready.content is not None
    assert ready.status == "ready" and "Maintainer-approved value: 3" in ready.content.body
    with pytest.raises(ContextError, match="unknown remedy"):
        propose_remedies(source, context, approved_inputs={"unknown"})


@pytest.mark.parametrize(
    "check,key", [("Citation", "approved_citation_metadata"), ("CodeOwners", "approved_codeowners")]
)
def test_format_validation_limit_prevents_false_pr_readiness(check, key):
    identifier = "ra-citation" if check == "Citation" else "ra-code-owners"
    result = propose_remedies(
        make_report(check),
        FakeGitHub().snapshot(),
        {identifier: {key: "reviewed content"}},
        approved_inputs={identifier},
    )
    proposal = result.proposals[0]
    assert proposal.status == "ready" and proposal.route == "issue"
    assert any("validator" in reason for reason in proposal.reasons)


def test_unknown_unavailable_and_stale_findings_are_never_ready():
    context = FakeGitHub().snapshot()
    for source, status in [
        (make_report("FutureCheck"), "unsupported"),
        (make_report(status="unavailable"), "unavailable"),
    ]:
        proposal = propose_remedies(source, context).proposals[0]
        assert proposal.status == status and proposal.content is None
    stale = propose_remedies(make_report(commit="c" * 40), context).proposals[0]
    assert stale.status == "needs-review" and any("commits differ" in reason for reason in stale.reasons)
    incomplete = propose_remedies(make_report("RequireApprovals", commit="c" * 40), context).proposals[0]
    assert incomplete.status == "needs-input"


def test_mixed_findings_keep_route_inputs_aligned():
    source = make_report()
    source.issues.extend([make_report("FutureCheck").issues[0], make_report("IssueTemplates").issues[0]])
    result = propose_remedies(source, FakeGitHub().snapshot(), approved_inputs={"ra-issue-templates"})
    assert [p.status for p in result.proposals] == ["ready", "unsupported", "ready"]
    assert [p.route for p in result.proposals] == ["issue", "issue", "pr"]


def test_invalid_rendered_text_is_not_ready():
    proposal = propose_remedies(
        make_report("LicenseFile"),
        FakeGitHub().snapshot(),
        {"ra-license-file": {"approved_license_text": "abc\x00def"}},
        approved_inputs={"ra-license-file"},
    ).proposals[0]
    assert proposal.status == "needs-review" and "text validation" in proposal.reasons[-1]


def test_propose_populates_file_content_from_repository_guidance():
    api = FakeGitHub()
    api.file(
        "README.md",
        "# Demo\n\n## Development setup\nuv sync\n\n## Testing\nuv run pytest\n\n## Submitting changes\nOpen a PR against main\n",
    )
    context = api.snapshot()
    proposal = propose_remedies(
        make_report("Contributing"), context, approved_inputs={"ra-contributing"}
    ).proposals[0]
    assert proposal.status == "ready" and proposal.route == "pr"
    assert proposal.content is not None
    content = proposal.content.files[0].content
    assert "uv sync" in content and "uv run pytest" in content and "Open a PR against main" in content
    assert proposal.inputs["development_setup"].source == f"file:README.md@{COMMIT}"


def test_uppercase_audited_commit_does_not_block_readiness():
    context = FakeGitHub().snapshot()
    proposal = propose_remedies(make_report(commit=context.commit_sha.upper()), context).proposals[0]
    assert proposal.status == "ready"
    assert not any("commits differ" in reason for reason in proposal.reasons)


@pytest.mark.parametrize("sha", ["A" * 40, "B" * 64])
def test_bundle_reuses_shared_git_sha_validation(sha):
    result = propose_remedies(make_report(), FakeGitHub().snapshot())
    data = result.model_dump()
    data["base_commit"] = sha
    assert ProposalBundle.model_validate(data).base_commit == sha.lower()
    data["base_commit"] = "invalid"
    with pytest.raises(ValueError):
        ProposalBundle.model_validate(data)
