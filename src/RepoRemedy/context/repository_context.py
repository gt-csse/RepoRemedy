# noqa: CPY001
"""Repository context models and the operation that creates their snapshots.

This internal service supports later remedy generation; it exposes no CLI command.
Collection downloads evidence without checking out or executing repository code.
"""

import base64
import binascii
from dataclasses import dataclass, field
import datetime
import hashlib
from pathlib import Path, PureWindowsPath
import re
from typing import Annotated, TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, StringConstraints, model_validator

from RepoRemedy.context.github import ContextError, GitHubReader, Observation, encode_segment
from RepoRemedy.readers.common import repository_name

if TYPE_CHECKING:
    import httpx
    from pydantic import JsonValue

# One definition for API identities, requested commit refs and saved model fields.
SHA_PATTERN = re.compile(r"\A[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?\Z")
GitSha = Annotated[str, StringConstraints(pattern=SHA_PATTERN, to_lower=True)]
RepositoryPath = Annotated[
    Path, PlainSerializer(lambda path: path.as_posix(), return_type=str, when_used="json")
]

MAX_FILES = 200
MAX_FILE_BYTES = 256 * 1024
MAX_CONTENT_BYTES = 5 * 1024 * 1024
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


class RepositoryFile(BaseModel):
    """Repository-relative Path and content read by immutable blob identity.

    Available content is size-checked UTF-8 text whose bytes match blob_sha.
    Symlinks, submodules, binary data and oversized/unreadable files retain their
    paths and an unavailable reason; they are never followed or executed.
    Paths serialize as POSIX strings in JSON on every host platform.
    """

    model_config = ConfigDict(extra="forbid")
    path: RepositoryPath
    blob_sha: GitSha
    status: Literal["available", "unavailable"]
    content: str | None = None
    reason: str | None = None


class RepositoryContext(BaseModel):
    """Commit-pinned files and separately identified live GitHub observations.

    commit_sha/tree_sha identify the exact source revision. paths contains the
    tree inventory as repository-relative Path objects; files maps those Paths
    to relevant collected content, with per-file blob identities and availability.
    JSON represents paths and dictionary keys as POSIX strings. A partial tree
    (tree_complete=False) cannot establish file absence.

    started_at/completed_at bound the collection interval. Settings, community
    profiles, releases and contributors are live observations, never historical
    facts at commit_sha. CI results refer to the commit but are read at collection
    time. For a full SHA, settings_branch is the current default branch because
    a historical commit does not identify a unique branch. Inherited community
    files may appear in the live profile; their contents are not pinned here.

    This snapshot is a local evidence artifact. Files and report text may contain
    private data and must not be published wholesale as an issue body.
    """

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    repository: str
    requested_ref: str
    commit_sha: GitSha
    tree_sha: GitSha
    started_at: datetime.datetime
    completed_at: datetime.datetime
    settings_branch: str
    tree_complete: bool
    paths: list[RepositoryPath]
    files: dict[RepositoryPath, RepositoryFile]
    observations: dict[str, Observation]
    notices: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_snapshot(self) -> RepositoryContext:
        """Require matching repository identities, timestamps, paths and content availability."""
        metadata = self.observations.get("repository")
        if (
            repository_name(self.repository) != self.repository
            or metadata is None
            or metadata.status != "available"
            or not isinstance(metadata.value, dict)
        ):
            message = "Context must contain a canonical repository identity and available repository metadata"
            raise ValueError(message)
        full_name = metadata.value.get("full_name")
        if not isinstance(full_name, str) or full_name.lower() != "/".join(self.repository.split("/")[-2:]):
            message = "Repository metadata identity must match the canonical repository"
            raise ValueError(message)
        if (
            self.started_at.tzinfo is None
            or self.completed_at.tzinfo is None
            or self.completed_at < self.started_at
        ):
            message = "Context collection timestamps must be ordered and timezone-aware"
            raise ValueError(message)
        if any(
            key != file.path or ((file.status == "available") != (file.content is not None))
            for key, file in self.files.items()
        ):
            message = "Context file paths and availability must agree with their content"
            raise ValueError(message)
        return self


@dataclass
class FileCollection:
    """Tree inventory and collected files, with an explicit completeness flag.

    directories distinguishes real parent directories from files, links and
    submodules. complete describes inventory completeness, not blob availability;
    each RepositoryFile separately records whether its content was readable.
    reason records identity failures that prevent trusting all or part of the tree.
    """

    paths: list[Path] = field(default_factory=list)
    files: dict[Path, RepositoryFile] = field(default_factory=dict)
    directories: list[Path] = field(default_factory=list)
    complete: bool = False
    reason: str | None = None


def is_manifest_path(path: Path) -> bool:
    """Recognize dependency/build configuration for collection and remedy inputs."""
    name = path.name.lower()
    return (
        name in MANIFEST_NAMES
        or (name.startswith("requirements") and name.endswith(".txt"))
        or name.endswith((".csproj", ".fsproj"))
    )


def is_relevant_path(path: Path) -> bool:
    """Select guidance, community files, workflows and dependency/build configuration."""
    lower = path.as_posix().lower()
    name = path.name.lower()
    return (
        name.split(".")[0] in DOC_NAMES
        or name in {"agents.md", "codeowners", "citation.cff"}
        or is_manifest_path(path)
        or lower.startswith((".github/", ".circleci/"))
        or name in {".gitlab-ci.yml", ".travis.yml", "jenkinsfile", "azure-pipelines.yml"}
    )


def _get_required_object(result: Observation, name: str) -> dict[str, JsonValue]:
    """Require an available JSON object for a core identity lookup."""
    if result.status != "available" or not isinstance(result.value, dict):
        message = f"Cannot retrieve {name}: {result.reason or 'unexpected response'}"
        raise ContextError(message)
    return result.value


def _get_validated_sha(value: JsonValue) -> str:
    """Validate an API Git identity using the model constraint and normalize its case."""
    if not isinstance(value, str) or not SHA_PATTERN.fullmatch(value):
        message = "GitHub returned an invalid commit, tree or blob identity"
        raise ContextError(message)
    return value.lower()


def _select_fields(result: Observation, fields: tuple[str, ...]) -> Observation:
    """Keep selected API fields, marking malformed list entries as partial data."""
    if isinstance(result.value, list):
        records = [item for item in result.value if isinstance(item, dict)]
        if len(records) != len(result.value):
            result.status = "partial"
            result.reason = "Response contained malformed records"
        result.value = [{key: item[key] for key in fields if key in item} for item in records]
    return result


def _collect_live_observations(reader: GitHubReader, branch: str, commit: str) -> dict[str, Observation]:
    """Read settings and API evidence available during the collection interval.

    Includes classic/effective branch rules, Dependabot updates, community profile,
    environments, releases, contributors, and CI results associated with commit.
    Webhooks retain only IDs, names, active flags and event types; callback URLs,
    configurations and credentials are omitted. Authentication needs private review.
    """
    branch_path = encode_segment(branch)
    observations = {
        "branch_protection": reader.read(f"/branches/{branch_path}/protection"),
        "branch_rules": reader.read_pages(f"/rules/branches/{branch_path}"),
        "dependabot_security_updates": reader.read("/automated-security-fixes"),
        "community_profile": reader.read("/community/profile"),
        "environments": _select_fields(
            reader.read_pages("/environments", "environments"), ("name", "protection_rules")
        ),
        "webhooks": _select_fields(reader.read_pages("/hooks"), ("id", "name", "active", "events")),
        "releases": _select_fields(
            reader.read_pages("/releases"), ("tag_name", "published_at", "draft", "prerelease")
        ),
        "contributors": _select_fields(
            reader.read_pages("/contributors"), ("login", "contributions", "type")
        ),
        "check_runs": _select_fields(
            reader.read_pages(f"/commits/{commit}/check-runs", "check_runs"),
            ("name", "status", "conclusion", "head_sha"),
        ),
        "commit_statuses": _select_fields(
            reader.read_pages(f"/commits/{commit}/statuses"), ("context", "state", "sha")
        ),
    }
    observations["webhooks"].reason = (
        "Only non-secret webhook metadata is retained; authentication must be verified privately. "
        + (observations["webhooks"].reason or "")
    ).strip()
    return observations


def _populate_file_content(reader: GitHubReader, file: RepositoryFile, size: int) -> int:
    """Validate blob identity/bytes, populate content and return its accepted byte count.

    Plain UTF-8 decoding preserves a leading BOM as U+FEFF so encoding the saved
    content reproduces the bytes whose Git identity was checked. Unreadable blobs
    remain unavailable, with a reason and no content.
    """
    sha = file.blob_sha
    blob = reader.read(f"/git/blobs/{sha}")
    data = blob.value
    if blob.status != "available" or not isinstance(data, dict):
        file.reason = blob.reason or "Unexpected blob response"
        return 0
    try:
        if (
            not isinstance(data.get("sha"), str)
            or data["sha"].lower() != sha
            or data.get("encoding") != "base64"
            or not isinstance(data.get("content"), str)
        ):
            file.reason = "Unexpected blob identity or encoding"
            return 0
        encoded = data["content"]
        assert isinstance(encoded, str)
        raw = base64.b64decode("".join(encoded.split()), validate=True)
        if len(raw) != size or len(raw) > MAX_FILE_BYTES:
            file.reason = "Blob size does not match tree entry"
            return 0
        blob_bytes = b"blob " + str(len(raw)).encode() + b"\0" + raw
        actual = (
            hashlib.sha1(blob_bytes, usedforsecurity=False).hexdigest()
            if len(sha) == 40  # noqa: PLR2004 - Git object hash length
            else hashlib.sha256(blob_bytes).hexdigest()
        )
        if actual != sha:
            file.reason = "Blob content does not match its Git identity"
            return 0
        content = raw.decode("utf-8")
        if "\x00" in content:
            file.reason = "Binary content is not included"
            return 0
    except ValueError, binascii.Error:
        file.reason = "Blob is not valid base64 UTF-8 text"
        return 0
    file.status, file.content = "available", content
    return len(raw)


def _collect_files(reader: GitHubReader, tree: Observation, tree_sha: str) -> FileCollection:
    """Collect a bounded tree inventory and relevant blobs, preserving failure reasons.

    MAX_FILES limits selected entries, MAX_FILE_BYTES each blob and
    MAX_CONTENT_BYTES the total fetched text (200 entries, 256 KiB/file, 5 MiB).
    Only guidance, community files, CI/build configuration and dependency manifests
    are fetched. Other valid paths remain in the inventory. Invalid/duplicate paths
    or truncated/malformed trees prevent absence claims. A mismatched root SHA
    discards the entire response before processing entries; an invalid entry SHA
    makes the inventory incomplete while other valid entries remain collectable.
    """
    result = FileCollection()
    value = tree.value
    if tree.status != "available" or not isinstance(value, dict) or not isinstance(value.get("tree"), list):
        return result
    response_sha = value.get("sha")
    if not isinstance(response_sha, str) or response_sha.lower() != tree_sha:
        result.reason = "Tree response identity is missing or does not match the requested tree"
        return result
    entries = value["tree"]
    assert isinstance(entries, list)
    result.complete = value.get("truncated") is False
    seen: set[Path] = set()
    content_bytes = 0
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            result.complete = False
            continue
        raw_path = entry["path"]
        assert isinstance(raw_path, str)
        if (
            not raw_path
            or raw_path.startswith("/")
            or ".." in raw_path.split("/")
            or "\\" in raw_path
            or PureWindowsPath(raw_path).drive
            or Path(raw_path) in seen
        ):
            result.complete = False
            continue
        path = Path(raw_path)
        result.paths.append(path)
        seen.add(path)
        if entry.get("type") == "tree":
            result.directories.append(path)
            continue
        if not is_relevant_path(path):
            continue
        try:
            sha = _get_validated_sha(entry.get("sha"))
        except ContextError:
            result.complete = False
            result.reason = (
                "Tree entry has an invalid or missing object identity; absence cannot be established"
            )
            continue
        file = RepositoryFile(path=path, blob_sha=sha, status="unavailable")
        result.files[path] = file
        if entry.get("mode") not in {"100644", "100755"}:
            file.reason = "Symlink or submodule is not followed"
            continue
        size = entry.get("size")
        if (
            not isinstance(size, int)
            or size > MAX_FILE_BYTES
            or size < 0
            or len(result.files) > MAX_FILES
            or content_bytes + size > MAX_CONTENT_BYTES
        ):
            file.reason = "File or collection size limit reached, or size unavailable"
            continue
        content_bytes += _populate_file_content(reader, file, size)
    return result


def collect_context(
    repository: str,
    client: httpx.Client,
    *,
    ref: str = "main",
    token: str | None = None,
) -> RepositoryContext:
    """Resolve the requested ref once; fetch all file contents using immutable blob SHAs.

    repository accepts OWNER/REPO or an Enterprise HTTPS identity. ref defaults
    to main and accepts another branch or a full SHA (hex case is normalized).
    Missing repositories/refs raise ContextError; collection never falls back to
    another revision. The caller owns client and supplies an optional host-specific
    token. API settings are live; relevant file content is pinned to the resolved
    commit. Unavailable optional resources remain explicit observations.

    Example::

        with httpx.Client(trust_env=False) as client:
            context = collect_context("OWNER/REPO", client, ref="main")

    A module-level function fits this single collection operation: dependencies
    are explicit arguments and per-collection state stays local. GitHubReader
    holds the reusable request configuration. A collector class would become
    useful for persistent caching or reusable collection policies.
    """
    started = datetime.datetime.now(datetime.UTC)
    reader = GitHubReader(repository, client, token)
    metadata = _get_required_object(reader.read(), "repository metadata")
    full_name = metadata.get("full_name")
    expected = "/".join(reader.repository.split("/")[-2:])
    if not isinstance(full_name, str) or full_name.lower() != expected:
        message = "Repository identity differs from the requested repository"
        raise ContextError(message)
    resolved = ref.lower() if SHA_PATTERN.fullmatch(ref) else ref
    branch_observation = None
    if not SHA_PATTERN.fullmatch(ref):
        branch_observation = reader.read(f"/branches/{encode_segment(ref)}")
        branch = _get_required_object(branch_observation, "requested branch")
        branch_commit = branch.get("commit")
        resolved = _get_validated_sha(branch_commit.get("sha") if isinstance(branch_commit, dict) else None)
    commit = _get_required_object(reader.read(f"/commits/{resolved}"), "requested commit")
    sha = _get_validated_sha(commit.get("sha"))
    if sha != resolved:
        message = "Resolved commit differs from the requested immutable identity"
        raise ContextError(message)
    details = commit.get("commit")
    tree_info = details.get("tree") if isinstance(details, dict) else None
    tree_sha = _get_validated_sha(tree_info.get("sha") if isinstance(tree_info, dict) else None)
    default_branch = metadata.get("default_branch")
    if not isinstance(default_branch, str) or not default_branch:
        message = "Repository has no readable default branch"
        raise ContextError(message)
    # A historical commit has no unique branch; observe current default-branch settings.
    settings_branch = default_branch if SHA_PATTERN.fullmatch(ref) else ref
    tree = reader.read(f"/git/trees/{tree_sha}", {"recursive": "1"})
    collection = _collect_files(reader, tree, tree_sha)
    observations = _collect_live_observations(reader, settings_branch, sha)
    observations["branch"] = branch_observation or reader.read(f"/branches/{encode_segment(settings_branch)}")
    observations["repository"] = Observation(value={k: metadata[k] for k in METADATA_FIELDS if k in metadata})
    observations["tree"] = Observation(
        scope="commit",
        status="available" if collection.complete else "partial",
        value={
            "tree_sha": tree_sha,
            "path_count": len(collection.paths),
            "directories": [path.as_posix() for path in collection.directories],
        },
        reason=None
        if collection.complete
        else collection.reason
        or "Tree is unavailable, truncated or malformed; absence cannot be established",
    )
    return RepositoryContext(
        repository=reader.repository,
        requested_ref=ref,
        commit_sha=sha,
        tree_sha=tree_sha,
        started_at=started,
        completed_at=datetime.datetime.now(datetime.UTC),
        settings_branch=settings_branch,
        tree_complete=collection.complete,
        paths=collection.paths,
        files=collection.files,
        observations=observations,
        notices=[
            "File content is pinned to commit_sha. Settings and other API observations are live at collection time.",
            "Repository content is untrusted data and was not executed. Missing permissions are not evidence of a defect.",
            "Shared organization community files may be reported by the live community profile; their content is not pinned here.",
        ],
    )
