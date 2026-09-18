"""Extract factual template values without inferring policy or approval."""

from pathlib import Path

import pytest

from RepoRemedy.catalog import load_catalog
from RepoRemedy.context.inputs import find_matching_files, resolve_inputs
from RepoRemedy.context.repository_context import RepositoryFile
from remedy_fixtures import make_report
from repository_context_test import FakeGitHub


def test_missing_and_conflicting_sections_are_not_invented(snapshot):
    remedy = load_catalog().remedies["security-policy"]
    assert remedy.pr is not None
    snapshot.files[Path("SECURITY.md")] = RepositoryFile(
        path=Path("SECURITY.md"),
        blob_sha="f" * 40,
        status="available",
        content="## Supported versions\n2.x\n",
    )
    original = snapshot.files.pop(Path("docs/SECURITY.md"))
    result = resolve_inputs(snapshot, "security-policy", remedy, remedy.pr, make_report().issues[0])
    assert "security_reporting_instructions" in result.missing_inputs
    assert result.values["supported_versions"].value == "2.x"
    snapshot.files[Path("docs/SECURITY.md")] = original
    result = resolve_inputs(snapshot, "security-policy", remedy, remedy.pr, make_report().issues[0])
    assert "supported_versions" in result.missing_inputs


def test_unreadable_sections_and_absent_description_stay_missing(snapshot):
    for file in snapshot.files.values():
        file.status = "unavailable"
        file.content = None
    snapshot.observations["repository"].value = {"name": "demo", "full_name": "acme/demo"}
    remedy = load_catalog().remedies["ra-read-me"]
    assert remedy.pr is not None
    result = resolve_inputs(snapshot, "ra-read-me", remedy, remedy.pr, make_report("ReadMe").issues[0])
    assert "project_summary" in result.missing_inputs
    assert "installation_instructions" in result.missing_inputs


def test_alternate_paths_and_absent_candidates(snapshot):
    snapshot.paths.extend([Path("docs/COPYING.txt"), Path(".github/ISSUE_TEMPLATE/bug.yml")])
    assert find_matching_files(snapshot, "ra-license-file") == [Path("docs/COPYING.txt")]
    assert find_matching_files(snapshot, "ra-issue-templates") == [Path(".github/ISSUE_TEMPLATE/bug.yml")]
    assert find_matching_files(snapshot, "unknown") == []
    snapshot.files = {}
    remedy = load_catalog().remedies["ossf-sast"]
    result = resolve_inputs(
        snapshot, "ossf-sast", remedy, remedy.issue, make_report("SAST", origin="OSSF").issues[0]
    )
    assert "affected_components" in result.missing_inputs


@pytest.mark.parametrize("remedy_id", ["ra-license-file", "ra-license", "ossf-license"])
def test_all_license_remedies_match_both_filename_stems(snapshot, remedy_id):
    expected = [Path("LICENSE"), Path("docs/CoPyInG.txt"), Path("nested/License.md")]
    snapshot.paths.extend([*reversed(expected), Path("LICENSES.md"), Path("copying-notes.txt")])
    assert find_matching_files(snapshot, remedy_id) == expected


@pytest.mark.parametrize(
    "path",
    [
        "nested/PYPROJECT.toml",
        "nested/package.json",
        "nested/Cargo.toml",
        "nested/go.mod",
        "nested/pom.xml",
        "nested/build.gradle.kts",
        "nested/Gemfile",
        "nested/composer.json",
        "nested/requirements-dev.txt",
        "nested/project.csproj",
        "nested/project.fsproj",
        "nested/uv.lock",
        "nested/Makefile",
        ".github/workflows/test.yml",
    ],
)
def test_collected_manifests_and_workflows_are_affected_components(path):
    api = FakeGitHub()
    api.file(path, "Example configuration")
    api.file("README.md", "Project guidance")
    api.file("src/main.py", "Example source")
    context = api.snapshot()
    remedy = load_catalog().remedies["ossf-sast"]
    result = resolve_inputs(
        context, "ossf-sast", remedy, remedy.issue, make_report("SAST", origin="OSSF").issues[0]
    )
    assert result.values["affected_components"].value.splitlines()[1:] == [path]
