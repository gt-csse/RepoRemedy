r"""Live tests for context/repository_context.py.

PR #6 includes an opt-in integration test for the internal context collector.
It uses [ketanbj/reporemedy-live-fixture](https://github.com/ketanbj/reporemedy-live-fixture),
a disposable public repository containing only synthetic data. Its
[coverage matrix](https://github.com/ketanbj/reporemedy-live-fixture/blob/main/FIXTURE-COVERAGE.md)
accounts for all 68 catalog remedies and explains which conditions are seeded,
policy-dependent, historical or unavailable on this host.

## Run

Use an account/token with access to the fixture's administrative reads (including
webhooks and repository settings). Authenticate `gh` to that account, then run:

```shell
REPOREMEDY_LIVE_TEST=1 REPOREMEDY_TOKEN="$(gh auth token --hostname github.com)" \
  uv run pytest tests/live/repository_context_test.py --no-cov
```

Alternatively, set `REPOREMEDY_TOKEN` through your usual secret-management mechanism.
The token is passed in memory, never saved in the fixture or test contract. An
explicitly enabled run without a token fails. API permission errors also fail the
expected-read assertions; they do not silently skip the live checks.

Ordinary `uv run pytest` skips these tests before any HTTP request. The live suite
uses real GitHub GET requests only; it does not create, repair, publish to or reset
the fixture. Running it requires network access and consumes API read quota.

## What is verified

- `main` and the recorded commit have different, correctly pinned file contents.
- The complete tree includes source/artifact paths, while downloaded blobs are
  limited to relevant context files and match their Git identities.
- Missing community files, weak repository settings and an unprotected branch are
  preserved as observations. A protection API 404 remains unavailable data.
- Symlink, binary and oversized content is excluded with explicit reasons.
- Release, environment, contributor, CI-status and live community observations
  come from the actual API. The failed status is synthetic, not an executed test.
- Webhook metadata excludes callback URLs and configuration, and the authentication
  token is absent from serialized snapshots. Anonymous restricted access and a
  nonexistent branch fail explicitly.

The fixture's Actions are disabled, hooks are inactive and use a reserved
`example.invalid` destination, and no dependency installation or target code runs.
This is a context-collection test, not an assertion that every auditor check fails.
A newly created repository cannot represent long-term inactivity, contradictory
policy choices or Enterprise-only features. Enterprise, malformed responses,
rate limits and truncated trees remain covered by deterministic mocked tests.

## Maintaining the fixture

The [test contract](../fixtures/repository_context_live.json) records the
repository and exact `main`/historical commit SHAs plus expected content. Changes
to `main` or its live settings deliberately fail assertions so drift is visible.
Keep it stable during runs; use separate branches for later publication tests.
If intentionally reseeding, update the contract and expected observations together,
then run the live suite before committing them. Do not replace expected facts with
assertions that accept every availability state.
"""

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
    contract = json.loads((Path(__file__).parents[1] / "fixtures/repository_context_live.json").read_text())
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
    assert Path("README.md") not in current.paths
    assert recorded.files[Path("README.md")].content == contract["recorded_readme"]
    assert current.files[Path("docs/SUPPORT.md")].content == contract["support_main"]
    assert recorded.files[Path("docs/SUPPORT.md")].content == contract["support_recorded"]


def test_live_file_inventory_and_blob_content_integrity(live):
    _, current, recorded, _ = live
    assert {
        Path(name) for name in ("pyproject.toml", "package.json", ".github/workflows/fixture.yml")
    } <= current.files.keys()
    assert {Path("src/demo.py"), Path("artifacts/demo.bin")} <= set(current.paths)
    assert not {Path("src/demo.py"), Path("artifacts/demo.bin")} & current.files.keys()
    assert not {
        Path(name)
        for name in ("CONTRIBUTING.md", "SECURITY.md", "LICENSE", "CODE_OF_CONDUCT.md", "CITATION.cff")
    } & set(current.paths)
    assert "requests" in current.files[Path("pyproject.toml")].content
    assert "actions/checkout@main" in current.files[Path(".github/workflows/fixture.yml")].content
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
        file = current.files[Path(path)]
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
        hooks = GitHubReader(contract["repository"], client).read_pages("/hooks")
        assert hooks.reason is not None
        assert hooks.status == "unavailable" and hooks.reason.startswith("GitHub HTTP ")
        with pytest.raises(ContextError, match="requested branch"):
            collect_context(
                contract["repository"],
                client,
                ref="fixture/does-not-exist",
                token=os.environ["REPOREMEDY_TOKEN"],
            )
