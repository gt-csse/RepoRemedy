"""Selected publication, immutable-content checks and interruption recovery."""

import json

import httpx
import pytest

from RepoRemedy.propose import ProposalBundle, propose_remedies
from RepoRemedy.publication.publish import get_publication_key, publish_remedies
from RepoRemedy.publication.receipts import PublicationError, ReceiptJournal, ReceiptStore
from publication_fixtures import PublishingGitHub, NEW_COMMIT, NEW_TREE
from remedy_fixtures import make_report
from repository_context_test import COMMIT, TREE


def publish(api, bundle, path, selected=None, **kwargs):
    with httpx.Client(transport=httpx.MockTransport(api)) as client:
        return publish_remedies(
            bundle,
            selected or [bundle.proposals[0].remedy_id],
            bundle.repository,
            path,
            client,
            token="PRIVATE",
            confirmed=True,
            **kwargs,
        )


def test_only_selected_settings_remedy_creates_issue_and_receipt(tmp_path):
    api = PublishingGitHub()
    source = make_report("RequireApprovals")
    source.issues.append(make_report("IssueTemplates").issues[0])
    bundle = propose_remedies(
        source,
        api.snapshot(),
        {"ra-require-approvals": {"approved_value": "3", "reported_expected_value": "3"}},
        approved_inputs={"ra-require-approvals", "ra-issue-templates"},
    )
    path = tmp_path / "receipts.json"
    result = publish(api, bundle, path, ["ra-require-approvals"])
    assert [endpoint for endpoint, _ in api.posts] == ["/issues"]
    payload = api.posts[0][1]
    assert "Maintainer-approved value: 3" in payload["body"]
    assert "PRIVATE" not in json.dumps(payload)
    assert "reporemedy:v1:" in payload["body"]
    receipt = result.receipts["ra-require-approvals"]
    assert receipt.status == "created" and receipt.route == "issue"
    assert receipt.url == "https://github.com/acme/demo/issues/1"
    assert receipt.updated_at.tzinfo is not None
    assert ReceiptJournal.model_validate_json(path.read_bytes()) == result
    assert "PRIVATE" not in path.read_text()
    assert not (tmp_path / "receipts.json.lock").exists()


def test_file_proposal_creates_atomic_commit_and_draft_pr(tmp_path):
    api = PublishingGitHub()
    api.file("src/app.py", "keep unchanged")
    bundle = api.bundle("IssueTemplates")
    bundle = ProposalBundle.model_validate_json(bundle.model_dump_json())
    result = publish(api, bundle, tmp_path / "receipts.json")
    assert [endpoint for endpoint, _ in api.posts] == ["/git/trees", "/git/commits", "/git/refs", "/pulls"]
    tree, commit, ref, pr = [payload for _, payload in api.posts]
    assert bundle.proposals[0].content is not None
    assert tree["base_tree"] == TREE and len(tree["tree"]) == 2
    assert {entry["path"] for entry in tree["tree"]} == {
        f.path.as_posix() for f in bundle.proposals[0].content.files
    }
    assert commit["parents"] == [COMMIT] and commit["tree"] == NEW_TREE
    assert ref["ref"].startswith("refs/heads/reporemedy/") and ref["sha"] == NEW_COMMIT
    assert (
        pr["draft"] is True and pr["base"] == "main" and pr["head"] == ref["ref"].removeprefix("refs/heads/")
    )
    receipt = result.receipts["ra-issue-templates"]
    assert receipt.commit_sha == NEW_COMMIT and receipt.url.endswith("/pull/1")


@pytest.mark.parametrize("confirmed,token", [(False, "PRIVATE"), (True, "")])
def test_confirmation_and_token_are_required_before_network(tmp_path, confirmed, token):
    api = PublishingGitHub()
    bundle = api.bundle()
    api.requests.clear()
    with httpx.Client(transport=httpx.MockTransport(api)) as client, pytest.raises(PublicationError):
        publish_remedies(
            bundle,
            ["security-policy"],
            "acme/demo",
            tmp_path / "receipt.json",
            client,
            token=token,
            confirmed=confirmed,
        )
    assert not api.requests and not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "mutation",
    [
        "target",
        "context_repository",
        "report_repository",
        "base",
        "report_sha",
        "context_sha",
        "catalog_sha",
        "missing",
        "duplicate_selection",
        "empty_selection",
        "not_ready",
        "no_content",
        "unknown",
        "duplicate_proposal",
        "findings",
        "empty_findings",
        "multiple_findings",
        "title",
        "guards",
    ],
)
def test_invalid_bundle_or_selection_never_writes(tmp_path, mutation):
    api = PublishingGitHub()
    bundle = api.bundle()
    ids = ["security-policy"]
    repo = "acme/demo"
    if mutation == "target":
        repo = "github.example/acme/demo"
    elif mutation == "context_repository":
        bundle.context.repository = "other/repo"
    elif mutation == "report_repository":
        bundle.report.repository = "other/repo"
    elif mutation == "base":
        bundle.base_commit = "f" * 40
    elif mutation == "report_sha":
        bundle.report_sha256 = "f" * 64
    elif mutation == "context_sha":
        bundle.context_sha256 = "f" * 64
    elif mutation == "catalog_sha":
        bundle.catalog_sha256 = "f" * 64
    elif mutation == "missing":
        bundle.proposals = []
    elif mutation == "duplicate_selection":
        ids *= 2
    elif mutation == "empty_selection":
        ids = []
    elif mutation == "not_ready":
        bundle.proposals[0].status = "needs-review"
    elif mutation == "no_content":
        bundle.proposals[0].content = None
    elif mutation == "unknown":
        ids = ["unknown"]
    elif mutation == "duplicate_proposal":
        bundle.proposals *= 2
    elif mutation == "findings":
        bundle.proposals[0].findings = [make_report("Private").issues[0]]
    elif mutation == "empty_findings":
        bundle.proposals[0].findings = []
    elif mutation == "multiple_findings":
        bundle.proposals[0].findings *= 2
    elif mutation == "title":
        bundle.proposals[0].content.title = "Edited"
    elif mutation == "guards":
        bundle.proposals[0].guards["approved_inputs"] = True
    with httpx.Client(transport=httpx.MockTransport(api)) as client, pytest.raises(ValueError):
        publish_remedies(
            bundle, ids, repo, tmp_path / "receipts.json", client, token="PRIVATE", confirmed=True
        )
    assert not api.posts


@pytest.mark.parametrize(
    "change",
    [
        "branch",
        "settings",
        "inherited",
        "file",
        "permission",
        "archived",
        "disabled",
        "issues_disabled",
        "unreadable",
    ],
)
def test_stale_or_inaccessible_target_blocks_publication(tmp_path, change):
    api = PublishingGitHub()
    check = (
        "RequireApprovals"
        if change == "settings"
        else "IssueTemplates"
        if change == "permission"
        else "SecurityPolicy"
    )
    bundle = api.bundle(check)
    if change == "branch":
        api.responses["/branches/main"]["commit"]["sha"] = "f" * 40
    elif change == "settings":
        api.responses["/branches/main/protection"]["required_pull_request_reviews"][
            "required_approving_review_count"
        ] = 4
    elif change == "inherited":
        api.responses["/community/profile"] = {"files": {"security": {"html_url": "inherited"}}}
    elif change == "file":
        api.file("SECURITY.md", "now exists")
    elif change == "permission":
        api.responses[""]["permissions"] = {"push": False}
    elif change == "archived":
        api.responses[""]["archived"] = True
    elif change == "disabled":
        api.responses[""]["disabled"] = True
    elif change == "issues_disabled":
        api.responses[""]["has_issues"] = False
    else:
        api.responses[""] = httpx.Response(403)
    with pytest.raises(ValueError):
        publish(api, bundle, tmp_path / "receipt.json")
    assert not api.posts
