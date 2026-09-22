# Remedy catalogs

These catalogs map RepoAuditor (`RA`) and OpenSSF Scorecard (`OSSF`) findings to
proposed responses. They contain 68 remedy definitions across five topic files.
The definitions are data. [`propose`](../../../../doc/repository-context.md) gathers
repository context and uses them to create concrete issue or draft PR proposals.
[`publish`](../../../../doc/publishing.md) publishes selected, confirmed remedies
and persists receipts.

## Organization

| Catalog | Remedies | Contents |
| --- | ---: | --- |
| [documentation.toml](documentation.toml) | 9 | README, contribution guidance, security policy, licensing files and community templates. |
| [repository-settings.toml](repository-settings.toml) | 20 | Repository features, merge preferences, security settings and webhooks. |
| [branch-protection.toml](branch-protection.toml) | 21 | Review requirements, required checks and restrictions on branch changes. |
| [engineering.toml](engineering.toml) | 12 | CI, dependency tooling, workflow repairs, testing and release practices. |
| [maintainer-decisions.toml](maintainer-decisions.toml) | 6 | License intent, visibility, participation and maintenance commitments. |

The template assets have three directories:

```text
templates/
  catalog/  # Remedy definitions grouped by topic
  bodies/   # Five shared issue/PR body templates
  files/    # Ten proposed-file assets, such as SECURITY.md and CONTRIBUTING.md
```

A topic groups related findings. A body determines how a proposal is presented.
These are independent: a code-of-conduct remedy belongs in the documentation
catalog, but can request a maintainer decision before offering a file-creation PR.

The SAST remedy uses an engineering issue because configuring static analysis may
require workflow changes. The webhook remedy uses a decision issue to assign
private authentication setup and verification; it does not request an approved
setting value. Its inputs must contain only non-secret configuration status and
verification details, never credentials or authenticated webhook URLs.

## Five shared bodies

| Body | Purpose |
| --- | --- |
| [Settings issue](../bodies/settings-issue.md) | Request an approved setting change, including its location and expected value. |
| [Engineering issue](../bodies/engineering-issue.md) | Describe affected components and implementation work. |
| [Maintainer decision issue](../bodies/decision-issue.md) | Request a decision about project policy or commitments. |
| [Documentation issue](../bodies/documentation-issue.md) | Request documentation or configuration after checking existing files. |
| [File-creation PR](../bodies/create-files-pr.md) | Propose new files using approved content. |

Every remedy defines an issue route; nine also define a PR route. The shared bodies
replace 77 separate issue/PR bodies. The [proposed-file assets](../files/) remain
distinct because formats such as README, CODEOWNERS and citation metadata differ.

## Reading a definition

Each topic file declares `schema_version = 3`. Entries are keyed by stable ID, for
example `[remedies."ra-contributing"]` in [documentation.toml](documentation.toml).
IDs must be unique across catalogs and stay the same when an entry moves topics.

| Field | Meaning |
| --- | --- |
| `sources` | Exact auditor and check identifiers; match both origin and identifier. |
| `response` | Remedy-specific guidance, stored once and used by both routes. |
| `issue` | Title, shared body filename and required runtime inputs for an issue. |
| `pr` | Optional title, body, change summary, required inputs, guards and proposed files. |

Route `body` filenames resolve within `bodies/`. A PR file's `template` resolves
within `files/`, while its `path` is the destination in the target repository.
Paths must stay within their respective roots.

Titles, bodies and proposed files use `${name}` placeholders. `required_inputs`
lists all runtime inputs they need. Supply `response` from the definition and
`change_summary` from the PR route as fixed values, not user-overridable inputs.
Substitute once: inserted values remain literal, even if they contain `${...}`.
Missing inputs must remain visible as `needs-input`; incomplete proposals cannot
be published.

PRs currently support file creation only. All four guards must pass:
`confirmed_gap`, `target_absent`, `no_equivalent_file` and `approved_inputs`.
Existing-file editing requires a future editing strategy. Issue/PR routes describe
available proposals; they do not establish that a finding is actionable or that
validation has run.

## Current limitations

- The catalogs declare 25 distinct runtime input fields; each proposal requires
  only its selected route's 5–10 fields. Context retrieval resolves available facts
  and unambiguous documentation sections; missing or conflicting information remains explicit.
  Report data should provide identity and evidence; repository inspection should
  provide current state; remedy logic should provide instructions and verification
  guidance. Maintainers should supply missing facts and approve policy decisions.
- Catalog inputs have names; resolved values record their sources and must be
  nonempty strings when user-supplied. Domain-specific input validators are not implemented. Some
  file assets require complete maintainer-supplied content. Presence alone does not
  establish that settings instructions are actionable or generated files are valid.
- Check matching does not establish applicability. `propose` enforces file-creation
  guards and preserves unavailable or stale evidence. Existing/alternate files and
  uncertain absence require review. Automatic re-auditing of settings and engineering
  checks, and merging overlapping findings, are not implemented.
- `propose` chooses an eligible PR when its inputs are complete and explicitly
  approved; otherwise it offers the issue route with reasons. Citation and CODEOWNERS
  PRs remain blocked pending dedicated format/access validators. Their issue routes
  remain available. `--route` can request a specific route without bypassing guards.
- Saved proposals retain report, context and catalog provenance, rendered content,
  file diffs, input approvals and readiness reasons. `publish` selects only ready
  content, rechecks target state and duplicates, requires explicit confirmation and
  persists receipts. Input approval is not publication authorization.
- Asset and proposal tests check structure, rendering and guards. They do not run
  target repository commands or prove audit improvements. Review evidence and inputs
  for private content before publication; local context must not be posted wholesale.

## Adding or updating a remedy

1. Choose the topic catalog and add or update its stable remedy ID.
2. Declare the exact source checks and write the specific response.
3. Select a shared body and list its runtime inputs. Reuse bodies across remedies.
4. If offering a PR, declare its guards, target paths and any required file assets.
5. Update the matching rows in the [finding catalog](../../../../doc/catalog.md),
   including the remedy ID and link to its topic file.
6. Run `uv run pytest tests/template_assets_test.py --no-cov` from the repository root.

The asset tests check unique IDs and source mappings, catalog links, body selection,
input declarations, paths and referenced assets. See the
[design](../../../../doc/design.md#non-llm-templates) for the broader workflow and
preview/publication requirements.
