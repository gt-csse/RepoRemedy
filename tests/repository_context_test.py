"""Repository snapshots keep immutable files distinct from live, fallible API data."""

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from RepoRemedy.context import RepositoryContext, collect_context
from RepoRemedy.context.repository_context import is_relevant_path
from RepoRemedy.context.github import ContextError

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
    assert set(snapshot.files) == {Path("README.md"), Path(".github/workflows/test.yml")}
    assert Path("src/app.py") in snapshot.paths
    assert snapshot.files[Path("README.md")].content.startswith("# Demo")
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
        {"sha": TREE, "tree": [], "truncated": True},
        {
            "sha": TREE,
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
    assert api.snapshot().files[Path("README.md")].status == "unavailable"
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
    assert api.snapshot().files[Path("README.md")].status == "unavailable"


@pytest.mark.parametrize("limit", ["MAX_FILES", "MAX_FILE_BYTES", "MAX_CONTENT_BYTES"])
def test_file_collection_is_bounded(api, monkeypatch, limit):
    sha = api.file("README.md", "Hello")
    monkeypatch.setattr(f"RepoRemedy.context.repository_context.{limit}", 0)
    assert api.snapshot().files[Path("README.md")].status == "unavailable"
    assert not any(r.url.path.endswith(sha) for r in api.requests)


def test_unreadable_blob_and_tree_directory(api):
    sha = api.file("README.md", "Hello")
    api.responses[f"/git/blobs/{sha}"] = None
    api.file("docs", "", mode="040000", kind="tree")
    assert api.snapshot().files[Path("README.md")].reason == "GitHub HTTP 404"


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
    assert is_relevant_path(Path(path))


@pytest.mark.parametrize("raw,reason", [(b"\xff\xff", "UTF-8"), (b"\x00x", "Binary")])
def test_nontext_blob_with_valid_git_identity(api, raw, reason):
    api.file("README.md", raw)
    assert reason in api.snapshot().files[Path("README.md")].reason


def test_blob_integrity_is_checked(api):
    sha = api.file("README.md", "Hi")
    api.responses[f"/git/blobs/{sha}"]["content"] = base64.b64encode(b"No").decode()
    assert "Git identity" in api.snapshot().files[Path("README.md")].reason


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


@pytest.mark.parametrize("length", [40, 64])
def test_mixed_case_git_identities_are_normalized_across_api_and_models(api, length):
    from RepoRemedy.context.repository_context import RepositoryFile

    commit = ("AbCdEf0123" * 7)[:length]
    tree = ("bCdEfA9876" * 7)[:length]
    original_blob = api.file("docs/README.md", "Hello")
    blob_bytes = b"blob 5\0Hello"
    blob_sha = (
        hashlib.sha1(blob_bytes).hexdigest() if length == 40 else hashlib.sha256(blob_bytes).hexdigest()
    )
    tree_data = api.responses[f"/git/trees/{TREE}"]
    tree_data["sha"] = tree
    tree_data["tree"][0]["sha"] = blob_sha.upper()
    blob_data = api.responses.pop(f"/git/blobs/{original_blob}")
    blob_data["sha"] = blob_sha.upper()
    api.responses[f"/git/blobs/{blob_sha}"] = blob_data
    api.responses[f"/git/trees/{tree.lower()}"] = tree_data
    api.responses[f"/commits/{commit.lower()}"] = {"sha": commit, "commit": {"tree": {"sha": tree}}}
    api.responses["/branches/main"] = {"commit": {"sha": commit}}

    for ref in (commit, "main"):
        snapshot = api.snapshot(ref=ref)
        assert snapshot.commit_sha == commit.lower() and snapshot.tree_sha == tree.lower()
        assert snapshot.files[Path("docs/README.md")].blob_sha == blob_sha
        assert snapshot.files[Path("docs/README.md")].content == "Hello"
    assert not any(request.url.path.endswith(f"/branches/{commit}") for request in api.requests)

    data = snapshot.model_dump(mode="json")
    data.update(commit_sha=commit, tree_sha=tree)
    data["files"]["docs/README.md"]["blob_sha"] = blob_sha.upper()
    assert RepositoryContext.model_validate(data) == snapshot
    assert (
        RepositoryFile(path=Path("docs/README.md"), blob_sha=blob_sha.upper(), status="unavailable").blob_sha
        == blob_sha
    )


@pytest.mark.parametrize("invalid", ["g" * 40, "a" * 39, "a" * 41, "a" * 63, "a" * 65, "a" * 40 + "\n"])
def test_all_model_git_identities_use_the_same_validation(api, invalid):
    from pydantic import ValidationError

    api.file("README.md", "Hello")
    snapshot = api.snapshot()
    for field in ("commit_sha", "tree_sha", "blob_sha"):
        data = snapshot.model_dump(mode="json")
        if field == "blob_sha":
            data["files"]["README.md"][field] = invalid
        else:
            data[field] = invalid
        with pytest.raises(ValidationError):
            RepositoryContext.model_validate(data)


def test_repository_paths_are_typed_and_json_remains_posix(api):
    api.file("docs", "", mode="040000", kind="tree")
    api.file("docs/README.md", "Hello")
    snapshot = api.snapshot()
    assert all(isinstance(path, Path) for path in snapshot.paths)
    assert all(isinstance(path, Path) for path in snapshot.files)
    assert all(isinstance(file.path, Path) for file in snapshot.files.values())
    assert snapshot.observations["tree"].value["directories"] == ["docs"]
    assert snapshot.observations["tree"].value["path_count"] == 2
    encoded = json.loads(snapshot.model_dump_json())
    assert encoded["paths"] == ["docs", "docs/README.md"]
    assert encoded["files"]["docs/README.md"]["path"] == "docs/README.md"
    assert RepositoryContext.model_validate_json(snapshot.model_dump_json()) == snapshot


@pytest.mark.parametrize("path", ["", "C:/README.md", "C:README.md"])
def test_invalid_repository_paths_are_rejected_before_path_conversion(api, path):
    api.file(path, "Hello")
    snapshot = api.snapshot()
    assert not snapshot.tree_complete and not snapshot.paths and not snapshot.files


@pytest.mark.parametrize("response_sha", [None, "c" * 40, "not-a-sha", 123])
def test_untrusted_tree_identity_is_rejected_before_reading_entries(api, response_sha):
    api.file("README.md", "Must not be collected from another tree")
    tree = api.responses[f"/git/trees/{TREE}"]
    if response_sha is None:
        tree.pop("sha")
    else:
        tree["sha"] = response_sha
    snapshot = api.snapshot()
    assert not snapshot.tree_complete and not snapshot.paths and not snapshot.files
    assert snapshot.observations["tree"].status == "partial"
    assert "Tree response identity" in snapshot.observations["tree"].reason
    assert not any("/git/blobs/" in request.url.path for request in api.requests)


@pytest.mark.parametrize("entry_sha", [None, "bad-sha", 123, "a" * 39])
def test_malformed_entry_identity_keeps_valid_files_and_marks_inventory_incomplete(api, entry_sha):
    invalid_blob = api.file("README.md", "Invalid entry")
    api.file("SECURITY.md", "Valid policy")
    entry = api.responses[f"/git/trees/{TREE}"]["tree"][0]
    if entry_sha is None:
        entry.pop("sha")
    else:
        entry["sha"] = entry_sha
    snapshot = api.snapshot()
    assert not snapshot.tree_complete
    assert Path("README.md") in snapshot.paths and Path("README.md") not in snapshot.files
    assert snapshot.files[Path("SECURITY.md")].content == "Valid policy"
    assert snapshot.observations["tree"].status == "partial"
    assert "invalid or missing object identity" in snapshot.observations["tree"].reason
    assert not any(request.url.path.endswith(invalid_blob) for request in api.requests)


@pytest.mark.parametrize("text", ["", "# Readme\r\n\nExample\n"])
def test_utf8_bom_is_preserved_through_collection_and_json_round_trip(api, text):
    raw = b"\xef\xbb\xbf" + text.encode("utf-8")
    sha = api.file("README.md", raw)
    snapshot = api.snapshot()
    for result in (snapshot, RepositoryContext.model_validate_json(snapshot.model_dump_json())):
        file = result.files[Path("README.md")]
        assert file.content is not None and file.content.startswith("\ufeff")
        assert file.content.encode("utf-8") == raw
        assert (
            hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + file.content.encode()).hexdigest() == sha
        )


@pytest.mark.parametrize("full_name", [None, "other/repo", 123, {}])
def test_saved_snapshot_rejects_missing_or_mismatched_metadata_identity(api, full_name):
    from pydantic import ValidationError

    data = api.snapshot().model_dump(mode="json")
    metadata = data["observations"]["repository"]["value"]
    if full_name is None:
        metadata.pop("full_name")
    else:
        metadata["full_name"] = full_name
    with pytest.raises(ValidationError, match="metadata identity"):
        RepositoryContext.model_validate_json(json.dumps(data))


@pytest.mark.parametrize("repository", ["acme/demo", "github.example:8443/acme/demo"])
def test_saved_snapshot_accepts_equivalent_metadata_identity_on_each_host(api, repository):
    data = api.snapshot().model_dump(mode="json")
    data["repository"] = repository
    data["observations"]["repository"]["value"]["full_name"] = "Acme/DeMo"
    assert RepositoryContext.model_validate_json(json.dumps(data)).repository == repository


@pytest.mark.parametrize(
    "status,content,valid",
    [
        ("available", None, False),
        ("available", "", True),
        ("available", "Example", True),
        ("unavailable", None, True),
        ("unavailable", "", False),
        ("unavailable", "Example", False),
    ],
)
def test_saved_snapshot_file_status_and_content_must_agree(api, status, content, valid):
    from pydantic import ValidationError

    api.file("README.md", content or "")
    data = api.snapshot().model_dump(mode="json")
    data["files"]["README.md"].update(status=status, content=content)
    if valid:
        assert (
            RepositoryContext.model_validate_json(json.dumps(data)).files[Path("README.md")].status == status
        )
    else:
        with pytest.raises(ValidationError, match="availability"):
            RepositoryContext.model_validate_json(json.dumps(data))
