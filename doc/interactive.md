# Interactive single-repository remediation

Start with an existing RepoAuditor or OpenSSF Scorecard report:

```shell
uv run RepoRemedy inspect report.txt --report-type repoauditor \
  --repo OWNER/REPO --interactive --plan remedy-plan.json
```

Use `--report-type ossf-scorecard` for Scorecard JSON. The report is read offline
first. Browse findings and evidence, then choose **Select remedies** to collect
repository context. Collection uses `--ref` when supplied, otherwise the report's audited commit,
otherwise the repository's live default branch (including `master` or `trunk`).
The resolved target branch and commit are displayed before publication. To select
another branch for a new session, add `--ref release/1.x`. Offline inspection
rejects `--ref`; resume retains its recorded target and rejects ref overrides. Set `REPOREMEDY_TOKEN` in your
environment before continuing, or use `--token-env ENTERPRISE_TOKEN` for another
host-appropriate variable. Tokens are never stored in the plan.

The terminal interface uses [Textual](https://textual.textualize.io/). It supports
keyboard navigation and mouse input. `Tab` moves between controls; arrow keys
browse lists; `Space` toggles a remedy or checkbox. `Ctrl+S` saves the session and
`Ctrl+Q` saves and exits. Both shortcuts also work inside review and input dialogs.
The main screens also provide labeled save/exit buttons.
The layout follows the terminal mockups with a dark background, aligned columns,
status colors and evidence below the remedy list. It adapts to 80×24 terminals;
120×40 or larger provides more room for findings and previews. Terminal fonts and
the `NO_COLOR` environment setting remain under the user's control.

While browsing remedies, `/` focuses search, `F` focuses the filter, `A` selects
eligible filtered rows and `Enter` starts review. `Escape` leaves search. These
single-letter shortcuts do not intercept typing in input fields. During review,
`Enter` approves the current proposal, `E` edits inputs, `D` deselects and `Escape`
returns. In multiline input forms, `Enter` inserts a newline; use the button or
`Ctrl+Enter` to generate a preview.

## Select and review

1. Search remedy IDs or report evidence. Filter by readiness or selection.
2. Select individual remedies, or select/clear all eligible remedies in the
   current filter. Selections outside the filter stay intact.
3. Choose **Review**. Each selected proposal shows evidence, reasons, the issue
   body and any exact file diffs. **Back** returns to the selection list.
4. Use **Edit inputs / route** to choose an issue or an available draft PR route.
   Fill the catalog fields, approve those values, and generate the preview.
5. Choose **Approve / next** for each ready proposal, or deselect it. Input
   approval and content review are separate. `Ctrl+S` in an input form saves
   incomplete values and the chosen route as an **unapproved draft**. `Ctrl+Q`
   saves that draft and exits. On resume, select Review then Edit inputs to
   restore it. Saved drafts block approval/publication until you generate and
   review the new preview or explicitly **Discard saved draft** and review the
   original proposal. Cancel closes the form without applying unsaved edits;
   previously saved drafts remain available. Changing inputs or routes clears
   the affected content review. Blocked proposals cannot be approved.
6. When every selection has been reviewed, the **Review complete** screen shows
   ready/attention counts and the draft PR/issue split. Save and exit, change the
   selection, or continue to publication checks. No publication happens here.

PR review shows the exact file diffs first, with colored added/removed lines;
the complete PR description follows. Issue review includes the complete issue
body. Scroll through longer proposals before approving.

The UI offers a draft PR for catalog remedies with a PR definition and shows why
it is not yet ready. This avoids silently falling back to an issue while a user
is completing PR inputs. Existing-file edits and the catalog's unsupported PR
routes remain blocked. The user can explicitly choose an issue instead.

Unsupported or unavailable findings remain visible. Multiple findings with the
same remedy ID are marked not selectable because the current publisher requires
one unambiguous proposal. This increment does not combine audit sources or
discard duplicate evidence. Use one report for one repository per plan.

## Save and resume

```shell
uv run RepoRemedy inspect --resume remedy-plan.json
```

Resume opens **Saved session restored**, with actual selection/review counts and
choices to continue to publication, review proposals, change selections or save
and exit. Restoring a session itself makes no network requests.

The versioned JSON plan embeds the existing proposal bundle, selections, inputs,
route choices, unapproved input drafts, the requested ref and exact-content review digests. It is written atomically and can
also be saved before context collection or before all inputs/reviews are complete.
An existing plan is never replaced by a new inspection; resume it or choose a
different `--plan` path. Use one session per plan file at a time.

The plan contains local report/context evidence and proposed content. Keep it
local for review; the publisher sends only selected issue/PR content. The receipt
path defaults to `publication-receipts.json` beside the plan, and is a typed path
in the plan schema. Use separate directories or distinct receipt paths for
different repositories. Relative receipt paths resolve against the plan location.

## Publish the reviewed plan

Choose **Publish** from the selection screen, or reopen directly at confirmation:

```shell
uv run RepoRemedy publish --plan remedy-plan.json
```

Every selected proposal must be ready and reviewed. The screen names the target
repository and selected issue/draft-PR counts, then runs read-only preflight.
It checks saved content, existing GitHub matches and receipt reconciliation; new
objects also undergo the publisher's route, branch, evidence and publication-branch
checks. It reports expected creations, existing results to reuse and blockers.
These checks issue GET requests only and do not create or modify receipt files.
The reviewed plan is saved locally before the checks begin.

Confirmation is disabled until every selection passes. Check the confirmation
box and choose **Publish selected**. Existing matches can be reused without
creation permissions or a fresh base branch. Preflight is a snapshot, not a write
permission guarantee or a lock on GitHub: publication repeats validation and can
still be rejected. Selecting or reviewing remedies never publishes.

The existing publisher checks target freshness and permissions before each new
publication, reuses matching existing objects, and records each completed result
before proceeding. The UI shows progress, created/reused results and their actual
links. Select a result and choose **Open selected result** to view it in a browser.
Draft PRs require maintainer review and merging; issues request maintainer action.
Repository settings are not changed automatically.

The progress and completion views show created, reused, failed/blocked, unresolved
and remaining counts separately. Results have readable remedy, outcome and action
columns, with the selected result's actual URL displayed below.

If publication stops, completed results and the plan remain available. Inspect
the receipt journal, then choose **Check again / retry** or reopen the command.
Every retry runs preflight again and clears the confirmation checkbox. Matching
existing objects are reused. Uncertain attempts still require reconciliation and
are never blindly recreated. A stale branch or changed catalog requires generating
and reviewing a new plan from an appropriate audit; resuming does not refresh or
silently approve changed content. See [publication rules](publishing.md).

For automation, explicit confirmation publishes the saved selections and emits
the existing receipt JSON format:

```shell
uv run RepoRemedy publish --plan remedy-plan.json --confirm
```

The plan supplies repository, selections, receipt path and token-variable name.
Do not mix `--plan` with the legacy bundle/selection arguments. The UI requires a
terminal; JSON `inspect`, `propose`, `propose-batch` and legacy `publish` remain
available unchanged for scripts. LLM-assisted proposals and cohort UI are outside
this increment.

## Tests and module boundaries

`plan.py` owns saved state and review validity. `review.py` provides library form
and preview controls. `tui.py` coordinates screens and background workers.
`interactive.py` adapts the CLI; `tui.tcss` contains presentation styles. Read-only
preflight and publication reuse validation and reconciliation helpers in the
publisher. Publication progress callbacks run after durable receipt saves.

```shell
uv run pytest tests/plan_test.py tests/interactive_test.py tests/review_test.py tests/tui_test.py --no-cov
```

Tests run the real Textual controls headlessly, with simulated GitHub responses,
including selection across filters, input completion, review invalidation,
save/resume, read-only preflight, keyboard navigation, 80×24 layout bounds,
explicit confirmation, publication and duplicate reuse. They do not
create live GitHub objects.
