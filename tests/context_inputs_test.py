"""Catalog inputs resolve from provenance-bearing facts without generating proposals."""

from pathlib import Path
import json
import shutil

import pytest

from RepoRemedy.catalog import asset, load_catalog
from RepoRemedy.context.github import ContextError
from RepoRemedy.context.inputs import MAINTAINER_INPUTS, ResolvedInput, matching_files
from RepoRemedy.context.repository_context import RepositoryContext, RepositoryFile
from RepoRemedy.context.resolve import resolve_template_inputs
from RepoRemedy.models import Issue, Report, ReportType, Source
from repository_context_test import COMMIT, TREE, FakeGitHub

ASSETS = Path(__file__).resolve().parents[1] / "src/RepoRemedy/templates"


def report(check="SecurityPolicy", *, origin="RA", status="warning", commit=None):
    return Report(
        repository="acme/demo",
        source=Source(
            path=Path("audit.txt"), sha256="e" * 64, report_type=ReportType.REPOAUDITOR, audited_commit=commit
        ),
        issues=[
            Issue(
                origin=origin, check=check, status=status, evidence="Example evidence", location="lines:1-3"
            )
        ],
        notices=[],
    )


@pytest.fixture
def snapshot():
    api = FakeGitHub()
    api.file(
        "README.md",
        "# Demo\n\n## Installation\nuv sync\n\n## Usage\nRun demo\n\n## Support\nAsk maintainers\n",
    )
    api.file(
        "CONTRIBUTING.md",
        "# Contributing\n\n## Development setup\nuv sync\n\n## Testing\nuv run pytest\n\n## Submitting changes\nOpen a PR\n",
    )
    api.file(
        "docs/SECURITY.md",
        "# Security\n\n## Reporting a vulnerability\nUse the private reporting form\n\n## Supported versions\n1.x\n",
    )
    api.file(".github/workflows/test.yml", "name: CI")
    api.file("pyproject.toml", "[project]\nname='demo'\n")
    return api.snapshot()


def test_security_inputs_use_recorded_sections_and_remain_inputs(snapshot):
    result = resolve_template_inputs(report(), snapshot)
    pr = next(t for t in result.templates if t.route == "pr")
    assert pr.status == "complete"
    assert pr.inputs["security_reporting_instructions"].value == "Use the private reporting form"
    assert pr.inputs["supported_versions"].value == "1.x"
    assert COMMIT in pr.inputs["supported_versions"].source
    assert result.report_sha256 == "e" * 64 and len(result.context_sha256) == 64
    assert not {"body", "title", "files", "guards"} & pr.model_dump().keys()
    assert "docs/SECURITY.md" in result.templates[0].inputs["observed_state"].value
    assert any("guard evaluation" in n for n in result.notices)


def test_missing_and_conflicting_sections_are_not_invented(snapshot):
    snapshot.files[Path("SECURITY.md")] = RepositoryFile(
        path="SECURITY.md", blob_sha="f" * 40, status="available", content="## Supported versions\n2.x\n"
    )
    del snapshot.files[Path("docs/SECURITY.md")]
    result = resolve_template_inputs(report(), snapshot)
    assert "security_reporting_instructions" in result.templates[1].missing_inputs
    snapshot.files[Path("docs/SECURITY.md")] = RepositoryFile(
        path="docs/SECURITY.md", blob_sha="c" * 40, status="available", content="## Supported versions\n1.x\n"
    )
    assert "supported_versions" in resolve_template_inputs(report(), snapshot).templates[1].missing_inputs


def test_unreadable_sections_and_absent_description_stay_missing(snapshot):
    for file in snapshot.files.values():
        file.status = "unavailable"
        file.content = None
    snapshot.observations["repository"].value = {"name": "demo", "full_name": "acme/demo"}
    result = resolve_template_inputs(report("ReadMe"), snapshot)
    assert result.templates[1].status == "needs-input"
    assert "project_summary" in result.templates[1].missing_inputs


def test_settings_never_infer_approved_or_expected_values(snapshot):
    result = resolve_template_inputs(report("Private"), snapshot)
    assert '"private": false' in result.templates[0].inputs["observed_state"].value
    result = resolve_template_inputs(report("RequireApprovals"), snapshot)
    issue = result.templates[0]
    assert set(issue.missing_inputs) == {"reported_expected_value", "approved_value"}
    assert issue.inputs["setting_location"].value == "https://github.com/acme/demo/settings/branches"
    assert "required_approving_review_count" in issue.inputs["observed_state"].value
    completed = resolve_template_inputs(
        report("RequireApprovals"),
        snapshot,
        {"ra-require-approvals": {"approved_value": "2", "reported_expected_value": "2"}},
    )
    assert completed.templates[0].status == "complete"
    assert "approval not established" in completed.templates[0].inputs["approved_value"].source


def test_all_catalog_inputs_are_accounted_for(snapshot):
    remedies, digest = load_catalog()
    assert len(remedies) == 68 and len(digest) == 64
    for identifier, remedy in remedies.items():
        origin, checks = next(iter(remedy.sources.items()))
        result = resolve_template_inputs(report(checks[0], origin=origin), snapshot)
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
        resolve_template_inputs(report("RequireApprovals"), snapshot, {"ra-require-approvals": fields})


def test_unknown_remedy_and_repository_mismatch(snapshot):
    with pytest.raises(ContextError, match="unknown remedy"):
        resolve_template_inputs(report(), snapshot, {"unknown": {}})
    wrong = report()
    wrong.repository = "other/repo"
    with pytest.raises(ContextError, match="different repositories"):
        resolve_template_inputs(wrong, snapshot)


def test_unknown_and_unavailable_findings_remain_visible(snapshot):
    unknown = resolve_template_inputs(report("FutureCheck"), snapshot).templates[0]
    assert unknown.status == "unsupported" and not unknown.inputs
    unavailable = resolve_template_inputs(report(status="unavailable"), snapshot).templates[0]
    assert unavailable.status == "unavailable" and not unavailable.inputs
    assert any("differs" in n for n in resolve_template_inputs(report(commit="c" * 40), snapshot).notices)


def test_literal_user_content_and_route_specific_inputs(snapshot):
    result = resolve_template_inputs(
        report("LicenseFile"),
        snapshot,
        {"ra-license-file": {"approved_license_text": "Literal ${repository}"}},
    )
    assert "approved_license_text" not in result.templates[0].inputs
    assert result.templates[1].inputs["approved_license_text"].value == "Literal ${repository}"


def test_alternate_paths_and_absent_candidates(snapshot):
    snapshot.paths.extend([Path("docs/COPYING.txt"), Path(".github/ISSUE_TEMPLATE/bug.yml")])
    assert matching_files(snapshot, "ra-license-file") == [Path("docs/COPYING.txt")]
    assert matching_files(snapshot, "ra-issue-templates") == [Path(".github/ISSUE_TEMPLATE/bug.yml")]
    assert matching_files(snapshot, "unknown") == []
    snapshot.files = {}
    result = resolve_template_inputs(report("SAST", origin="OSSF"), snapshot)
    assert "affected_components" in result.templates[0].missing_inputs


@pytest.mark.parametrize(
    "folder,name",
    [("other", "README.md"), ("files", "../README.md"), ("files", "x\\README.md"), ("files", "..")],
)
def test_catalog_paths_are_bounded(folder, name):
    with pytest.raises(ContextError):
        asset(folder, name)


@pytest.mark.parametrize(
    "mutation,error",
    [
        ("schema_version = 3", "schema"),
        ('body = "documentation-issue.md"', "body"),
        ('guards = ["confirmed_gap", "target_absent", "no_equivalent_file", "approved_inputs"]', "PR route"),
        ('path = "CITATION.cff"', "destination"),
        ('"approved_citation_metadata",', "placeholders"),
    ],
)
def test_invalid_catalog_contracts_fail_explicitly(tmp_path, monkeypatch, mutation, error):
    shutil.copytree(ASSETS, tmp_path / "templates")
    path = tmp_path / "templates/catalog/documentation.toml"
    replacements = {
        "schema": "schema_version = 99",
        "body": 'body = "missing.md"',
        "PR route": "guards = []",
        "destination": 'path = "../outside"',
        "placeholders": "",
    }
    path.write_text(path.read_text().replace(mutation, replacements[error], 1))
    monkeypatch.setattr("RepoRemedy.catalog.files", lambda _: tmp_path)
    with pytest.raises(ContextError, match=error):
        load_catalog()


def test_duplicate_catalog_sources_and_invalid_placeholders(tmp_path, monkeypatch):
    shutil.copytree(ASSETS, tmp_path / "templates")
    monkeypatch.setattr("RepoRemedy.catalog.files", lambda _: tmp_path)
    path = tmp_path / "templates/catalog/extra.toml"
    path.write_text((tmp_path / "templates/catalog/documentation.toml").read_text())
    with pytest.raises(ContextError, match="Duplicate"):
        load_catalog()
    path.unlink()
    (tmp_path / "templates/bodies/documentation-issue.md").write_text("Invalid ${")
    with pytest.raises(ContextError, match="placeholder"):
        load_catalog()


@pytest.mark.parametrize(
    "old,new",
    [
        ('"verification_steps",', '"verification_steps", "verification_steps",'),
        ('sources = { RA = ["Citation"] }', "sources = { RA = [] }"),
        ('path = "CITATION.cff"', 'path = ".GIT/config"'),
    ],
)
def test_ambiguous_or_unsafe_catalog_declarations(tmp_path, monkeypatch, old, new):
    shutil.copytree(ASSETS, tmp_path / "templates")
    path = tmp_path / "templates/catalog/documentation.toml"
    path.write_text(path.read_text().replace(old, new, 1))
    monkeypatch.setattr("RepoRemedy.catalog.files", lambda _: tmp_path)
    with pytest.raises(ContextError):
        load_catalog()


def test_resolution_preserves_report_and_context_notices(snapshot):
    source = report()
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
    result = resolve_template_inputs(report(), snapshot)
    observed = json.loads(result.templates[0].inputs["observed_state"].value)
    assert observed["matching_paths"] == ["docs/SECURITY.md"]
    supported = result.templates[1].inputs["supported_versions"]
    assert supported.value == "1.x"
    assert supported.source == f"file:docs/SECURITY.md@{COMMIT}"
    assert snapshot.files[Path("docs/SECURITY.md")].content == content
    engineering = resolve_template_inputs(report("Pinned-Dependencies", origin="OSSF"), snapshot)
    inputs = engineering.templates[0].inputs
    assert ".github/workflows/test.yml" in inputs["affected_components"].value
    assert ".github/workflows/test.yml" in json.loads(inputs["observed_state"].value)["collected_paths"]
