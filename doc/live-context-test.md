# Live repository-context test

PR #6 includes an opt-in integration test for the internal context collector.
It uses [ketanbj/reporemedy-live-fixture](https://github.com/ketanbj/reporemedy-live-fixture),
a disposable public repository containing only synthetic data. Its
[coverage matrix](https://github.com/ketanbj/reporemedy-live-fixture/blob/main/FIXTURE-COVERAGE.md)
accounts for all 68 catalog remedies and explains which conditions are seeded,
policy-dependent, historical or unavailable on this host.

The [live-test module](../tests/live/repository_context_test.py) includes these
instructions in its docstring as well. Keep both locations aligned when changing
the fixture or test invocation.

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

The [test contract](../tests/fixtures/repository_context_live.json) records the
repository and exact `main`/historical commit SHAs plus expected content. Changes
to `main` or its live settings deliberately fail assertions so drift is visible.
Keep it stable during runs; use separate branches for later publication tests.
If intentionally reseeding, update the contract and expected observations together,
then run the live suite before committing them. Do not replace expected facts with
assertions that accept every availability state.
