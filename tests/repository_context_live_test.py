"""Opt-in, read-only integration tests against the versioned GitHub fixture."""

import hashlib
import json
import os
from pathlib import Path

import httpx
import pytest

from RepoRemedy.context import RepositoryContext, collect_context
from RepoRemedy.context.github import ContextError, GitHubReader

pytestmark = pytest.mark.skipif(
    os.environ.get("REPOREMEDY_LIVE_TEST") != "1",
    reason="Set REPOREMEDY_LIVE_TEST=1 to read the live fixture",
)


@pytest.fixture(scope="module")
def live():
    contract = json.loads((Path(__file__).parent / "fixtures/repository_context_live.json").read_text())
    token = os.environ.get("REPOREMEDY_TOKEN")
    if not token:
        pytest.fail("Live tests require REPOREMEDY_TOKEN with access to the fixture's administrative reads")
    requests = []
    with httpx.Client(
        trust_env=False, event_hooks={"request": [lambda request: requests.append(request.method)]}
    ) as client:
        current = collect_context(contract["repository"], client, token=token)
        recorded = collect_context(contract["repository"], client, ref=contract["recorded_sha"], token=token)
    if any(token in snapshot.model_dump_json() for snapshot in (current, recorded)):
        pytest.fail("A snapshot contains the authentication token")
    return contract, current, recorded, requests


def test_live_branch_and_recorded_commit_use_different_immutable_file_content(live):
    contract, current, recorded, methods = live
    assert methods and set(methods) == {"GET"}
    assert current.repository == recorded.repository == contract["repository"]
    assert current.requested_ref == "main" and current.commit_sha == contract["main_sha"]
    assert recorded.requested_ref == recorded.commit_sha == contract["recorded_sha"]
    assert current.tree_complete and recorded.tree_complete and current.tree_sha != recorded.tree_sha
    assert "README.md" not in current.paths
    assert recorded.files["README.md"].content == contract["recorded_readme"]
    assert current.files["docs/SUPPORT.md"].content == contract["support_main"]
    assert recorded.files["docs/SUPPORT.md"].content == contract["support_recorded"]


def test_live_file_inventory_and_blob_content_integrity(live):
    _, current, recorded, _ = live
    assert {"pyproject.toml", "package.json", ".github/workflows/fixture.yml"} <= current.files.keys()
    assert {"src/demo.py", "artifacts/demo.bin"} <= set(current.paths)
    assert not {"src/demo.py", "artifacts/demo.bin"} & current.files.keys()
    assert not {"CONTRIBUTING.md", "SECURITY.md", "LICENSE", "CODE_OF_CONDUCT.md", "CITATION.cff"} & set(
        current.paths
    )
    assert "requests" in current.files["pyproject.toml"].content
    assert "actions/checkout@main" in current.files[".github/workflows/fixture.yml"].content
    for snapshot in (current, recorded):
        for file in snapshot.files.values():
            if file.status == "available":
                raw = file.content.encode()
                digest = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
                assert digest == file.blob_sha
        assert RepositoryContext.model_validate_json(snapshot.model_dump_json()) == snapshot


def test_live_symlink_binary_and_oversized_content_are_not_used(live):
    _, current, _, _ = live
    expected = {
        ".github/context-link": "Symlink",
        ".github/binary.dat": "Binary",
        ".github/oversized.txt": "size limit",
    }
    for path, reason in expected.items():
        file = current.files[path]
        assert file.status == "unavailable" and file.content is None
        assert reason in file.reason


def test_live_repository_settings_and_unprotected_branch(live):
    _, current, recorded, _ = live
    for snapshot in (current, recorded):
        observations = snapshot.observations
        metadata = observations["repository"]
        assert metadata.status == "available" and metadata.scope == "live"
        assert metadata.value["default_branch"] == "main" and metadata.value["private"] is False
        assert not metadata.value["description"]
        for field in (
            "has_issues",
            "has_wiki",
            "has_projects",
            "allow_auto_merge",
            "delete_branch_on_merge",
            "web_commit_signoff_required",
        ):
            assert metadata.value[field] is False
        assert observations["branch"].value["protected"] is False
        # Even with admin access, an unprotected branch returns 404. It remains unavailable, not false.
        assert observations["branch_protection"].status == "unavailable"
        assert observations["branch_protection"].reason == "GitHub HTTP 404"
        assert observations["branch_rules"].status == "available" and observations["branch_rules"].value == []
        assert observations["dependabot_security_updates"].value["enabled"] is False
        assert observations["tree"].scope == "commit" and snapshot.settings_branch == "main"


def test_live_release_environment_ci_and_community_observations(live):
    _, current, recorded, _ = live
    observations = current.observations
    for name in (
        "releases",
        "environments",
        "contributors",
        "check_runs",
        "commit_statuses",
        "community_profile",
    ):
        assert observations[name].status == "available", (name, observations[name].reason)
    assert any(release["tag_name"] == "fixture-v0" for release in observations["releases"].value)
    assert any(
        env["name"] == "unprotected" and not env["protection_rules"]
        for env in observations["environments"].value
    )
    assert observations["contributors"].value
    assert observations["check_runs"].value == []
    assert any(
        status["context"] == "fixture/no-tests" and status["state"] == "failure"
        for status in observations["commit_statuses"].value
    )
    assert recorded.observations["commit_statuses"].value == []
    # Community metadata is live even when file evidence is historical.
    assert (
        observations["community_profile"].scope == recorded.observations["community_profile"].scope == "live"
    )


def test_live_webhook_metadata_excludes_private_configuration(live):
    _, current, _, _ = live
    hooks = current.observations["webhooks"]
    assert hooks.status == "available" and len(hooks.value) == 2
    for hook in hooks.value:
        assert set(hook) == {"id", "name", "active", "events"} and hook["active"] is False
    snapshot = current.model_dump_json()
    assert "example.invalid/reporemedy" not in snapshot
    assert "fixture-only-not-a-credential" not in snapshot


def test_live_restricted_anonymous_read_and_missing_ref(live):
    contract, _, _, _ = live
    with httpx.Client(trust_env=False) as client:
        hooks = GitHubReader(contract["repository"], client).pages("/hooks")
        assert hooks.reason is not None
        assert hooks.status == "unavailable" and hooks.reason.startswith("GitHub HTTP ")
        with pytest.raises(ContextError, match="requested branch"):
            collect_context(
                contract["repository"],
                client,
                ref="fixture/does-not-exist",
                token=os.environ["REPOREMEDY_TOKEN"],
            )
