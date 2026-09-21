"""Route input resolution, supplied values and saved provenance."""

from pathlib import Path
import json

import pytest

from RepoRemedy.catalog import load_catalog
from RepoRemedy.context.github import ContextError
from RepoRemedy.context.inputs import MAINTAINER_INPUTS
from RepoRemedy.context.repository_context import RepositoryContext
from RepoRemedy.context.resolve import InputResolution, resolve_template_inputs
from remedy_fixtures import make_report
from repository_context_test import COMMIT, FakeGitHub


def test_security_inputs_use_recorded_sections_and_remain_inputs(snapshot):
    result = resolve_template_inputs(make_report(), snapshot)
    pr = next(t for t in result.templates if t.route == "pr")
    assert pr.status == "complete"
    assert pr.inputs["security_reporting_instructions"].value == "Use the private reporting form"
    assert pr.inputs["supported_versions"].value == "1.x"
    assert COMMIT in pr.inputs["supported_versions"].source
    assert result.report_sha256 == "e" * 64 and len(result.context_sha256) == 64
    assert not {"body", "title", "files", "guards"} & pr.model_dump().keys()
    assert "docs/SECURITY.md" in result.templates[0].inputs["observed_state"].value
    assert any("guard evaluation" in n for n in result.notices)


def test_settings_never_infer_approved_or_expected_values(snapshot):
    result = resolve_template_inputs(make_report("Private"), snapshot)
    assert '"private": false' in result.templates[0].inputs["observed_state"].value
    result = resolve_template_inputs(make_report("RequireApprovals"), snapshot)
    issue = result.templates[0]
    assert set(issue.missing_inputs) == {"reported_expected_value", "approved_value"}
    assert issue.inputs["setting_location"].value == "https://github.com/acme/demo/settings/branches"
    assert "required_approving_review_count" in issue.inputs["observed_state"].value
    completed = resolve_template_inputs(
        make_report("RequireApprovals"),
        snapshot,
        {"ra-require-approvals": {"approved_value": "2", "reported_expected_value": "2"}},
    )
    assert completed.templates[0].status == "complete"
    assert "approval not established" in completed.templates[0].inputs["approved_value"].source


def test_all_catalog_inputs_are_accounted_for(snapshot):
    catalog = load_catalog()
    for identifier, remedy in catalog.remedies.items():
        origin, checks = next(iter(remedy.sources.items()))
        result = resolve_template_inputs(make_report(checks[0], origin=origin), snapshot)
        for resolved in result.templates:
            route = remedy.issue if resolved.route == "issue" else remedy.pr
            assert route is not None
            assert set(resolved.inputs) | set(resolved.missing_inputs) == set(route.required_inputs)
            assert not set(resolved.inputs) & set(resolved.missing_inputs)
            assert not MAINTAINER_INPUTS & resolved.inputs.keys()
            assert resolved.remedy_id == identifier


@pytest.mark.parametrize(
    "fields",
    [{"unknown": "x"}, {"repository": "other/repo"}, {"approved_value": ""}, {"approved_value": 12}, []],
)
def test_supplied_values_cannot_override_evidence_or_introduce_unknown_inputs(snapshot, fields):
    with pytest.raises(ContextError):
        resolve_template_inputs(make_report("RequireApprovals"), snapshot, {"ra-require-approvals": fields})


def test_unknown_remedy_and_repository_mismatch(snapshot):
    with pytest.raises(ContextError, match="unknown remedy"):
        resolve_template_inputs(make_report(), snapshot, {"unknown": {}})
    wrong = make_report()
    wrong.repository = "other/repo"
    with pytest.raises(ContextError, match="different repositories"):
        resolve_template_inputs(wrong, snapshot)


def test_unknown_and_unavailable_findings_remain_visible(snapshot):
    unknown = resolve_template_inputs(make_report("FutureCheck"), snapshot).templates[0]
    assert unknown.status == "unsupported" and not unknown.inputs
    unavailable = resolve_template_inputs(make_report(status="unavailable"), snapshot).templates[0]
    assert unavailable.status == "unavailable" and not unavailable.inputs
    assert any(
        "differs" in n for n in resolve_template_inputs(make_report(commit="c" * 40), snapshot).notices
    )


def test_literal_user_content_and_route_specific_inputs(snapshot):
    result = resolve_template_inputs(
        make_report("LicenseFile"),
        snapshot,
        {"ra-license-file": {"approved_license_text": "Literal ${repository}"}},
    )
    assert "approved_license_text" not in result.templates[0].inputs
    assert result.templates[1].inputs["approved_license_text"].value == "Literal ${repository}"


def test_resolution_preserves_report_and_context_notices(snapshot):
    source = make_report()
    source.notices.append("Report completeness is unverified")
    result = resolve_template_inputs(source, snapshot)
    assert "Report completeness is unverified" in result.notices
    assert set(snapshot.notices) <= set(result.notices)


def test_saved_context_resolves_paths_and_bom_prefixed_sections():
    api = FakeGitHub()
    content = "\ufeff## Supported versions\n1.x\n"
    api.file("docs/SECURITY.md", content)
    api.file(".github/workflows/test.yml", "name: CI")
    snapshot = RepositoryContext.model_validate_json(api.snapshot().model_dump_json())
    result = resolve_template_inputs(make_report(), snapshot)
    observed = json.loads(result.templates[0].inputs["observed_state"].value)
    assert observed["matching_paths"] == ["docs/SECURITY.md"]
    supported = result.templates[1].inputs["supported_versions"]
    assert supported.value == "1.x"
    assert supported.source == f"file:docs/SECURITY.md@{COMMIT}"
    assert snapshot.files[Path("docs/SECURITY.md")].content == content
    engineering = resolve_template_inputs(make_report("Pinned-Dependencies", origin="OSSF"), snapshot)
    inputs = engineering.templates[0].inputs
    assert ".github/workflows/test.yml" in inputs["affected_components"].value
    assert ".github/workflows/test.yml" in json.loads(inputs["observed_state"].value)["collected_paths"]


@pytest.mark.parametrize("sha", ["A" * 40, "B" * 64])
def test_resolution_reuses_shared_git_sha_validation(snapshot, sha):
    result = resolve_template_inputs(make_report(), snapshot)
    data = result.model_dump()
    data["commit_sha"] = sha
    assert InputResolution.model_validate(data).commit_sha == sha.lower()
    data["commit_sha"] = "invalid"
    with pytest.raises(ValueError):
        InputResolution.model_validate(data)


def test_commit_comparison_ignores_hex_case(snapshot):
    result = resolve_template_inputs(make_report(commit=snapshot.commit_sha.upper()), snapshot)
    assert not any("differs" in notice for notice in result.notices)
