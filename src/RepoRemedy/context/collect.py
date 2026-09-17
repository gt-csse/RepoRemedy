# noqa: CPY001
"""Capture immutable file content and independently timestamped live GitHub facts."""

import base64
import binascii
import datetime
import hashlib
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING

from RepoRemedy.context.github import ContextError, GitHubReader, segment
from RepoRemedy.context.models import Observation, RepositoryContext, RepositoryFile

if TYPE_CHECKING:
    import httpx
    from pydantic import JsonValue

MAX_FILES = 200
MAX_FILE_BYTES = 256 * 1024
MAX_CONTENT_BYTES = 5 * 1024 * 1024
SHA = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
METADATA_FIELDS = (
    "name",
    "full_name",
    "description",
    "default_branch",
    "private",
    "visibility",
    "archived",
    "is_template",
    "has_issues",
    "has_wiki",
    "has_projects",
    "has_discussions",
    "allow_merge_commit",
    "allow_squash_merge",
    "allow_rebase_merge",
    "allow_auto_merge",
    "delete_branch_on_merge",
    "allow_update_branch",
    "web_commit_signoff_required",
    "merge_commit_title",
    "merge_commit_message",
    "squash_merge_commit_title",
    "squash_merge_commit_message",
    "security_and_analysis",
    "license",
    "pushed_at",
)
MANIFEST_NAMES = {
    "pyproject.toml",
    "setup.cfg",
    "setup.py",
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "uv.lock",
    "pipfile",
    "pipfile.lock",
    "cargo.toml",
    "cargo.lock",
    "go.mod",
    "go.sum",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "gemfile",
    "gemfile.lock",
    "composer.json",
    "composer.lock",
    "makefile",
    "cmakelists.txt",
    "tox.ini",
    "pytest.ini",
    ".pre-commit-config.yaml",
    "renovate.json",
    "renovate.json5",
    ".renovaterc",
    ".renovaterc.json",
    ".gitmodules",
}
DOC_NAMES = {
    "readme",
    "contributing",
    "security",
    "code_of_conduct",
    "support",
    "license",
    "copying",
    "authors",
}


def relevant_path(path: str) -> bool:
    """Select guidance, community files, workflows and dependency/build configuration."""
    lower = path.lower()
    name = PurePosixPath(lower).name
    return (
        name.split(".")[0] in DOC_NAMES
        or name in {"agents.md", "codeowners", "citation.cff"}
        or name in MANIFEST_NAMES
        or (name.startswith("requirements") and name.endswith(".txt"))
        or name.endswith((".csproj", ".fsproj"))
        or lower.startswith((".github/", ".circleci/"))
        or name in {".gitlab-ci.yml", ".travis.yml", "jenkinsfile", "azure-pipelines.yml"}
    )


def _required(result: Observation, name: str) -> dict[str, JsonValue]:
    if result.status != "available" or not isinstance(result.value, dict):
        message = f"Cannot retrieve {name}: {result.reason or 'unexpected response'}"
        raise ContextError(message)
    return result.value


def _sha(value: JsonValue) -> str:
    if not isinstance(value, str) or not SHA.fullmatch(value):
        message = "GitHub returned an invalid commit, tree or blob identity"
        raise ContextError(message)
    return value


def _project(result: Observation, fields: tuple[str, ...]) -> Observation:
    """Retain useful facts without webhook destinations, credentials or response bodies."""
    if isinstance(result.value, list):
        records = [item for item in result.value if isinstance(item, dict)]
        if len(records) != len(result.value):
            result.status = "partial"
            result.reason = "Response contained malformed records"
        result.value = [{key: item[key] for key in fields if key in item} for item in records]
    return result


def _live_observations(reader: GitHubReader, branch: str, commit: str) -> dict[str, Observation]:
    branch_path = segment(branch)
    observations = {
        "branch_protection": reader.read(f"/branches/{branch_path}/protection"),
        "branch_rules": reader.pages(f"/rules/branches/{branch_path}"),
        "dependabot_security_updates": reader.read("/automated-security-fixes"),
        "community_profile": reader.read("/community/profile"),
        "environments": _project(reader.pages("/environments", "environments"), ("name", "protection_rules")),
        "webhooks": _project(reader.pages("/hooks"), ("id", "name", "active", "events")),
        "releases": _project(reader.pages("/releases"), ("tag_name", "published_at", "draft", "prerelease")),
        "contributors": _project(reader.pages("/contributors"), ("login", "contributions", "type")),
        "check_runs": _project(
            reader.pages(f"/commits/{commit}/check-runs", "check_runs"),
            ("name", "status", "conclusion", "head_sha"),
        ),
        "commit_statuses": _project(reader.pages(f"/commits/{commit}/statuses"), ("context", "state", "sha")),
    }
    observations["webhooks"].reason = (
        "Only non-secret webhook metadata is retained; authentication must be verified privately. "
        + (observations["webhooks"].reason or "")
    ).strip()
    return observations


def _files(reader: GitHubReader, tree: Observation) -> tuple[list[str], dict[str, RepositoryFile], bool]:  # noqa: PLR0915 - bounded per-file collection and explicit failure states
    value = tree.value
    if tree.status != "available" or not isinstance(value, dict) or not isinstance(value.get("tree"), list):
        return [], {}, False
    entries = value["tree"]
    assert isinstance(entries, list)
    complete = value.get("truncated") is False
    paths: list[str] = []
    seen: set[str] = set()
    files: dict[str, RepositoryFile] = {}
    content_bytes = 0
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            complete = False
            continue
        path = entry["path"]
        assert isinstance(path, str)
        if path.startswith("/") or ".." in path.split("/") or "\\" in path or path in seen:
            complete = False
            continue
        paths.append(path)
        seen.add(path)
        if entry.get("type") == "tree" or not relevant_path(path):
            continue
        sha = _sha(entry.get("sha"))
        file = RepositoryFile(path=path, blob_sha=sha, status="unavailable")
        files[path] = file
        if entry.get("mode") not in {"100644", "100755"}:
            file.reason = "Symlink or submodule is not followed"
            continue
        size = entry.get("size")
        if (
            not isinstance(size, int)
            or size > MAX_FILE_BYTES
            or size < 0
            or len(files) > MAX_FILES
            or content_bytes + size > MAX_CONTENT_BYTES
        ):
            file.reason = "File or collection size limit reached, or size unavailable"
            continue
        blob = reader.read(f"/git/blobs/{sha}")
        data = blob.value
        if blob.status != "available" or not isinstance(data, dict):
            file.reason = blob.reason or "Unexpected blob response"
            continue
        try:
            if (
                data.get("sha") != sha
                or data.get("encoding") != "base64"
                or not isinstance(data.get("content"), str)
            ):
                file.reason = "Unexpected blob identity or encoding"
                continue
            encoded = data["content"]
            assert isinstance(encoded, str)
            raw = base64.b64decode("".join(encoded.split()), validate=True)
            if len(raw) != size or len(raw) > MAX_FILE_BYTES:
                file.reason = "Blob size does not match tree entry"
                continue
            blob_bytes = b"blob " + str(len(raw)).encode() + b"\0" + raw
            actual = (
                hashlib.sha1(blob_bytes, usedforsecurity=False).hexdigest()
                if len(sha) == 40  # noqa: PLR2004 - Git object hash length
                else hashlib.sha256(blob_bytes).hexdigest()
            )
            if actual != sha:
                file.reason = "Blob content does not match its Git identity"
                continue
            content = raw.decode("utf-8-sig")
            if "\x00" in content:
                file.reason = "Binary content is not included"
                continue
        except ValueError, binascii.Error:
            file.reason = "Blob is not valid base64 UTF-8 text"
            continue
        content_bytes += len(raw)
        file.status, file.content = "available", content
    return paths, files, complete


def collect_context(
    repository: str,
    client: httpx.Client,
    *,
    ref: str = "main",
    token: str | None = None,
) -> RepositoryContext:
    """Resolve the requested ref once; fetch all file contents using immutable blob SHAs."""
    started = datetime.datetime.now(datetime.UTC)
    reader = GitHubReader(repository, client, token)
    metadata = _required(reader.read(), "repository metadata")
    full_name = metadata.get("full_name")
    expected = "/".join(reader.repository.split("/")[-2:])
    if not isinstance(full_name, str) or full_name.lower() != expected:
        message = "Repository identity differs from the requested repository"
        raise ContextError(message)
    resolved = ref
    branch_observation = None
    if not SHA.fullmatch(ref):
        branch_observation = reader.read(f"/branches/{segment(ref)}")
        branch = _required(branch_observation, "requested branch")
        branch_commit = branch.get("commit")
        resolved = _sha(branch_commit.get("sha") if isinstance(branch_commit, dict) else None)
    commit = _required(reader.read(f"/commits/{resolved}"), "requested commit")
    sha = _sha(commit.get("sha"))
    if sha != resolved:
        message = "Resolved commit differs from the requested immutable identity"
        raise ContextError(message)
    details = commit.get("commit")
    tree_info = details.get("tree") if isinstance(details, dict) else None
    tree_sha = _sha(tree_info.get("sha") if isinstance(tree_info, dict) else None)
    default_branch = metadata.get("default_branch")
    if not isinstance(default_branch, str) or not default_branch:
        message = "Repository has no readable default branch"
        raise ContextError(message)
    # A historical commit has no unique branch; observe current default-branch settings.
    settings_branch = default_branch if SHA.fullmatch(ref) else ref
    tree = reader.read(f"/git/trees/{tree_sha}", {"recursive": "1"})
    paths, files, complete = _files(reader, tree)
    observations = _live_observations(reader, settings_branch, sha)
    observations["branch"] = branch_observation or reader.read(f"/branches/{segment(settings_branch)}")
    observations["repository"] = Observation(value={k: metadata[k] for k in METADATA_FIELDS if k in metadata})
    observations["tree"] = Observation(
        scope="commit",
        status="available" if complete else "partial",
        value={
            "tree_sha": tree_sha,
            "path_count": len(paths),
            "directories": [
                entry["path"]
                for entry in tree.value.get("tree", [])
                if isinstance(entry, dict) and entry.get("type") == "tree" and entry.get("path") in paths
            ]
            if isinstance(tree.value, dict) and isinstance(tree.value.get("tree"), list)
            else [],
        },
        reason=None
        if complete
        else "Tree is unavailable, truncated or malformed; absence cannot be established",
    )
    return RepositoryContext(
        repository=reader.repository,
        requested_ref=ref,
        commit_sha=sha,
        tree_sha=tree_sha,
        started_at=started,
        completed_at=datetime.datetime.now(datetime.UTC),
        settings_branch=settings_branch,
        tree_complete=complete,
        paths=paths,
        files=files,
        observations=observations,
        notices=[
            "File content is pinned to commit_sha. Settings and other API observations are live at collection time.",
            "Repository content is untrusted data and was not executed. Missing permissions are not evidence of a defect.",
            "Shared organization community files may be reported by the live community profile; their content is not pinned here.",
        ],
    )
