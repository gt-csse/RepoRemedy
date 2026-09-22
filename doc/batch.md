# Single-repository and batch proposals

`propose` and `propose-batch` call the same
[`propose_repository()` operation](../src/RepoRemedy/workflow.py):
read a report, validate supplied inputs, collect repository context, and render
catalog remedies. Both support RepoAuditor text and OpenSSF Scorecard JSON.
Route selection, input approvals, provenance, unsupported checks, and file guards
have identical semantics. Batch processing prepares proposals; publication is planned
as a separate, explicitly confirmed `publish` command.

```shell
RepoRemedy propose report.json --report-type ossf-scorecard --repo OWNER/REPO > proposals.json
RepoRemedy propose-batch demo/batch.json --output batch-results
```

Prefix commands with `uv run` when using a checkout. The checked-in
[`demo/batch.json`](../demo/batch.json) processes both report types for the ten
repositories in `demo/reports`. Keep any five entries for a smaller demonstration.
It explicitly uses each Scorecard report's recorded commit for both report types.
This does not establish an audited commit for RepoAuditor reports that lack one;
GitHub settings remain live observations even when file contents are pinned.
GitHub evidence is fetched read-only; permissions and rate limits can affect results.

## Manifest

```json
{
  "schema_version": 1,
  "reports": [
    {"report_type": "repoauditor", "path": "reports/{owner}/{repo}/repoauditor.txt"},
    {"report_type": "ossf-scorecard", "path": "reports/{owner}/{repo}/scorecard.json"}
  ],
  "repositories": [
    {"repository": "acme/project"},
    {
      "repository": "https://github.example:8443/acme/another-project",
      "ref": "release",
      "inputs": "inputs/{owner}/{repo}/{report_type}.json",
      "route": "pr",
      "approve_inputs": ["security-policy"],
      "token_env": "ENTERPRISE_TOKEN"
    }
  ]
}
```

Each repository is processed with each declared report type, in manifest order.
One or more repositories are supported; five to ten is the demo workload, not a
minimum. Each report type may appear once. Unknown configuration fields and unsafe
template expressions are rejected rather than silently ignored.

Report and optional input-file paths are relative to the manifest directory;
absolute paths are also accepted. Templates accept only `{owner}`, `{repo}`, and
`{report_type}` (plus doubled braces for a literal brace), without formatting or
attribute expressions. Owner/repository spelling is preserved for local paths,
while GitHub identity in the results is canonicalized. `.git` is removed from the
repository path component. Use literal paths when hosting the reports elsewhere.

Per-repository options match `propose`: `ref` defaults to the report's audited commit
or `main`; `inputs` is an optional JSON object keyed by remedy ID; `route` defaults
to `auto`; `approve_inputs` defaults to none. An explicit ref overrides the default
for both reports. Each repository's token comes only from its `token_env`, defaulting
to `REPOREMEDY_TOKEN`; credentials and approvals never carry over from another entry.
Batch manifests are limited to 1 MiB, as are individual input-override files.

## Artifacts and outcomes

`--output` must name a new directory, relative to the current working directory
unless absolute. Existing directories, including previous runs, are refused before
any repository is processed. Use a new path to retry a run.

```text
batch-results/
  summary.json
  0001/
    summary.json
    repoauditor.proposals.json
    ossf-scorecard.proposals.json
  0002/
    summary.json
    ...
```

The numbered directory maps to the repository's one-based manifest position.
Duplicate repositories are independent entries; Enterprise names cannot collide
with public repository artifact paths. Each successful bundle contains the normalized
report, report hash, context snapshot and commit, catalog hash, approvals, and proposals.
Original report files are not copied. Bundles use the existing proposal format for
review and future publication. All directory and artifact paths in summaries are relative
to the output root, including paths in per-repository summaries.

Each repository summary records the outcome for each report, the bundle location,
source hash, base commit, proposal status counts, and a sanitized error on failure.
The batch summary contains these repository records, planned counts, and successful
and failed report counts; it is also printed as JSON to stdout when processing
completes. Summaries distinguish processing success from remedy readiness:
`needs-input`, `needs-review`, `unavailable`, and
`unsupported` proposals remain visible and do not themselves fail the batch.

| Exit code | Meaning |
| --- | --- |
| `0` | All reports processed and artifacts/summaries saved. |
| `3` | Some reports succeeded, but at least one report or repository-summary write failed. |
| `2` | No reports succeeded, or a configuration, output-root, root-summary, or stdout error occurred. |

Missing/malformed reports, invalid repository identities, inaccessible context,
invalid input overrides, and per-repository artifact failures do not stop later
reports or repositories. Configuration errors (such as an unknown report type) fail
before the run starts. A root summary write failure stops the run with exit `2`;
already-written repository artifacts remain available.

If printing the final summary fails, the command exits `2` even though the saved
summary is already `completed` with the run's original exit code. Inspect saved
results before retrying; a stdout failure does not invalidate saved bundles.

JSON artifacts are replaced atomically. The batch summary is updated after every
repository and marked `completed` only at the end. An interrupted run can leave a
`running` summary whose counts cover only the repositories in that checkpoint.
Additional bundles or repository summaries may already exist on disk; inspect those
files as well. Runs are not automatically resumed or overwritten.

Repository evidence can change between calls, so identical options alone do not
guarantee byte-identical bundles from separate live runs. Parity means the same
report, snapshot, and options produce the same proposal content and readiness.
These are local review artifacts and can include repository file contents; they
should not be published wholesale.

## Validation

Tests exercise five and ten repositories with both real report readers and fixed
context snapshots, comparing every batch bundle with the single-repository command.
They cover continuation, exit codes, Enterprise token isolation, approvals, duplicate
entries, malformed configuration, filesystem failures, and the ten-repository demo
manifest. HTTP simulations verify that batch processing makes no GitHub writes.
