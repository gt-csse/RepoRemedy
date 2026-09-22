# Publishing selected remedies

`publish` consumes a reviewed proposal bundle and creates only the explicitly
selected remedies. Settings remedies create issues requesting the approved change;
file remedies create draft PRs with the exact proposed files. It does not change
repository settings, merge PRs, or overwrite existing files.

## Command

Review the titles, bodies, file contents and diffs in `proposals.json`, then run:

```shell
RepoRemedy publish proposals.json --repo OWNER/REPO \
  --select ra-require-approvals --select ra-issue-templates \
  --receipts publication-receipts.json --confirm
```

Prefix with `uv run` when running from a checkout. Each selected ID must identify
exactly one `ready` proposal. There is no implicit selection of all remedies.
Unknown, duplicate, ambiguous or blocked selections fail before remote writes.
`--confirm` authorizes this invocation's selections; `propose --approve-inputs`
only approves template inputs and does not authorize publication.

The required `--repo` must match the bundle, including its host. The default token
variable is `REPOREMEDY_TOKEN`. Enterprise hosts and non-default HTTPS ports remain
supported; select a token for that host:

```shell
RepoRemedy publish proposals.json --repo https://github.example:8443/OWNER/REPO \
  --select security-policy --receipts publication-receipts.json \
  --token-env ENTERPRISE_TOKEN --confirm
```

Use a token with access to read the selected evidence and create the chosen object.
Issue creation requires issue write access. PR creation requires contents and pull
request write access, and write access to a branch in the target repository. Fork
publication is not implemented. See GitHub's [issue creation permissions](https://docs.github.com/en/rest/issues/issues#create-an-issue),
[tree creation permissions](https://docs.github.com/en/rest/git/trees#create-a-tree)
and [pull request creation permissions](https://docs.github.com/en/rest/pulls/pulls#create-a-pull-request).

The receipt directory must already exist. Keep using the same receipt file for a
repository. On success the command also writes the journal as JSON to stdout. On
failure it exits with code 2; inspect the journal for any completed or pending work.
Tests simulate GitHub; running the command with `--confirm` makes real API writes.
Creating branches and PRs may trigger the target repository's configured automation.

## Validation and stale content

Before writing, the publisher verifies repository identities, the base commit,
report/context provenance and the installed catalog digest. It rebuilds selected
proposals against their saved context, retaining supplied inputs and their approvals.
Changing a saved status to `ready` or editing rendered content does not bypass
catalog validation. Regenerate and review proposals after catalog changes.

Before each new publication it checks the target branch, fetches fresh repository
context and rebuilds the selected remedy again. The branch must still point to the
reviewed commit, and the selected evidence, rendered content and readiness must
remain unchanged. Any branch advance is conservatively stale, even if unrelated
files changed. Changed settings, existing or inherited files, unreadable evidence
and failed creation guards prevent publication. GitHub enforces token permissions;
the publisher also checks repository availability and PR push access.

A draft PR uses a deterministic `reporemedy/…` branch for its repository/remedy key.
One Git tree overlays the proposed new files on the reviewed tree; one commit uses
the reviewed commit as its parent. This preserves unrelated files and puts all files
from one remedy into a single commit. Only a new ref is created: existing refs are
never force-updated. An interrupted attempt may reuse its recorded commit and ref;
an unrelated or changed branch requires manual reconciliation. The base and proposal
branch are checked again before the PR is created with `draft=true`.

## Duplicates and retries

Each published body receives a hidden marker derived from the canonical repository
and stable remedy ID. This identity does not change with a report, route or content
revision. The publisher lists issues and PRs in all states, including closed items,
and skips a matching marker or an identical title. It records the existing object's
URL instead of creating another issue or PR. This also prevents an issue from being
followed automatically by a PR for the same remedy.

Incomplete pagination, inaccessible listings, malformed results and multiple matches
block creation. The scan is repeated immediately before the final creation request.
Existing matches are reused even if the original proposal is now stale; reuse makes
no changes to the remote object. Renamed, unmarked manual issues require human
reconciliation; semantic duplicate detection and automatic reopening are not provided.

GitHub does not provide a transaction spanning the duplicate scan, branch checks and
issue/PR creation. The local journal lock prevents simultaneous publishers using the
same receipt path. It is not a distributed lock: serialize publication across machines
or different journal paths. Another user can still change repository state between a
check and a write. These checks reduce that window but cannot eliminate it.

## Publication receipts

[`PublicationReceipt` and `ReceiptStore`](../src/RepoRemedy/publication/receipts.py)
record the remedy ID, route, reviewed commit, requested content digest, timestamp,
status, remote number/URL and any prepared branch/commit. The journal is bound to a
repository. It stores neither authentication tokens nor the full report, context,
issue body or file contents. A digest records the requested content, not proof that
an existing duplicate still has identical content.

| Status | Meaning |
| --- | --- |
| `pending` | Preparation began; a draft PR may already have a recorded commit or branch. |
| `uncertain` | Issue/PR creation was about to be attempted; no successful result has been durably recorded. |
| `created` | A newly created issue or draft PR and its URL were recorded. |
| `existing` | A matching remote issue or PR was found and reused. |

The store acquires an exclusive `.lock` file, flushes and fsyncs a private temporary
file, then atomically replaces the JSON journal. It saves intent before dependent
remote writes and saves each completed result separately. If a later selected remedy
fails, earlier receipts remain available; a batch is not an all-or-nothing transaction.
The journal keeps the latest state per remedy, not an append-only event history.

A retry first checks GitHub for the stable marker/title. If found, it reconciles the
receipt without another creation. If an uncertain request has no visible match, it
stops: absence from a later listing is insufficient to justify blindly repeating a
POST whose response was lost. Inspect GitHub and preserve the journal before manually
resolving that receipt. The same conservative rule applies when a recorded created
object can no longer be found. Pending PR preparation may resume only for unchanged
content and base commit. Failed preparation can leave an unused branch or unreachable
Git objects; no automatic branch deletion is attempted.

After a process crash, remove a leftover `.lock` file only after establishing that no
publisher is still running. Never erase uncertain receipts merely to retry: reconcile
whether an object was created first.

## Implementation and tests

[`publish_remedies()`](../src/RepoRemedy/publication/publish.py) is one operation with
explicit bundle, selection, target, client, token and receipt-path dependencies.
[`GitHubPublisher`](../src/RepoRemedy/publication/github.py) groups host-bound request
configuration, while `ReceiptStore` owns journal state and its lock. `PublishedTarget`
is a named dataclass; receipts use typed timestamps and shared `GitSha` validation.
Filesystem and repository destinations use `Path` types, with POSIX serialization
at GitHub/JSON boundaries. These contracts are also documented beside the code.

```shell
uv run pytest tests/publication tests/cli_test.py --no-cov
```

Tests cover selected-only settings issues, draft PR payloads, unchanged unrelated
files, bundle validation, stale branches/settings/files, duplicate pagination,
Enterprise routing, partial failures, uncertain responses, branch collisions,
receipt persistence/locking and CLI confirmation/errors. They use simulated HTTP
responses and make no live GitHub writes.
