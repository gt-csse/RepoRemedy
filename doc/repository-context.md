# Proposing remedies with repository context

`propose` reads an audit, gathers repository context, resolves catalog inputs and
renders a concrete issue or eligible draft PR in one invocation. Context collection
and input resolution are internal services, not separate CLI commands. `inspect`
remains available for offline report inspection; publication will be a separate
`publish` command.

The [models and collection function](../src/RepoRemedy/context/repository_context.py)
also document these contracts beside their definitions. Keep this guide and those
docstrings aligned when changing collection behavior.

## Command

Run from an installed package or prefix with `uv run` in a checkout:

```shell
RepoRemedy propose report.json --report-type ossf-scorecard \
  --repo OWNER/REPO > proposals.json
RepoRemedy propose report.txt --report-type repoauditor \
  --repo https://github.gatech.edu/OWNER/REPO --ref main \
  --token-env ENTERPRISE_TOKEN > proposals.json
```

Without `--ref`, context uses the audit's recorded commit, or `main` when no commit
was recorded. Use `--ref main`, another branch, or a full commit SHA to choose
explicitly. A differing audited/context commit marks otherwise ready proposals
`needs-review`. Missing revisions are errors; there is no silent fallback.
Branches resolve once, then commit, tree and blob reads use immutable SHAs. Blob
content is checked against its Git identity. No repository code is executed.
Git identities accept uppercase or lowercase hex and are normalized to lowercase.

GitHub.com shorthand and Enterprise host/port identities are supported. GitHub.com
uses `api.github.com`; Enterprise uses the chosen host with `/api/v3`. The default
token environment variable is `REPOREMEDY_TOKEN`, optional for public reads;
`--token-env` selects a variable containing a token for the requested host.
Requests do not follow redirects or server-provided pagination URLs. Credentials
are excluded from collected API metadata and error messages.

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

## How the 25 input fields are resolved

Each selected route uses only its own required fields. Every resolved field
contains a value and its source; unresolved fields contain a reason.

| Fields | Resolution |
| --- | --- |
| `repository`, `origin`, `check`, `evidence` | Normalized report; repository identity must match the snapshot. |
| `target` | Catalog destination paths or repository/branch target. |
| `observed_state` | Matching file paths or relevant API observations, including availability; no applicability conclusion is inferred. |
| `setting_location` | Host-aware repository settings URL; detailed setting navigation remains part of later remedy logic. |
| `verification_steps` | Catalog-based review/rerun guidance; this is a plan, not evidence that checks ran. |
| `affected_components` | Candidate workflow/manifest paths from the recorded tree; not a declaration that those files are defective. |
| `project_name`, `project_summary` | Live repository metadata with that provenance explicitly recorded. |
| `installation_instructions`, `usage_instructions`, `support_instructions` | Unambiguous matching Markdown sections from existing documentation. |
| `development_setup`, `test_instructions`, `contribution_process` | Unambiguous matching Markdown sections from existing documentation. |
| `security_reporting_instructions`, `supported_versions` | Unambiguous matching Markdown sections from existing documentation. |
| `reported_expected_value` | Explicit supplied audit expectation; not guessed from narrative evidence or current settings. |
| `approved_value`, `approved_license_text`, `approved_codeowners`, `approved_code_of_conduct`, `approved_citation_metadata` | Supplied by the user; fetching current content does not establish maintainer approval. |

Section extraction uses Markdown headings, not semantic inference. Missing,
unreadable or conflicting sections remain unresolved. Raw relevant files are
retained so later logic can support additional formats and project conventions.

Optional user inputs are a JSON object keyed by stable remedy ID:

```json
{
  "security-policy": {
    "security_reporting_instructions": "Use the project's private reporting form.",
    "supported_versions": "The 1.x release series."
  },
  "ra-require-approvals": {
    "reported_expected_value": "2",
    "approved_value": "2"
  }
}
```

```shell
RepoRemedy propose report.txt --report-type repoauditor --repo OWNER/REPO \
  --inputs maintainer-inputs.json --approve-inputs security-policy > proposals.json
```

Unknown keys, empty/non-string values and overrides of report/context-owned fields
are rejected. User values remain literal, including placeholder-like text. Their
provenance identifies user input but does not establish approval. Input files must
not contain secrets or authenticated webhook URLs.

## Route selection and readiness

The default `--route auto` selects a PR only when all declared inputs are complete,
all file-creation guards pass, and `--approve-inputs REMEDY_ID` explicitly approves
its content inputs. Repeat that option for multiple remedies. This approves inputs,
not publication, and does not bypass missing evidence or file validation. Setting
issues containing an `approved_value` also require explicit input approval.

For a PR, the tree must be complete, targets absent, and supported alternate files
absent. A live community profile must also be readable and show no matching shared
file for applicable community assets. Existing files, symlinks, submodules or
ambiguous parent directories cannot be overwritten. Citation and CODEOWNERS PRs
require future dedicated format/access validators and currently use the issue route.

When a PR is ineligible, `auto` renders the catalog issue and records why it did not
choose the PR. `--route issue` requests issues only; `--route pr` keeps missing inputs
and failed guards visible on the requested PR instead of falling back. It cannot
force an unsupported or unsafe PR.

Each proposal has one selected route and one status:

| Status | Meaning |
| --- | --- |
| `ready` | Complete issue or draft PR content for the separate publication step. |
| `needs-input` | Required values are missing; no partial template is rendered. |
| `needs-review` | Evidence, input approval or validation does not establish readiness; any rendered content remains blocked. |
| `unavailable` | The audit did not establish a finding; no content is generated. |
| `unsupported` | No catalog mapping exists; the finding remains visible without content. |

`ready` means ready issue/draft PR content, not that repository checks passed or
that publication is authorized. Settings and engineering issues request specific
follow-up work; this non-LLM implementation does not repair code or rerun auditors.
File presence can indicate an existing or incomplete remedy, so such findings
require review instead of assuming success or creating a duplicate file.

## Saved proposal bundle

The JSON output includes repository identity, `base_commit`, the source report,
collected context, SHA-256 digests for report/context/catalog assets, explicit input
approvals and a `proposals` list. Each proposal retains its finding, selected route,
sourced inputs, missing values, guard results and readiness reasons. Its `content`
contains the rendered title/body and, for PRs, exact new file contents, create
operations and unified diffs. PR content is marked `draft`.

Substitution is single-pass: placeholder-like text inside supplied values remains
literal. Packaged assets are unchanged. No GitHub writes occur.

Keep the bundle local for review. A future publisher must use only selected `ready`
proposal content, not the entire context or report. It must recheck target state,
permissions and duplicates and obtain publication confirmation. Existing-file edits,
check-specific re-auditing and combining overlapping findings remain future work.

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

## Internal service contracts

`load_catalog()` returns a `LoadedCatalog` dataclass with `remedies` and `sha256`.
`resolve_inputs()` returns a `ResolvedInputs` dataclass with `values` and
`missing_inputs`. Named fields make the intermediate results explicit;
`InputResolution` remains the Pydantic model for saved JSON.

Catalog destinations use the same `RepositoryPath` type as collected paths:
Python callers receive `Path` objects, and JSON and template text use POSIX strings.
Packaged body/template names remain string resource identifiers, read through
`read_asset()`; they are not local filesystem paths. Invalid destination syntax
is checked before path conversion can normalize separators.

Resolution's `commit_sha` reuses the collector's `GitSha` validation. Commit
comparisons ignore hex case, so uppercase report SHAs do not create false mismatch
notices. Git identities and SHA-256 artifact digests serve different purposes.

Input extraction uses `find_matching_files()`, `_extract_section()` and
`_describe_observed_state()`. Heading extraction ignores a leading BOM for matching
while retaining the original snapshot content. Evidence supplies facts, never
maintainer approval; missing and conflicting values remain explicit.

Tests follow the modules: `catalog_test.py` checks catalog declarations and assets,
`inputs_test.py` checks evidence extraction, and `resolve_test.py` checks route
resolution and saved provenance. Shared fixtures live in `remedy_fixtures.py`.
These contracts are also documented beside the types and functions in the code.

Proposal selection returns a `RouteSelection` dataclass with `inputs`, `guards`
and `reasons`. `_evaluate_file_guards()`, `_select_route()`, `_render_content()`
and `_build_proposal()` name the steps explicitly. `FileChange.path` uses
`RepositoryPath` and `ProposalBundle.base_commit` uses `GitSha`; saved paths and
diff headers remain POSIX strings. `propose_test.py` exercises the service and
`cli_test.py` exercises command invocation and its input/output boundaries.

The shared [`propose_repository()` workflow](../src/RepoRemedy/workflow.py) reads the
report and optional input file, collects context, and invokes proposal generation.
Both `propose` and [`propose-batch`](batch.md) use it; callers control artifact storage
and whether an input failure stops processing. `workflow_test.py` checks input-file
bounds, and `batch_test.py` checks single/batch parity, isolation and partial results.

## Validation and API references

Tests cover branch/commit resolution, Enterprise hosts and ports, immutable blob
reads, content integrity, incomplete trees, file limits, permission/rate-limit
failures, pagination, credential filtering, catalog contracts, all catalog input
sets, missing/conflicting inputs, rendering, route selection, creation guards and CLI errors.

```shell
uv run pytest tests/repository_context_test.py tests/github_test.py tests/catalog_test.py tests/inputs_test.py tests/resolve_test.py tests/propose_test.py tests/workflow_test.py tests/batch_test.py tests/cli_test.py --no-cov
```

The collector follows GitHub's [Git tree](https://docs.github.com/en/rest/git/trees)
and [blob](https://docs.github.com/en/rest/git/blobs) APIs for immutable file evidence,
and the [branch protection](https://docs.github.com/en/rest/branches/branch-protection)
and [active branch rules](https://docs.github.com/en/rest/repos/rules#get-rules-for-a-branch)
APIs for current protection observations. Repository metadata and security feature
availability follow the [repository API](https://docs.github.com/en/rest/repos/repos).
