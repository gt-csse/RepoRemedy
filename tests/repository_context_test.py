"""Repository snapshots keep immutable files distinct from live, fallible API data."""

import base64
import hashlib
import json
from typing import Any

import httpx
import pytest

from RepoRemedy.context import RepositoryContext, collect_context
from RepoRemedy.context.collect import relevant_path
from RepoRemedy.context.github import ContextError, GitHubReader

COMMIT = "a" * 40
TREE = "b" * 40
ROOT = "https://api.github.com/repos/acme/demo"


class FakeGitHub:
    def __init__(self):
        self.requests = []
        self.responses: dict[str, Any] = {
            "": {
                "name": "demo",
                "full_name": "acme/demo",
                "description": "Example project",
                "default_branch": "main",
                "private": False,
            },
            "/branches/main": {"commit": {"sha": COMMIT}},
            f"/commits/{COMMIT}": {"sha": COMMIT, "commit": {"tree": {"sha": TREE}}},
            f"/git/trees/{TREE}": {"sha": TREE, "tree": [], "truncated": False},
            "/branches/main/protection": {
                "required_pull_request_reviews": {"required_approving_review_count": 2}
            },
            "/rules/branches/main": [],
            "/automated-security-fixes": {"enabled": True},
            "/community/profile": {"files": {}},
            "/environments": {"environments": []},
            "/hooks": [
                {
                    "id": 1,
                    "active": True,
                    "events": ["push"],
                    "config": {
                        "secret": "PRIVATE",
                        "url": "https://user:password@private.example/hook?token=PRIVATE",
                    },
                    "url": "PRIVATE",
                }
            ],
            "/releases": [],
            "/contributors": [],
            f"/commits/{COMMIT}/check-runs": {"check_runs": []},
            f"/commits/{COMMIT}/statuses": [],
        }

    def file(self, path, content, mode="100644", kind="blob"):
        raw = content.encode() if isinstance(content, str) else content
        sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        self.responses[f"/git/trees/{TREE}"]["tree"].append(
            {"path": path, "sha": sha, "type": kind, "mode": mode, "size": len(raw)}
        )
        self.responses[f"/git/blobs/{sha}"] = {
            "sha": sha,
            "encoding": "base64",
            "content": base64.b64encode(raw).decode(),
        }
        return sha

    def __call__(self, request):
        self.requests.append(request)
        suffix = request.url.path.split("/repos/acme/demo", 1)[1]
        data = self.responses.get(suffix)
        if isinstance(data, httpx.Response):
            return data
        if callable(data):
            return data(request)
        if data is None:
            return httpx.Response(404, json={"message": "PRIVATE"})
        return httpx.Response(200, json=data)

    def snapshot(self, **kwargs):
        with httpx.Client(transport=httpx.MockTransport(self)) as client:
            return collect_context("acme/demo", client, **kwargs)


@pytest.fixture
def api():
    return FakeGitHub()


def test_pinned_snapshot_and_secret_free_webhook_metadata(api):
    api.file("README.md", "# Demo\n\n## Installation\nuv sync\n")
    api.file(".github/workflows/test.yml", "name: CI\n")
    api.file("src/app.py", "must not run")
    snapshot = api.snapshot()
    assert snapshot.requested_ref == "main" and snapshot.commit_sha == COMMIT
    assert snapshot.tree_sha == TREE and snapshot.tree_complete
    assert set(snapshot.files) == {"README.md", ".github/workflows/test.yml"}
    assert "src/app.py" in snapshot.paths
    assert snapshot.files["README.md"].content.startswith("# Demo")
    assert all(r.method == "GET" for r in api.requests)
    assert sum(r.url.path.endswith("/repos/acme/demo/branches/main") for r in api.requests) == 1
    assert all("/contents/" not in r.url.path for r in api.requests)
    assert snapshot.observations["repository"].scope == "live"
    assert snapshot.observations["tree"].scope == "commit"
    assert "PRIVATE" not in snapshot.model_dump_json() and "password" not in snapshot.model_dump_json()
    assert RepositoryContext.model_validate_json(snapshot.model_dump_json()) == snapshot
    assert snapshot.started_at <= snapshot.completed_at


def test_recorded_commit_and_enterprise_host(api):
    with httpx.Client(transport=httpx.MockTransport(api)) as client:
        snapshot = collect_context(
            "https://github.gatech.edu:8443/acme/demo", client, ref=COMMIT, token="TOKEN"
        )
    assert snapshot.repository == "github.gatech.edu:8443/acme/demo"
    assert snapshot.settings_branch == "main"
    assert all(r.url.host == "github.gatech.edu" and r.url.port == 8443 for r in api.requests)
    assert all(r.url.path.startswith("/api/v3/repos/") for r in api.requests)
    assert all(r.headers["Authorization"] == "Bearer TOKEN" for r in api.requests)
    assert sum(r.url.path.endswith("/repos/acme/demo/branches/main") for r in api.requests) == 1
    assert "TOKEN" not in snapshot.model_dump_json()


@pytest.mark.parametrize(
    "suffix,payload",
    [
        ("", httpx.Response(403, json={"message": "PRIVATE"})),
        ("", {"full_name": "other/repo"}),
        ("/branches/main", {}),
        (f"/commits/{COMMIT}", {"sha": "c" * 40}),
        (f"/commits/{COMMIT}", {"sha": COMMIT}),
        (f"/commits/{COMMIT}", []),
        ("", {"full_name": "acme/demo", "default_branch": None}),
    ],
)
def test_core_identity_failures_are_fatal_and_sanitized(api, suffix, payload):
    api.responses[suffix] = payload
    with pytest.raises(ContextError) as error:
        api.snapshot()
    assert "PRIVATE" not in str(error.value)


def test_branch_with_slash_is_encoded(api):
    api.responses["/branches/release/stable"] = {"commit": {"sha": COMMIT}}
    snapshot = api.snapshot(ref="release/stable")
    assert snapshot.settings_branch == "release/stable"
    assert b"release%2Fstable" in api.requests[1].url.raw_path


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_optional_failures_do_not_become_disabled_settings(api, status):
    api.responses["/automated-security-fixes"] = httpx.Response(status, json={"message": "PRIVATE"})
    observation = api.snapshot().observations["dependabot_security_updates"]
    assert observation.status == "unavailable" and observation.value is None
    assert observation.reason == f"GitHub HTTP {status}"


@pytest.mark.parametrize(
    "tree",
    [
        None,
        [],
        {},
        {"tree": [], "truncated": True},
        {
            "tree": [False, {"path": "../README.md"}, {"path": "/README.md"}, {"path": "x\\README.md"}],
            "truncated": False,
        },
    ],
)
def test_incomplete_inventory_never_proves_absence(api, tree):
    api.responses[f"/git/trees/{TREE}"] = tree
    assert not api.snapshot().tree_complete


def test_duplicate_paths_make_inventory_incomplete(api):
    api.file("README.md", "Hello")
    api.file("README.md", "Hello")
    assert not api.snapshot().tree_complete


@pytest.mark.parametrize("mode,kind", [("120000", "blob"), ("160000", "commit")])
def test_symlinks_and_submodules_not_followed(api, mode, kind):
    sha = api.file("README.md", "somewhere/private", mode=mode, kind=kind)
    assert api.snapshot().files["README.md"].status == "unavailable"
    assert not any(r.url.path.endswith(sha) for r in api.requests)


@pytest.mark.parametrize(
    "change",
    [
        {"content": "not base64!"},
        {"encoding": "utf-8"},
        {"sha": "c" * 40},
        {"content": 12},
        {"content": base64.b64encode(b"longer").decode()},
        {"content": base64.b64encode(b"\xff\xff").decode()},
        {"content": base64.b64encode(b"\x00x").decode()},
    ],
)
def test_invalid_blob_content_is_unavailable(api, change):
    sha = api.file("README.md", "Hi")
    api.responses[f"/git/blobs/{sha}"].update(change)
    assert api.snapshot().files["README.md"].status == "unavailable"


@pytest.mark.parametrize("limit", ["MAX_FILES", "MAX_FILE_BYTES", "MAX_CONTENT_BYTES"])
def test_file_collection_is_bounded(api, monkeypatch, limit):
    sha = api.file("README.md", "Hello")
    monkeypatch.setattr(f"RepoRemedy.context.collect.{limit}", 0)
    assert api.snapshot().files["README.md"].status == "unavailable"
    assert not any(r.url.path.endswith(sha) for r in api.requests)


def test_unreadable_blob_and_tree_directory(api):
    sha = api.file("README.md", "Hello")
    api.responses[f"/git/blobs/{sha}"] = None
    api.file("docs", "", mode="040000", kind="tree")
    assert api.snapshot().files["README.md"].reason == "GitHub HTTP 404"


@pytest.mark.parametrize(
    "path",
    [
        "AGENTS.md",
        "docs/SECURITY.rst",
        "src/AGENTS.md",
        "LICENSE",
        "COPYING.txt",
        "requirements-dev.txt",
        "nested/package.json",
        "project.csproj",
        ".circleci/config.yml",
        ".gitlab-ci.yml",
        "CITATION.cff",
        ".github/ISSUE_TEMPLATE/bug.yml",
        "Makefile",
    ],
)
def test_context_file_selection(path):
    assert relevant_path(path)


def test_api_limits_errors_and_redirects(monkeypatch):
    responses = [
        httpx.Response(302, headers={"Location": "https://evil.example"}),
        httpx.Response(200, content=b"bad json"),
        httpx.Response(200, content=b"[]" * 20),
    ]
    monkeypatch.setattr("RepoRemedy.context.github.MAX_RESPONSE_BYTES", 10)
    for response in responses:
        seen = []

        def transport(request):
            seen.append(request)
            return response

        with httpx.Client(transport=httpx.MockTransport(transport), follow_redirects=True) as client:
            result = GitHubReader("acme/demo", client, "TOKEN").read()
        assert result.status == "unavailable" and len(seen) == 1

    def timeout(request):
        raise httpx.ReadTimeout("PRIVATE", request=request)

    with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
        assert "PRIVATE" not in GitHubReader("acme/demo", client).read().model_dump_json()


def test_pagination_partial_and_limit(monkeypatch):
    monkeypatch.setattr("RepoRemedy.context.github.MAX_PAGES", 2)
    for mode in ("limit", "partial", "malformed"):

        def transport(request):
            if mode == "partial" and request.url.params["page"] == "2":
                return httpx.Response(403)
            return httpx.Response(200, json={} if mode == "malformed" else [1] * 100)

        with httpx.Client(transport=httpx.MockTransport(transport)) as client:
            result = GitHubReader("acme/demo", client).pages("/hooks")
        assert result.status == ("unavailable" if mode == "malformed" else "partial")
        assert isinstance(result.value, list)
        assert len(result.value) == (0 if mode == "malformed" else 100 if mode == "partial" else 200)


@pytest.mark.parametrize("raw,reason", [(b"\xff\xff", "UTF-8"), (b"\x00x", "Binary")])
def test_nontext_blob_with_valid_git_identity(api, raw, reason):
    api.file("README.md", raw)
    assert reason in api.snapshot().files["README.md"].reason


def test_blob_integrity_is_checked(api):
    sha = api.file("README.md", "Hi")
    api.responses[f"/git/blobs/{sha}"]["content"] = base64.b64encode(b"No").decode()
    assert "Git identity" in api.snapshot().files["README.md"].reason


@pytest.mark.parametrize("mutation", ["repository", "metadata", "timestamps", "path", "content"])
def test_saved_snapshot_consistency(api, mutation):
    from pydantic import ValidationError

    api.file("README.md", "Hello")
    data = api.snapshot().model_dump(mode="json")
    if mutation == "repository":
        data["repository"] = "https://github.com/acme/demo"
    elif mutation == "metadata":
        data["observations"].pop("repository")
    elif mutation == "timestamps":
        data["completed_at"] = "2000-01-01T00:00:00"
    elif mutation == "path":
        data["files"]["README.md"]["path"] = "other"
    else:
        data["files"]["README.md"]["content"] = None
    with pytest.raises(ValidationError):
        RepositoryContext.model_validate(data)


def test_malformed_optional_records_mark_observation_partial(api):
    api.responses["/releases"] = [{"tag_name": "v1"}, "invalid record"]
    result = api.snapshot().observations["releases"]
    assert result.status == "partial" and result.value == [{"tag_name": "v1"}]
