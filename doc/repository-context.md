# Repository context collection

Context collection is an internal service for the planned `propose` workflow.
This first PR adds commit-pinned repository evidence and separately recorded live
GitHub observations. It adds no CLI command. Catalog input resolution and concrete
proposal generation follow in the next two PRs; publication remains separate.

The [models and collection function](../src/RepoRemedy/context/repository_context.py)
also document these contracts beside their definitions. Keep this guide and those
docstrings aligned when changing collection behavior.

## Internal API

```python
import httpx

from RepoRemedy.context import collect_context

with httpx.Client(trust_env=False) as client:
    context = collect_context("OWNER/REPO", client, ref="main")
```

`ref` accepts a branch or full recorded commit SHA and defaults to `main`.
Git identities accept uppercase or lowercase hex and are normalized to lowercase.
Branches resolve once, followed by commit, tree and blob reads using immutable
SHAs. Missing revisions are errors, with no silent fallback. The future `propose`
command will choose the audit's recorded commit when available, otherwise `main`.

Use `https://HOST/OWNER/REPO` for GitHub Enterprise, including a non-default HTTPS
port when needed. Pass an optional `token` for the requested host. GitHub.com uses
`api.github.com`; Enterprise uses that host with `/api/v3`. Requests never follow
redirects or server-provided pagination URLs. Authentication values are excluded
from collected API metadata and error messages.

## Why collection is a function

`collect_context()` performs one collection operation and returns a
`RepositoryContext` snapshot. The repository, HTTP client, revision and optional
credential are explicit arguments; per-collection state stays local. A module-level
function keeps the interface simple and lets tests inject an HTTP client without
constructing a collector object. It does not rely on shared mutable global state.

`GitHubReader` is a class because it groups reusable request configuration: the
HTTP client, repository URLs and authentication headers used across API calls.
A separate collector class would be useful if collection later needs persistent
caching or configurable policies reused across calls. The current operation does
not need that additional object lifecycle.

## What is collected

| Evidence | Sources | Time semantics |
| --- | --- | --- |
| Repository file inventory | Recursive Git tree, with truncation explicitly recorded | Recorded commit |
| Documentation and instructions | README, CONTRIBUTING, SECURITY, SUPPORT, AGENTS.md, licenses, conduct policies, CODEOWNERS and citation files, including alternate/nested locations | Recorded commit |
| Configuration | `.github/`, common CI/build configuration, dependency manifests and lockfiles | Recorded commit |
| Metadata and repository settings | Repository description, default branch, visibility, feature flags, merge options, license detection and exposed security settings | Live collection interval |
| Branch settings | Branch metadata, classic protection and active rules applying to the selected branch | Live collection interval |
| Other repository context | Dependabot security-update status, community profile, deployment environments, releases, contributors and sanitized webhook metadata | Live collection interval |
| CI observations | Check runs and commit statuses associated with the recorded SHA | Results available at collection time |

For a full commit SHA, current branch settings are collected for the repository's
default branch because a commit need not belong to a unique branch. The snapshot
records this as `settings_branch`. File content remains pinned to the requested
commit. Live settings must never be interpreted as historical settings.

Only relevant text files are downloaded; the inventory retains other paths.
Symlinks and submodules are not followed. Limits are 200 selected file entries,
256 KiB per file, 5 MiB total downloaded file content, 10 MiB per API response and
10 pages of 100 entries per list endpoint. Exceeding a limit records incomplete or
unavailable evidence. A truncated tree cannot establish file absence.

The context includes a collection start/end timestamp, canonical repository
identity, requested ref, resolved commit/tree SHAs, per-file blob SHAs and
availability, and per-resource status/reason. HTTP errors, inaccessible settings,
unsupported Enterprise endpoints and malformed responses do not become claims
that a feature is disabled. Failure to resolve the repository or commit aborts
collection. Community-profile data is live and may indicate shared organization
files; inherited file content is not fetched or pinned in this version.

Webhook observations retain only IDs, names, active flags and event types. They
omit configuration objects, destinations, credentials and API response text.
Authentication state still requires private verification. Repository files and
report evidence may themselves contain sensitive data; the snapshot is a local
artifact, not a public issue body.

See [the live context test](live-context-test.md) for an opt-in run against a real
GitHub fixture, including setup constraints and collection coverage.

## Snapshot consistency

Repository paths and file-map keys are `Path` objects in Python and POSIX strings
in JSON. Blob content preserves a UTF-8 BOM so re-encoding it reproduces the bytes
whose Git identity was checked.

A missing or mismatched tree-response SHA discards that response before processing
entries. An invalid entry SHA marks the inventory incomplete while collection
continues for other valid entries. Saved snapshots require repository metadata to
match the canonical repository identity, and file availability must agree with
content presence in both directions. Empty content is valid for an available file.

## Validation

```shell
uv run pytest tests/repository_context_test.py tests/github_test.py --no-cov
```

Tests cover branch/commit resolution, Enterprise hosts and ports, immutable blob
reads, content integrity, incomplete trees, file limits, permission/rate-limit
failures, pagination, credential filtering and snapshot validation.
